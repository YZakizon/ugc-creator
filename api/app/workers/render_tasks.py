import asyncio
import os
from datetime import UTC, datetime
from pathlib import PurePath
from uuid import UUID

from app.core.media_naming import generated_media_filename
from app.db.session import create_database_engine, session_factory
from app.providers.render.comfyui import (
    ComfyUIProviderError,
    ComfyUIRenderer,
    ComfyUISubmissionOutcomeUnknown,
)
from app.providers.render.contracts import RenderOutput, RenderRequest
from app.providers.storage.local import LocalStorageProvider, StorageError
from app.render_repository import RenderExecutionRepository
from app.services.media_service import MediaProcessingError, probe_audio_duration
from app.services.workflow_service import (
    WorkflowValidationError,
    prepare_workflow,
    randomize_unbound_comfyui_seeds,
    workflow_uses_audio_duration,
)
from app.workers.celery_app import celery_app


def render_has_timed_out(
    submitted_at: datetime,
    timeout_seconds: int,
    *,
    current_time: datetime | None = None,
) -> bool:
    checked_at = current_time or datetime.now(UTC)
    if submitted_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=None)
    return (checked_at - submitted_at).total_seconds() >= timeout_seconds


def repository() -> RenderExecutionRepository:
    engine = create_database_engine()
    if engine is None:
        raise RuntimeError("DATABASE_URL is required for rendering")
    return RenderExecutionRepository(session_factory(engine))


def render_input_filename(filename: str, attempt_id: UUID | str) -> str:
    """Give each render fresh ComfyUI input names to bypass stale node caches."""
    return f"{attempt_id}-{PurePath(filename).name}"


async def apply_default_workflow_media(
    values: dict[str, object],
    metadata: dict[str, object],
    renderer: ComfyUIRenderer,
    storage: LocalStorageProvider,
    *,
    measure_audio_duration: bool = False,
    upload_namespace: str | None = None,
) -> None:
    media = metadata.get("default_workflow_media", metadata.get("workflow_media", {}))
    if not isinstance(media, dict):
        return
    for key, input_type in (("source_image", "image"), ("audio", "audio")):
        if values.get(key) not in (None, ""):
            continue
        asset_key = media.get(key)
        if isinstance(asset_key, str) and asset_key:
            content = storage.get(asset_key)
            if (
                key == "audio"
                and measure_audio_duration
                and "audio_duration" not in values
            ):
                values["audio_duration"] = probe_audio_duration(
                    content, PurePath(asset_key).name
                )
            source_name = PurePath(asset_key).name
            upload_name = (
                render_input_filename(source_name, upload_namespace)
                if upload_namespace
                else source_name
            )
            values[key] = await renderer.upload(upload_name, content, input_type)


async def _prepare_and_submit(attempt_id: UUID) -> None:
    repo = repository()
    existing = repo.get_attempt(attempt_id)
    if existing is None:
        raise LookupError("Render attempt not found")
    if existing.external_job_id:
        monitor_render.apply_async(args=[str(attempt_id)], countdown=1)
        return
    if existing.status in {"completed", "failed", "cancelled"}:
        return
    if existing.status == "submitting_render":
        expires_at = existing.submission_claim_expires_at
        checked_at = datetime.now(UTC)
        if expires_at is not None:
            if expires_at.tzinfo is None:
                checked_at = checked_at.replace(tzinfo=None)
            remaining = int((expires_at - checked_at).total_seconds())
            if remaining > 0:
                submit_render.apply_async(
                    args=[str(attempt_id)], countdown=max(1, remaining)
                )
                return
        renderer = ComfyUIRenderer(
            base_url=repo.execution_context(attempt_id)[3].base_url,
            client_id=existing.client_id,
        )
        try:
            prompt_id = (
                await renderer.find_submission(existing.client_id)
                if existing.client_id and existing.submission_started_at is not None
                else None
            )
        except ComfyUIProviderError as exc:
            raise ComfyUISubmissionOutcomeUnknown(
                "ComfyUI submission reconciliation is temporarily unavailable"
            ) from exc
        if prompt_id and repo.save_submission(
            attempt_id, prompt_id, existing.client_id
        ):
            monitor_render.apply_async(args=[str(attempt_id)], countdown=1)
            return
        repo.update_progress(
            attempt_id,
            "failed",
            existing.progress,
            "ComfyUI submission outcome is unknown; it was not resubmitted "
            "automatically. Retry render to create a new attempt.",
        )
        return
    claimed, retry_after = repo.claim_submission(attempt_id)
    if not claimed:
        if retry_after:
            submit_render.apply_async(args=[str(attempt_id)], countdown=retry_after)
        return
    attempt, job, profile, node, template = repo.execution_context(attempt_id)
    renderer = ComfyUIRenderer(base_url=node.base_url, client_id=attempt.client_id)
    if attempt.external_job_id:
        monitor_render.apply_async(args=[str(attempt_id)], countdown=1)
        return
    values = dict(profile.default_parameters)
    needs_audio_duration = workflow_uses_audio_duration(attempt.workflow_snapshot)
    values.update(
        {
            "script": job.speech_script or job.topic,
            "topic": job.topic,
            "hook": job.hook or "",
            "video_prompt": profile.prompt_template or job.speech_script or job.topic,
            "duration": job.target_duration_seconds,
            "character_name": profile.character.name,
        }
    )
    audio_asset = next(
        (asset for asset in job.media_assets if asset.kind == "audio"), None
    )
    if audio_asset is not None:
        storage = LocalStorageProvider()
        audio_content = storage.get(audio_asset.object_key)
        if needs_audio_duration:
            values["audio_duration"] = probe_audio_duration(
                audio_content, audio_asset.filename
            )
        values["audio"] = await renderer.upload(
            render_input_filename(audio_asset.filename, attempt_id),
            audio_content,
            "audio",
        )
    await apply_default_workflow_media(
        values,
        template.metadata_json,
        renderer,
        LocalStorageProvider(),
        measure_audio_duration=needs_audio_duration,
        upload_namespace=str(attempt_id),
    )
    workflow = prepare_workflow(
        attempt.workflow_snapshot, attempt.binding_snapshot, values
    )
    resolved_seeds = randomize_unbound_comfyui_seeds(workflow, attempt.binding_snapshot)
    if resolved_seeds:
        values["comfyui_seeds"] = resolved_seeds
    repo.save_prepared(attempt_id, workflow, values)
    if not repo.mark_submission_started(attempt_id):
        submit_render.apply_async(args=[str(attempt_id)], countdown=1)
        return
    submission = await renderer.submit(
        RenderRequest(workflow=workflow, client_id=attempt.client_id)
    )
    if repo.save_submission(
        attempt_id, submission.external_job_id, submission.client_id
    ):
        monitor_render.apply_async(args=[str(attempt_id)], countdown=3)


