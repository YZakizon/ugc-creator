import asyncio
import os
from uuid import UUID

from celery import Task

from app.core.media_naming import generated_media_filename
from app.db.session import create_database_engine, session_factory
from app.job_tts_repository import JobTTSRepository
from app.providers.storage.local import LocalStorageProvider
from app.providers.tts.contracts import TTSProvider, TTSProviderError, TTSRequest
from app.providers.tts.elevenlabs import ElevenLabsTTSProvider
from app.providers.tts.fake import FakeTTSProvider
from app.repositories import SqlAlchemyConfigurationRepository
from app.workers.celery_app import celery_app
from app.workers.retry import retry_provider_error


def tts_provider(provider_name: str) -> TTSProvider:
    if provider_name != "elevenlabs":
        raise ValueError(f"Unsupported TTS provider: {provider_name}")
    return (
        FakeTTSProvider()
        if os.getenv("UGC_FAKE_PROVIDERS") == "1"
        else ElevenLabsTTSProvider()
    )


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="ugc_creator.generate_job_tts",
    max_retries=3,
)
def generate_job_tts(task: Task, job_id: str) -> dict[str, str]:
    engine = create_database_engine()
    if engine is None:
        raise RuntimeError("DATABASE_URL is required for job speech generation")
    repo = JobTTSRepository(session_factory(engine))
    context = repo.claim(UUID(job_id))
    if context is None:
        return {"job_id": job_id, "status": "unchanged"}
    voice = context.voice_profile
    settings = dict(voice.extra_settings)
    output_format = str(settings.pop("output_format", "mp3_44100_128"))
    language_code = settings.pop("language_code", None)
    settings.update(
        {
            key: value
            for key, value in {
                "speed": voice.speed,
                "stability": voice.stability,
                "similarity_boost": voice.similarity,
                "style": voice.style_exaggeration,
            }.items()
            if value is not None
        }
    )
    model_id = (
        voice.provider_model
        or os.getenv("ELEVENLABS_DEFAULT_MODEL")
        or "eleven_multilingual_v2"
    )
    try:
        result = asyncio.run(
            tts_provider(voice.provider).synthesize(
                TTSRequest(
                    text=context.speech_script,
                    voice_id=voice.provider_voice_id,
                    model_id=model_id,
                    output_format=output_format,
                    language_code=str(language_code) if language_code else None,
                    voice_settings=settings,
                )
            )
        )
        filename = generated_media_filename(
            context.topic,
            context.content_number,
            context.audio_number,
            result.extension,
        )
        object_key = (
            f"topics/{context.batch_id}/contents/{context.job_id}/audio/{filename}"
        )
        LocalStorageProvider().put(object_key, result.audio)
        completed = repo.complete(
            context,
            provider_request_id=result.provider_request_id,
            model_id=model_id,
            settings={
                **settings,
                "output_format": output_format,
                "language_code": language_code,
            },
            object_key=object_key,
            filename=filename,
            content_type=result.content_type,
            size_bytes=len(result.audio),
        )
        return {
            "job_id": job_id,
            "status": completed.status if completed is not None else "claim_lost",
        }
    except TTSProviderError as exc:
        if exc.retriable:
            repo.release_for_retry(context, str(exc), exc.provider_request_id)
            retry_provider_error(task, exc, retriable=True)
        repo.fail(context, str(exc), exc.provider_request_id)
        return {"job_id": job_id, "status": "failed"}
    except Exception:
        repo.fail(context, "Speech generation failed unexpectedly.", None)
        raise


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="ugc_creator.generate_voice_preview",
    max_retries=3,
)
def generate_voice_preview(task: Task, preview_id: str) -> dict[str, str]:
    engine = create_database_engine()
    if engine is None:
        raise RuntimeError("DATABASE_URL is required for voice previews")
    repository = SqlAlchemyConfigurationRepository(session_factory(engine))
    preview_uuid = UUID(preview_id)
    preview = repository.get_voice_preview(preview_uuid)
    if preview is None:
        raise RuntimeError("Voice preview not found")
    if preview.status == "completed" and preview.asset_key:
        return {"preview_id": preview_id, "status": preview.status}
    claim = repository.claim_voice_preview(preview_uuid)
    if claim is None:
        status, retry_after = repository.reconcile_voice_preview_claim(preview_uuid)
        if retry_after:
            generate_voice_preview.apply_async(args=[preview_id], countdown=retry_after)
        return {"preview_id": preview_id, "status": status}
    preview, claim_token = claim
    settings = dict(preview.settings_json)
    output_format = str(settings.pop("output_format", "mp3_44100_128"))
    language_code = settings.pop("language_code", None)
    voice_settings = {
        key: value for key, value in settings.items() if value is not None
    }
    provider = (
        FakeTTSProvider()
        if os.getenv("UGC_FAKE_PROVIDERS") == "1"
        else ElevenLabsTTSProvider()
    )
    try:
        result = asyncio.run(
            provider.synthesize(
                TTSRequest(
                    text=preview.text,
                    voice_id=preview.provider_voice_id,
                    model_id=preview.provider_model
                    or os.getenv("ELEVENLABS_DEFAULT_MODEL")
                    or "eleven_multilingual_v2",
                    output_format=output_format,
                    language_code=str(language_code) if language_code else None,
                    voice_settings=voice_settings,
                )
            )
        )
        asset_key = f"voice-previews/{preview.id}/speech.{result.extension}"
        LocalStorageProvider().put(asset_key, result.audio)
        completed = repository.update_voice_preview(
            preview_uuid,
            status="completed",
            provider_request_id=result.provider_request_id,
            asset_key=asset_key,
            content_type=result.content_type,
            filename=f"voice-preview-{preview.id}.{result.extension}",
            generated_usage_units=(
                result.usage.generated_units if result.usage else None
            ),
            account_used_units=(
                result.usage.account_used_units if result.usage else None
            ),
            account_limit_units=(
                result.usage.account_limit_units if result.usage else None
            ),
            account_remaining_units=(
                result.usage.account_remaining_units if result.usage else None
            ),
            usage_resets_at_unix=(
                result.usage.resets_at_unix if result.usage else None
            ),
            usage_unit=result.usage.unit if result.usage else None,
            claim_token=claim_token,
        )
        return {
            "preview_id": preview_id,
            "status": completed.status if completed is not None else "claim_lost",
        }
    except TTSProviderError as exc:
        if exc.retriable:
            repository.update_voice_preview(
                preview_uuid,
                status="queued",
                provider_request_id=exc.provider_request_id,
                error_message=str(exc),
                claim_token=claim_token,
            )
            retry_provider_error(task, exc, retriable=True)
        repository.update_voice_preview(
            preview_uuid,
            status="failed",
            provider_request_id=exc.provider_request_id,
            error_message=str(exc),
            claim_token=claim_token,
        )
        return {"preview_id": preview_id, "status": "failed"}
    except Exception:
        repository.update_voice_preview(
            preview_uuid,
            status="failed",
            error_message="Speech generation failed unexpectedly.",
            claim_token=claim_token,
        )
        raise
