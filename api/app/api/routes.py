import base64
import binascii
import hashlib
import json
import os
from pathlib import PurePath
from typing import cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response

from app.core.statuses import JobStatus
from app.core.urls import validate_render_node_url
from app.providers.render.comfyui import ComfyUIProviderError, ComfyUIRenderer
from app.providers.storage.local import LocalStorageProvider, StorageError
from app.providers.tts.contracts import TTSProviderError, TTSUsage
from app.providers.tts.elevenlabs import ElevenLabsTTSProvider
from app.render_repository import RenderExecutionRepository
from app.repositories import (
    BatchRepository,
    ConfigurationRepository,
    VoiceProfileInUseError,
    batch_to_dict,
    character_to_dict,
    job_to_dict,
    render_profile_to_dict,
    voice_preview_to_dict,
    voice_profile_to_dict,
    workflow_template_to_dict,
)
from app.schemas import (
    BatchCreate,
    BatchList,
    BatchRead,
    CharacterCreate,
    CharacterList,
    CharacterRead,
    DashboardSummary,
    JobRead,
    RenderAttemptList,
    RenderAttemptRead,
    RenderNodeCreate,
    RenderNodeList,
    RenderNodeRead,
    RenderProfileCreate,
    RenderProfileList,
    RenderProfileRead,
    RenderProfileSetupCreate,
    RenderProfileUpdate,
    TTSAccountUsageRead,
    TTSVoiceList,
    TTSVoiceRead,
    VoicePreviewCreate,
    VoicePreviewList,
    VoicePreviewRead,
    VoiceProfileCreate,
    VoiceProfileList,
    VoiceProfileRead,
    VoiceProfileUpdate,
    WorkflowMediaUpload,
    WorkflowMediaUploadRead,
    WorkflowTemplateCreate,
    WorkflowTemplateList,
    WorkflowTemplateRead,
)
from app.services.workflow_service import (
    WorkflowValidationError,
    validate_bindings,
    workflow_checksum,
)
from app.workers.content_tasks import generate_job_content
from app.workers.render_tasks import submit_render
from app.workers.tts_tasks import generate_voice_preview

router = APIRouter(prefix="/api/v1")


@router.get("/tts-providers/elevenlabs/usage", response_model=TTSAccountUsageRead)
async def get_elevenlabs_usage(request: Request) -> TTSAccountUsageRead:
    if os.getenv("UGC_FAKE_PROVIDERS") == "1":
        usage = TTSUsage(
            account_used_units=125,
            account_limit_units=10_000,
            account_remaining_units=9_875,
        )
        configured = True
    else:
        provider = ElevenLabsTTSProvider()
        if not provider.api_key:
            return TTSAccountUsageRead(
                provider="elevenlabs",
                configured=False,
                used_units=None,
                limit_units=None,
                remaining_units=None,
                resets_at_unix=None,
                unit="characters",
            )
        try:
            usage = await provider.get_account_usage()
            configured = True
        except TTSProviderError:
            repo = cast(
                ConfigurationRepository, request.app.state.configuration_repository
            )
            latest = repo.get_latest_voice_preview_usage()
            if latest is None:
                return TTSAccountUsageRead(
                    provider="elevenlabs",
                    configured=True,
                    used_units=None,
                    limit_units=None,
                    remaining_units=None,
                    resets_at_unix=None,
                    unit="characters",
                )
            usage = TTSUsage(
                account_used_units=latest.account_used_units,
                account_limit_units=latest.account_limit_units,
                account_remaining_units=latest.account_remaining_units,
                resets_at_unix=latest.usage_resets_at_unix,
                unit=latest.usage_unit or "characters",
            )
            configured = True
    return TTSAccountUsageRead(
        provider="elevenlabs",
        configured=configured,
        used_units=usage.account_used_units,
        limit_units=usage.account_limit_units,
        remaining_units=usage.account_remaining_units,
        resets_at_unix=usage.resets_at_unix,
        unit=usage.unit,
    )


