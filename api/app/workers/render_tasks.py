import asyncio
import os
from datetime import UTC, datetime
from pathlib import PurePath
from uuid import UUID

from app.db.session import create_database_engine, session_factory
from app.providers.render.comfyui import ComfyUIProviderError, ComfyUIRenderer
from app.providers.render.contracts import RenderRequest
from app.providers.storage.local import LocalStorageProvider, StorageError
from app.render_repository import RenderExecutionRepository
from app.services.workflow_service import WorkflowValidationError, prepare_workflow
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


async def apply_default_workflow_media(
    values: dict[str, object],
    metadata: dict[str, object],
    renderer: ComfyUIRenderer,
    storage: LocalStorageProvider,
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
            values[key] = await renderer.upload(
                PurePath(asset_key).name, content, input_type
            )


async def _prepare_and_submit(attempt_id: UUID) -> None:
    repo = repository()
    existing = repo.get_attempt(attempt_id)
    if existing is None:
        raise LookupError("Render attempt not found")
    if existing.external_job_id:
        monitor_render.apply_async(args=[str(attempt_id)], countdown=1)
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
    await apply_default_workflow_media(
        values, template.metadata_json, renderer, LocalStorageProvider()
    )
    workflow = prepare_workflow(
        attempt.workflow_snapshot, attempt.binding_snapshot, values
    )
    repo.save_prepared(attempt_id, workflow, values)
    submission = await renderer.submit(
        RenderRequest(workflow=workflow, client_id=attempt.client_id)
    )
    repo.save_submission(attempt_id, submission.external_job_id, submission.client_id)
    monitor_render.apply_async(args=[str(attempt_id)], countdown=3)


@celery_app.task(name="ugc_creator.submit_render")  # type: ignore[untyped-decorator]
def submit_render(attempt_id: str) -> dict[str, str]:
    attempt_uuid = UUID(attempt_id)
    try:
        asyncio.run(_prepare_and_submit(attempt_uuid))
        return {"attempt_id": attempt_id, "status": "submitted"}
    except (
        ComfyUIProviderError,
        WorkflowValidationError,
        StorageError,
        ValueError,
        LookupError,
    ) as exc:
        repository().update_progress(attempt_uuid, "failed", 0, str(exc))
        return {"attempt_id": attempt_id, "status": "failed"}


async def _monitor(attempt_id: UUID) -> str:
    repo = repository()
    attempt, _job, _profile, node, _template = repo.execution_context(attempt_id)
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
        repo.update_progress(
            attempt_id,
            "rendering",
            max(attempt.progress, 1, int(status.progress)),
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
    repo.update_progress(attempt_id, "downloading_output", 95)
    outputs = await renderer.fetch_outputs(attempt.external_job_id)
    if not outputs:
        raise ComfyUIProviderError("ComfyUI completed without a downloadable output")
    output = outputs[0]
    content, content_type = await renderer.download_output(output)
    output_name = PurePath(output.filename).name
    object_key = (
        f"batches/{_job.batch_id}/jobs/{_job.id}/video/{attempt.id}-{output_name}"
    )
    LocalStorageProvider().put(object_key, content)
    repo.complete(
        attempt_id,
        object_key,
        PurePath(output.filename).name,
        content_type,
        len(content),
    )
    return "completed"


@celery_app.task(name="ugc_creator.monitor_render")  # type: ignore[untyped-decorator]
def monitor_render(attempt_id: str) -> dict[str, str]:
    attempt_uuid = UUID(attempt_id)
    try:
        result = asyncio.run(_monitor(attempt_uuid))
        return {"attempt_id": attempt_id, "status": result}
    except (ComfyUIProviderError, StorageError, ValueError, LookupError) as exc:
        repository().update_progress(attempt_uuid, "failed", 0, str(exc))
        return {"attempt_id": attempt_id, "status": "failed"}
