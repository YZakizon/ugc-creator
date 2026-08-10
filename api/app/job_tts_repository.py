from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, selectinload, sessionmaker

from app.core.statuses import JobStatus
from app.db.models import MediaAsset, RenderProfile, TopicJob, VoiceProfile

CLAIM_DURATION = timedelta(minutes=5)


@dataclass(frozen=True)
class JobTTSContext:
    job_id: UUID
    batch_id: UUID
    speech_script: str
    voice_profile: VoiceProfile
    claim_token: UUID


class JobTTSRepository:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self.factory = factory

    def claim(self, job_id: UUID) -> JobTTSContext | None:
        claimed_at = datetime.now(UTC)
        claim_token = uuid4()
        with self.factory() as session:
            job = session.scalar(
                select(TopicJob)
                .options(selectinload(TopicJob.media_assets))
                .where(TopicJob.id == job_id)
            )
            if job is None:
                raise LookupError("Job not found")
            if any(asset.kind == "audio" for asset in job.media_assets):
                job.status = JobStatus.READY_TO_RENDER.value
                job.tts_claim_token = None
                job.tts_claim_expires_at = None
                session.commit()
                return None
            if not job.speech_script:
                raise ValueError("Job has no generated speech script")
            if job.tts_claim_token is not None:
                expires_at = job.tts_claim_expires_at
                comparable_now = claimed_at
                if expires_at is not None and expires_at.tzinfo is None:
                    comparable_now = claimed_at.replace(tzinfo=None)
                if expires_at is None or expires_at <= comparable_now:
                    job.status = JobStatus.FAILED.value
                    job.error_message = (
                        "Speech generation stopped before its result was saved. Its "
                        "provider outcome is unknown; retry manually to avoid an "
                        "automatic duplicate paid request."
                    )
                    job.tts_claim_token = None
                    job.tts_claim_expires_at = None
                    session.commit()
                return None
            profile = (
                session.get(RenderProfile, job.render_profile_id)
                if job.render_profile_id
                else None
            )
            voice_profile_id = job.voice_profile_id or (
                profile.voice_profile_id if profile else None
            )
            if voice_profile_id is None:
                raise ValueError("Job has no voice profile")
            voice = session.get(VoiceProfile, voice_profile_id)
            if voice is None:
                raise ValueError("Voice profile is unavailable")
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(TopicJob)
                    .where(
                        TopicJob.id == job_id,
                        TopicJob.status == JobStatus.GENERATING_TTS.value,
                        TopicJob.tts_claim_token.is_(None),
                    )
                    .values(
                        tts_claim_token=claim_token,
                        tts_claim_expires_at=claimed_at + CLAIM_DURATION,
                        updated_at=claimed_at,
                    )
                ),
            )
            if result.rowcount != 1:
                session.rollback()
                return None
            session.commit()
            session.expunge(voice)
            return JobTTSContext(
                job_id=job.id,
                batch_id=job.batch_id,
                speech_script=job.speech_script,
                voice_profile=voice,
                claim_token=claim_token,
            )

    def complete(
        self,
        context: JobTTSContext,
        *,
        provider_request_id: str | None,
        model_id: str,
        settings: dict[str, object],
        object_key: str,
        filename: str,
        content_type: str,
        size_bytes: int,
    ) -> TopicJob | None:
        completed_at = datetime.now(UTC)
        voice = context.voice_profile
        with self.factory() as session:
            job = session.scalar(
                select(TopicJob)
                .options(selectinload(TopicJob.media_assets))
                .where(TopicJob.id == context.job_id)
            )
            if job is None or job.tts_claim_token != context.claim_token:
                return None
            if not any(asset.kind == "audio" for asset in job.media_assets):
                session.add(
                    MediaAsset(
                        job_id=job.id,
                        render_attempt_id=None,
                        kind="audio",
                        object_key=object_key,
                        filename=filename,
                        content_type=content_type,
                        size_bytes=size_bytes,
                    )
                )
            job.tts_provider = voice.provider
            job.tts_voice_id = voice.provider_voice_id
            job.tts_model = model_id
            job.tts_settings = settings
            job.tts_provider_request_id = provider_request_id
            job.tts_generated_at = completed_at
            job.tts_claim_token = None
            job.tts_claim_expires_at = None
            job.status = JobStatus.READY_TO_RENDER.value
            job.error_message = None
            session.commit()
            session.refresh(job)
            return job

    def release_for_retry(
        self, context: JobTTSContext, message: str, provider_request_id: str | None
    ) -> None:
        with self.factory() as session:
            session.execute(
                update(TopicJob)
                .where(
                    TopicJob.id == context.job_id,
                    TopicJob.tts_claim_token == context.claim_token,
                )
                .values(
                    status=JobStatus.GENERATING_TTS.value,
                    error_message=message,
                    tts_provider_request_id=provider_request_id,
                    tts_claim_token=None,
                    tts_claim_expires_at=None,
                    updated_at=datetime.now(UTC),
                )
            )
            session.commit()

    def fail(
        self, context: JobTTSContext, message: str, provider_request_id: str | None
    ) -> None:
        with self.factory() as session:
            session.execute(
                update(TopicJob)
                .where(
                    TopicJob.id == context.job_id,
                    TopicJob.tts_claim_token == context.claim_token,
                )
                .values(
                    status=JobStatus.FAILED.value,
                    error_message=message,
                    tts_provider_request_id=provider_request_id,
                    tts_claim_token=None,
                    tts_claim_expires_at=None,
                    updated_at=datetime.now(UTC),
                )
            )
            session.commit()