@router.get("/tts-providers/elevenlabs/voices", response_model=TTSVoiceList)
async def get_elevenlabs_voices() -> TTSVoiceList:
    if os.getenv("UGC_FAKE_PROVIDERS") == "1":
        items = [
            TTSVoiceRead(
                voice_id="fake-voice-hope",
                name="Hope",
                category="generated",
                description="Deterministic fake ElevenLabs voice.",
                preview_url=None,
            )
        ]
    else:
        provider = ElevenLabsTTSProvider()
        if not provider.api_key:
            return TTSVoiceList(items=[], total=0)
        try:
            voices = await provider.list_voices()
        except TTSProviderError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": exc.category, "message": str(exc)},
            ) from exc
        items = [
            TTSVoiceRead.model_validate(voice, from_attributes=True) for voice in voices
        ]
    return TTSVoiceList(items=items, total=len(items))


def repository(request: Request) -> BatchRepository:
    return cast(BatchRepository, request.app.state.batch_repository)


def configuration_repository(request: Request) -> ConfigurationRepository:
    return cast(ConfigurationRepository, request.app.state.configuration_repository)


def render_repository(request: Request) -> RenderExecutionRepository:
    repo = getattr(request.app.state, "render_repository", None)
    if not isinstance(repo, RenderExecutionRepository):
        raise HTTPException(status_code=503, detail="Render persistence is unavailable")
    return repo


def render_node_read(node: object) -> RenderNodeRead:
    return RenderNodeRead.model_validate(node, from_attributes=True)


def render_attempt_read(attempt: object) -> RenderAttemptRead:
    data = {
        key: getattr(attempt, key)
        for key in (
            "id",
            "job_id",
            "render_profile_id",
            "render_node_id",
            "workflow_template_id",
            "provider",
            "status",
            "progress",
            "external_job_id",
            "error_message",
            "created_at",
            "updated_at",
        )
    }
    data["assets"] = [
        {
            "id": asset.id,
            "job_id": asset.job_id,
            "render_attempt_id": asset.render_attempt_id,
            "kind": asset.kind,
            "filename": asset.filename,
            "content_type": asset.content_type,
            "size_bytes": asset.size_bytes,
            "download_url": f"/api/v1/assets/{asset.id}/download",
            "created_at": asset.created_at,
        }
        for asset in getattr(attempt, "assets", [])
    ]
    return RenderAttemptRead.model_validate(data)