@celery_app.task(name="ugc_creator.submit_render")  # type: ignore[untyped-decorator]
def submit_render(attempt_id: str) -> dict[str, str]:
    attempt_uuid = UUID(attempt_id)
    try:
        asyncio.run(_prepare_and_submit(attempt_uuid))
        return {"attempt_id": attempt_id, "status": "submitted"}
    except ComfyUISubmissionOutcomeUnknown:
        # Keep the durable submission intent intact. A follow-up delivery will
        # search ComfyUI queue/history by the persisted client ID and will never
        # blindly resubmit an operation whose result may have been accepted.
        submit_render.apply_async(args=[attempt_id], countdown=5)
        return {"attempt_id": attempt_id, "status": "reconciling"}
    except (
        ComfyUIProviderError,
        WorkflowValidationError,
        MediaProcessingError,
        StorageError,
        ValueError,
        LookupError,
    ) as exc:
        repository().update_progress(attempt_uuid, "failed", 0, str(exc))
        return {"attempt_id": attempt_id, "status": "failed"}


async def _monitor(attempt_id: UUID) -> str:
    repo = repository()
    attempt, _job, _profile, node, _template = repo.execution_context(attempt_id)
    if attempt.status in {"completed", "failed", "cancelled"}:
        return attempt.status
    if not attempt.external_job_id:
        raise ValueError("Render attempt has no ComfyUI prompt ID")
    timeout_seconds = max(60, int(os.getenv("RENDER_TIMEOUT_SECONDS", "3600")))
    if attempt.submitted_at is not None and render_has_timed_out(
        attempt.submitted_at, timeout_seconds
    ):
        repo.update_progress(
            attempt_id,
            "failed",
            attempt.progress,
            f"Render timed out after {timeout_seconds} seconds",
        )
        return "failed"
    renderer = ComfyUIRenderer(base_url=node.base_url, client_id=attempt.client_id)
    status = await renderer.get_status(attempt.external_job_id)
    if status.state in {"queued", "running"}:
        live_progress = await renderer.get_live_progress(attempt.external_job_id)
        progress = (
            max(attempt.progress, 1)
            if status.progress is None and live_progress is None
            else max(
                attempt.progress,
                1,
                int(status.progress or 0),
                int(live_progress or 0),
            )
        )
        repo.update_progress(
            attempt_id,
            "rendering",
            progress,
        )
        monitor_render.apply_async(args=[str(attempt_id)], countdown=5)
        return "rendering"
    if status.state != "completed":
        repo.update_progress(
            attempt_id,
            "failed",
            attempt.progress,
            status.message or "ComfyUI render failed",
        )
        return "failed"
    claimed, retry_after = repo.claim_finalization(attempt_id)
    if not claimed:
        if retry_after:
            monitor_render.apply_async(args=[str(attempt_id)], countdown=retry_after)
            return "downloading_output"
        current = repo.get_attempt(attempt_id)
        return current.status if current is not None else "failed"
    outputs = await renderer.fetch_outputs(attempt.external_job_id)
    output = select_video_output(outputs)
    content, content_type = await renderer.download_output(output)
    video_number = (
        sum(1 for item in _job.render_attempts if item.status == "completed") + 1
    )
    extension = PurePath(output.filename).suffix.lstrip(".") or "mp4"
    output_name = generated_media_filename(
        _job.topic,
        _job.content_number,
        video_number,
        extension,
    )
    object_key = (
        f"topics/{_job.batch_id}/contents/{_job.id}/video/{attempt_id}/{output_name}"
    )
    LocalStorageProvider().put(object_key, content)
    repo.complete(
        attempt_id,
        object_key,
        output_name,
        content_type,
        len(content),
    )
    return "completed"


def select_video_output(outputs: list[RenderOutput]) -> RenderOutput:
    video_extensions = {".mp4", ".webm", ".mov", ".mkv", ".avi", ".gif"}
    for output in outputs:
        if output.media_type == "video" or PurePath(output.filename).suffix.lower() in (
            video_extensions
        ):
            return output
    raise ComfyUIProviderError(
        "ComfyUI completed without a downloadable video or GIF output"
    )


@celery_app.task(name="ugc_creator.monitor_render")  # type: ignore[untyped-decorator]
def monitor_render(attempt_id: str) -> dict[str, str]:
    attempt_uuid = UUID(attempt_id)
    try:
        result = asyncio.run(_monitor(attempt_uuid))
        return {"attempt_id": attempt_id, "status": result}
    except (ComfyUIProviderError, StorageError, ValueError, LookupError) as exc:
        repository().update_progress(attempt_uuid, "failed", 0, str(exc))
        return {"attempt_id": attempt_id, "status": "failed"}