@router.post(
    "/render-nodes", response_model=RenderNodeRead, status_code=status.HTTP_201_CREATED
)
def create_render_node(
    payload: RenderNodeCreate,
    repo: RenderExecutionRepository = Depends(render_repository),
) -> RenderNodeRead:
    try:
        validated_url = validate_render_node_url(payload.base_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return render_node_read(
        repo.create_node(payload.model_copy(update={"base_url": validated_url}))
    )


@router.get("/render-nodes", response_model=RenderNodeList)
def list_render_nodes(
    repo: RenderExecutionRepository = Depends(render_repository),
) -> RenderNodeList:
    items = repo.list_nodes()
    return RenderNodeList(
        items=[render_node_read(item) for item in items], total=len(items)
    )


@router.post("/render-nodes/{node_id}/health", response_model=RenderNodeRead)
async def check_render_node(
    node_id: UUID, repo: RenderExecutionRepository = Depends(render_repository)
) -> RenderNodeRead:
    node = repo.get_node(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Render node not found")
    try:
        healthy = await ComfyUIRenderer(base_url=node.base_url).health_check()
        updated = repo.update_node_health(
            node_id, healthy, None if healthy else "ComfyUI health check failed"
        )
    except ComfyUIProviderError as exc:
        updated = repo.update_node_health(node_id, False, str(exc))
    return render_node_read(updated)


@router.delete("/render-nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_render_node(
    node_id: UUID, repo: RenderExecutionRepository = Depends(render_repository)
) -> None:
    try:
        deleted = repo.delete_node(node_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Render node not found")


@router.post(
    "/jobs/{job_id}/render",
    response_model=RenderAttemptRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def queue_render(
    job_id: UUID,
    node_id: UUID,
    repo: RenderExecutionRepository = Depends(render_repository),
) -> RenderAttemptRead:
    try:
        attempt = repo.queue_attempt(job_id, node_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    submit_render.delay(str(attempt.id))
    loaded = repo.get_attempt(attempt.id)
    return render_attempt_read(loaded or attempt)


@router.get("/render-attempts", response_model=RenderAttemptList)
def list_render_attempts(
    job_id: UUID | None = None,
    repo: RenderExecutionRepository = Depends(render_repository),
) -> RenderAttemptList:
    items = repo.list_attempts(job_id)
    return RenderAttemptList(
        items=[render_attempt_read(item) for item in items], total=len(items)
    )


@router.get("/assets/{asset_id}/download")
def download_asset(
    asset_id: UUID, repo: RenderExecutionRepository = Depends(render_repository)
) -> Response:
    asset = repo.get_asset(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Media asset not found")
    try:
        content = LocalStorageProvider().get(asset.object_key)
    except StorageError as exc:
        raise HTTPException(
            status_code=503, detail="Media asset is unavailable"
        ) from exc
    return Response(
        content=content,
        media_type=asset.content_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{asset.filename}"'},
    )


@router.post("/batches", response_model=BatchRead, status_code=status.HTTP_201_CREATED)
def create_batch(
    payload: BatchCreate,
    repo: BatchRepository = Depends(repository),
    configuration_repo: ConfigurationRepository = Depends(configuration_repository),
) -> BatchRead:
    if payload.default_render_profile_id is not None:
        profile = configuration_repo.get_render_profile(
            payload.default_render_profile_id
        )
        if profile is None:
            raise HTTPException(status_code=422, detail="Render profile not found")
        if profile.voice_profile_id is None:
            raise HTTPException(
                status_code=422,
                detail="Render profile requires a connected voice profile",
            )
    return BatchRead.model_validate(batch_to_dict(repo.create_batch(payload)))


@router.get("/batches", response_model=BatchList)
def list_batches(
    repo: BatchRepository = Depends(repository),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> BatchList:
    batches, total = repo.list_batches(limit, offset)
    return BatchList(
        items=[BatchRead.model_validate(batch_to_dict(batch)) for batch in batches],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/batches/{batch_id}", response_model=BatchRead)
def get_batch(batch_id: UUID, repo: BatchRepository = Depends(repository)) -> BatchRead:
    batch = repo.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    return BatchRead.model_validate(batch_to_dict(batch))


@router.get("/jobs/{job_id}", response_model=JobRead)
def get_job(job_id: UUID, repo: BatchRepository = Depends(repository)) -> JobRead:
    job = repo.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobRead.model_validate(job_to_dict(job))


@router.post(
    "/jobs/{job_id}/generate-content",
    response_model=JobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def queue_content_generation(
    job_id: UUID, repo: BatchRepository = Depends(repository)
) -> JobRead:
    job = repo.queue_job_for_content(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    generate_job_content.delay(str(job_id))
    return JobRead.model_validate(job_to_dict(job))


@router.post(
    "/characters", response_model=CharacterRead, status_code=status.HTTP_201_CREATED
)
def create_character(
    payload: CharacterCreate,
    repo: ConfigurationRepository = Depends(configuration_repository),
) -> CharacterRead:
    try:
        character = repo.create_character(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return CharacterRead.model_validate(character_to_dict(character))


@router.get("/characters", response_model=CharacterList)
def list_characters(
    repo: ConfigurationRepository = Depends(configuration_repository),
) -> CharacterList:
    items, total = repo.list_characters()
    return CharacterList(
        items=[CharacterRead.model_validate(character_to_dict(item)) for item in items],
        total=total,
    )


@router.post(
    "/voice-profiles",
    response_model=VoiceProfileRead,
    status_code=status.HTTP_201_CREATED,
)
def create_voice_profile(
    payload: VoiceProfileCreate,
    repo: ConfigurationRepository = Depends(configuration_repository),
) -> VoiceProfileRead:
    profile = repo.create_voice_profile(payload)
    return VoiceProfileRead.model_validate(voice_profile_to_dict(profile))


@router.get("/voice-profiles", response_model=VoiceProfileList)
def list_voice_profiles(
    repo: ConfigurationRepository = Depends(configuration_repository),
) -> VoiceProfileList:
    items, total = repo.list_voice_profiles()
    return VoiceProfileList(
        items=[
            VoiceProfileRead.model_validate(voice_profile_to_dict(item))
            for item in items
        ],
        total=total,
    )


@router.patch("/voice-profiles/{profile_id}", response_model=VoiceProfileRead)
def update_voice_profile(
    profile_id: UUID,
    payload: VoiceProfileUpdate,
    repo: ConfigurationRepository = Depends(configuration_repository),
) -> VoiceProfileRead:
    profile = repo.update_voice_profile(profile_id, payload)
    if profile is None:
        raise HTTPException(status_code=404, detail="Voice profile not found")
    return VoiceProfileRead.model_validate(voice_profile_to_dict(profile))


@router.delete("/voice-profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_voice_profile(
    profile_id: UUID,
    repo: ConfigurationRepository = Depends(configuration_repository),
) -> None:
    try:
        deleted = repo.delete_voice_profile(profile_id)
    except VoiceProfileInUseError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "voice_profile_in_use",
                "message": str(exc),
                "render_profiles": exc.render_profiles,
                "characters": exc.characters,
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Voice profile not found")


@router.post(
    "/voice-profiles/{profile_id}/previews",
    response_model=VoicePreviewRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_voice_preview(
    profile_id: UUID,
    payload: VoicePreviewCreate,
    repo: ConfigurationRepository = Depends(configuration_repository),
) -> VoicePreviewRead:
    profile = repo.get_voice_profile(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Voice profile not found")
    if profile.provider != "elevenlabs":
        raise HTTPException(
            status_code=422, detail="Voice preview requires an ElevenLabs voice profile"
        )
    text = payload.text.strip()
    fingerprint_payload = {
        "voice_profile_id": str(profile.id),
        "voice_updated_at": profile.updated_at.isoformat(),
        "text": text,
        "voice": voice_profile_to_dict(profile),
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    preview, created = repo.create_voice_preview(profile_id, text, fingerprint)
    if created:
        generate_voice_preview.delay(str(preview.id))
    return VoicePreviewRead.model_validate(voice_preview_to_dict(preview))


@router.get("/voice-previews/{preview_id}", response_model=VoicePreviewRead)
def get_voice_preview(
    preview_id: UUID,
    repo: ConfigurationRepository = Depends(configuration_repository),
) -> VoicePreviewRead:
    preview = repo.get_voice_preview(preview_id)
    if preview is None:
        raise HTTPException(status_code=404, detail="Voice preview not found")
    return VoicePreviewRead.model_validate(voice_preview_to_dict(preview))


@router.get("/voice-profiles/{profile_id}/previews", response_model=VoicePreviewList)
def list_voice_previews(
    profile_id: UUID,
    repo: ConfigurationRepository = Depends(configuration_repository),
) -> VoicePreviewList:
    if repo.get_voice_profile(profile_id) is None:
        raise HTTPException(status_code=404, detail="Voice profile not found")
    items, total = repo.list_voice_previews(profile_id)
    return VoicePreviewList(
        items=[
            VoicePreviewRead.model_validate(voice_preview_to_dict(item))
            for item in items
        ],
        total=total,
    )


@router.delete("/voice-previews/{preview_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_voice_preview(
    preview_id: UUID,
    repo: ConfigurationRepository = Depends(configuration_repository),
) -> None:
    preview = repo.get_voice_preview(preview_id)
    if preview is None:
        raise HTTPException(status_code=404, detail="Voice preview not found")
    if preview.status in {"queued", "generating"}:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "voice_preview_in_progress",
                "message": (
                    "Generated speech cannot be deleted while generation is in "
                    "progress."
                ),
            },
        )
    if preview.asset_key:
        try:
            LocalStorageProvider().delete(preview.asset_key)
        except StorageError as exc:
            raise HTTPException(
                status_code=503, detail="Voice preview audio could not be deleted"
            ) from exc
    repo.delete_voice_preview(preview_id)


@router.get("/voice-previews/{preview_id}/audio")
def download_voice_preview(
    preview_id: UUID,
    repo: ConfigurationRepository = Depends(configuration_repository),
) -> Response:
    preview = repo.get_voice_preview(preview_id)
    if preview is None:
        raise HTTPException(status_code=404, detail="Voice preview not found")
    if preview.status != "completed" or not preview.asset_key:
        raise HTTPException(status_code=409, detail="Voice preview audio is not ready")
    try:
        content = LocalStorageProvider().get(preview.asset_key)
    except StorageError as exc:
        raise HTTPException(
            status_code=503, detail="Voice preview audio is unavailable"
        ) from exc
    filename = preview.filename or "voice-preview.mp3"
    return Response(
        content=content,
        media_type=preview.content_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/render-profiles",
    response_model=RenderProfileRead,
    status_code=status.HTTP_201_CREATED,
)
def create_render_profile(
    payload: RenderProfileCreate,
    repo: ConfigurationRepository = Depends(configuration_repository),
) -> RenderProfileRead:
    try:
        profile = repo.create_render_profile(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RenderProfileRead.model_validate(render_profile_to_dict(profile))


@router.post(
    "/render-profiles/setup",
    response_model=RenderProfileRead,
    status_code=status.HTTP_201_CREATED,
)
def create_render_profile_setup(
    payload: RenderProfileSetupCreate,
    repo: ConfigurationRepository = Depends(configuration_repository),
) -> RenderProfileRead:
    try:
        profile = repo.create_render_profile_setup(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RenderProfileRead.model_validate(render_profile_to_dict(profile))


@router.get("/render-profiles", response_model=RenderProfileList)
def list_render_profiles(
    repo: ConfigurationRepository = Depends(configuration_repository),
) -> RenderProfileList:
    items, total = repo.list_render_profiles()
    return RenderProfileList(
        items=[
            RenderProfileRead.model_validate(render_profile_to_dict(item))
            for item in items
        ],
        total=total,
    )


@router.patch("/render-profiles/{profile_id}", response_model=RenderProfileRead)
def update_render_profile(
    profile_id: UUID,
    payload: RenderProfileUpdate,
    repo: ConfigurationRepository = Depends(configuration_repository),
) -> RenderProfileRead:
    try:
        profile = repo.update_render_profile(profile_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if profile is None:
        raise HTTPException(status_code=404, detail="Render profile not found")
    return RenderProfileRead.model_validate(render_profile_to_dict(profile))


@router.delete("/render-profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_render_profile(
    profile_id: UUID,
    repo: ConfigurationRepository = Depends(configuration_repository),
) -> None:
    if not repo.delete_render_profile(profile_id):
        raise HTTPException(status_code=404, detail="Render profile not found")


@router.post(
    "/workflow-templates",
    response_model=WorkflowTemplateRead,
    status_code=status.HTTP_201_CREATED,
)
def create_workflow_template(
    payload: WorkflowTemplateCreate,
    repo: ConfigurationRepository = Depends(configuration_repository),
) -> WorkflowTemplateRead:
    try:
        validate_bindings(
            payload.workflow_json,
            [binding.model_dump() for binding in payload.bindings],
        )
        template = repo.create_workflow_template(
            payload, workflow_checksum(payload.workflow_json)
        )
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return WorkflowTemplateRead.model_validate(workflow_template_to_dict(template))


@router.get("/workflow-templates", response_model=WorkflowTemplateList)
def list_workflow_templates(
    repo: ConfigurationRepository = Depends(configuration_repository),
) -> WorkflowTemplateList:
    items, total = repo.list_workflow_templates()
    return WorkflowTemplateList(
        items=[
            WorkflowTemplateRead.model_validate(workflow_template_to_dict(item))
            for item in items
        ],
        total=total,
    )


@router.get("/workflow-templates/{template_id}", response_model=WorkflowTemplateRead)
def get_workflow_template(
    template_id: UUID,
    repo: ConfigurationRepository = Depends(configuration_repository),
) -> WorkflowTemplateRead:
    template = repo.get_workflow_template(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Workflow template not found")
    return WorkflowTemplateRead.model_validate(workflow_template_to_dict(template))


@router.delete(
    "/workflow-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_workflow_template(
    template_id: UUID,
    repo: ConfigurationRepository = Depends(configuration_repository),
) -> None:
    dependent_count = repo.count_render_profiles_for_workflow(template_id)
    if dependent_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Workflow template is connected to {dependent_count} render profile"
                f"{'s' if dependent_count != 1 else ''}; disconnect it before deleting."
            ),
        )
    try:
        deleted = repo.delete_workflow_template(template_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Workflow template not found")


@router.put(
    "/workflow-templates/{template_id}",
    response_model=WorkflowTemplateRead,
)
def update_workflow_template(
    template_id: UUID,
    payload: WorkflowTemplateCreate,
    repo: ConfigurationRepository = Depends(configuration_repository),
) -> WorkflowTemplateRead:
    try:
        validate_bindings(
            payload.workflow_json,
            [binding.model_dump() for binding in payload.bindings],
        )
        template = repo.update_workflow_template(
            template_id, payload, workflow_checksum(payload.workflow_json)
        )
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if template is None:
        raise HTTPException(status_code=404, detail="Workflow template not found")
    return WorkflowTemplateRead.model_validate(workflow_template_to_dict(template))


@router.post(
    "/workflow-media",
    response_model=WorkflowMediaUploadRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_workflow_media(
    payload: WorkflowMediaUpload,
) -> WorkflowMediaUploadRead:
    filename = PurePath(payload.filename).name
    if not filename or filename in {".", ".."}:
        raise HTTPException(status_code=422, detail="A safe media filename is required")
    try:
        content = base64.b64decode(payload.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=422, detail="Media content is not valid base64"
        ) from exc
    if not content:
        raise HTTPException(status_code=422, detail="Media file cannot be empty")
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(
            status_code=413, detail="Media file must be 25 MB or smaller"
        )
    asset_key = f"workflow-media/{uuid4()}-{filename}"
    try:
        LocalStorageProvider().put(asset_key, content)
    except StorageError as exc:
        raise HTTPException(
            status_code=503, detail="Media storage is unavailable"
        ) from exc
    return WorkflowMediaUploadRead(
        asset_key=asset_key,
        filename=filename,
        input_type=payload.input_type,
    )


@router.get("/dashboard/summary", response_model=DashboardSummary)
def dashboard_summary(
    repo: BatchRepository = Depends(repository),
    config_repo: ConfigurationRepository = Depends(configuration_repository),
) -> DashboardSummary:
    return DashboardSummary(
        in_progress=repo.count_jobs(
            {
                JobStatus.GENERATING_CONTENT,
                JobStatus.GENERATING_TTS,
                JobStatus.FITTING_DURATION,
                JobStatus.SUBMITTING_RENDER,
                JobStatus.RENDERING,
                JobStatus.DOWNLOADING_OUTPUT,
            }
        ),
        ready_to_render=repo.count_jobs({JobStatus.READY_TO_RENDER}),
        completed_videos=repo.count_jobs({JobStatus.COMPLETED}),
        render_profiles=config_repo.count_render_profiles(),
        recent_jobs=[
            JobRead.model_validate(job_to_dict(job)) for job in repo.list_jobs()
        ],
    )
