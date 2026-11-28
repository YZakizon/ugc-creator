import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from kombu.exceptions import OperationalError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import cancel_render_attempt, render_attempt_read
from app.db.base import Base
from app.db.models import (
    Batch,
    Character,
    MediaAsset,
    RenderAttempt,
    RenderProfile,
    TopicJob,
    VoiceProfile,
    WorkflowParameterBinding,
    WorkflowTemplate,
)
from app.providers.render.comfyui import (
    ComfyUIProviderError,
    ComfyUISubmissionOutcomeUnknown,
)
from app.providers.render.contracts import RenderOutput, RenderStatus
from app.render_repository import RenderExecutionRepository
from app.schemas import (
    CreatedVideoRenderRequest,
    OnDemandRenderOverrides,
    RenderNodeCreate,
)
from app.services.media_service import MediaProcessingError
from app.workers.render_tasks import (
    _monitor,
    _prepare_and_submit,
    apply_default_workflow_media,
    dispatch_recoverable_created_video_heads,
    render_has_timed_out,
    render_input_filename,
    select_video_output,
    submit_render,
)


@pytest.mark.asyncio
async def test_monitor_persists_live_comfyui_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt_id = uuid4()
    attempt = SimpleNamespace(
        id=attempt_id,
        status="rendering",
        progress=12,
        external_job_id="prompt-live",
        submitted_at=datetime.now(UTC),
        client_id="attempt-client",
    )
    updates: list[tuple[object, str, int]] = []
    scheduled: list[tuple[list[str], int]] = []

    class FakeRepository:
        def execution_context(self, _attempt_id: object) -> tuple[object, ...]:
            return (
                attempt,
                SimpleNamespace(),
                SimpleNamespace(),
                SimpleNamespace(base_url="http://comfyui"),
                SimpleNamespace(),
            )

        def update_progress(
            self, stored_attempt_id: object, status: str, progress: int
        ) -> None:
            updates.append((stored_attempt_id, status, progress))

    class FakeRenderer:
        def __init__(self, **_values: object) -> None:
            pass

        async def get_status(self, external_job_id: str) -> RenderStatus:
            return RenderStatus(external_job_id=external_job_id, state="running")

        async def get_live_progress(self, _external_job_id: str) -> float:
            return 47.8

    monkeypatch.setattr("app.workers.render_tasks.repository", FakeRepository)
    monkeypatch.setattr("app.workers.render_tasks.ComfyUIRenderer", FakeRenderer)
    monkeypatch.setattr(
        "app.workers.render_tasks.monitor_render.apply_async",
        lambda *, args, countdown: scheduled.append((args, countdown)),
    )

    assert await _monitor(attempt_id) == "rendering"
    assert updates == [(attempt_id, "rendering", 47)]
    assert scheduled == [([str(attempt_id)], 5)]


def test_unknown_submission_outcome_stays_reconcilable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt_id = uuid4()
    scheduled: list[tuple[list[str], int]] = []

    async def ambiguous_submission(_attempt_id: object) -> None:
        raise ComfyUISubmissionOutcomeUnknown("ComfyUI submission outcome is unknown")

    class FailIfMarkedFailed:
        def update_progress(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("An ambiguous submission must not be marked failed")

    monkeypatch.setattr(
        "app.workers.render_tasks._prepare_and_submit", ambiguous_submission
    )
    monkeypatch.setattr("app.workers.render_tasks.repository", FailIfMarkedFailed)
    monkeypatch.setattr(
        "app.workers.render_tasks.submit_render.apply_async",
        lambda *, args, countdown: scheduled.append((args, countdown)),
    )

    result = submit_render(str(attempt_id))

    assert result == {"attempt_id": str(attempt_id), "status": "reconciling"}
    assert scheduled == [([str(attempt_id)], 5)]


def test_media_processing_failure_persists_safe_render_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt_id = uuid4()
    updates: list[tuple[object, str, int, str]] = []

    async def fail_to_measure(_attempt_id: object) -> None:
        raise MediaProcessingError("Audio duration could not be measured.")

    class FakeRepository:
        def update_progress(
            self,
            stored_attempt_id: object,
            status: str,
            progress: int,
            message: str,
        ) -> None:
            updates.append((stored_attempt_id, status, progress, message))

    monkeypatch.setattr("app.workers.render_tasks._prepare_and_submit", fail_to_measure)
    monkeypatch.setattr("app.workers.render_tasks.repository", FakeRepository)

    result = submit_render(str(attempt_id))

    assert result == {"attempt_id": str(attempt_id), "status": "failed"}
    assert updates == [
        (attempt_id, "failed", 0, "Audio duration could not be measured.")
    ]


@pytest.mark.asyncio
async def test_claim_expiring_during_preparation_schedules_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt_id = uuid4()
    attempt = SimpleNamespace(
        external_job_id=None,
        status="queued",
        client_id="durable-client",
        effective_values={},
        workflow_snapshot={"1": {"class_type": "Text", "inputs": {}}},
        binding_snapshot=[],
    )
    job = SimpleNamespace(
        speech_script="Prepared script",
        topic="Prepared topic",
        hook=None,
        target_duration_seconds=30,
        media_assets=[],
        render_overrides={},
    )
    profile = SimpleNamespace(
        default_parameters={},
        prompt_template=None,
        character=SimpleNamespace(name="Elena"),
    )
    node = SimpleNamespace(base_url="http://comfyui")
    template = SimpleNamespace(metadata_json={})
    scheduled: list[tuple[list[str], int]] = []

    class FakeRepository:
        def get_attempt(self, _attempt_id: object) -> object:
            return attempt

        def claim_submission(self, _attempt_id: object) -> tuple[bool, int]:
            return True, 0

        def execution_context(self, _attempt_id: object) -> tuple[object, ...]:
            return attempt, job, profile, node, template

        def save_prepared(self, *_args: object) -> None:
            pass

        def mark_submission_started(self, _attempt_id: object) -> bool:
            return False

    class FakeRenderer:
        def __init__(self, **_values: object) -> None:
            pass

        async def submit(self, _request: object) -> object:
            raise AssertionError("An expired claim must not submit")

    monkeypatch.setattr("app.workers.render_tasks.repository", FakeRepository)
    monkeypatch.setattr("app.workers.render_tasks.ComfyUIRenderer", FakeRenderer)
    monkeypatch.setattr(
        "app.workers.render_tasks.submit_render.apply_async",
        lambda *, args, countdown: scheduled.append((args, countdown)),
    )

    await _prepare_and_submit(attempt_id)

    assert scheduled == [([str(attempt_id)], 1)]


@pytest.mark.asyncio
async def test_redelivered_active_submission_schedules_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt_id = uuid4()
    attempt = SimpleNamespace(
        external_job_id=None,
        status="submitting_render",
        submission_claim_expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    scheduled: list[int] = []

    class FakeRepository:
        def get_attempt(self, _attempt_id: object) -> object:
            return attempt

    monkeypatch.setattr("app.workers.render_tasks.repository", FakeRepository)
    monkeypatch.setattr(
        "app.workers.render_tasks.submit_render.apply_async",
        lambda *, args, countdown: scheduled.append(countdown),
    )

    await _prepare_and_submit(attempt_id)

    assert len(scheduled) == 1
    assert 1 <= scheduled[0] <= 300


@pytest.mark.asyncio
async def test_uncertain_comfyui_submission_is_not_resubmitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt_id = uuid4()
    updates: list[tuple[str, str | None]] = []
    attempt = SimpleNamespace(
        id=attempt_id,
        external_job_id=None,
        client_id="persisted-client",
        status="submitting_render",
        submission_claim_expires_at=datetime.now(UTC) - timedelta(seconds=1),
        submission_started_at=datetime.now(UTC) - timedelta(minutes=5),
        progress=0,
    )

    class FakeRepository:
        def get_attempt(self, _attempt_id: object) -> object:
            return attempt

        def execution_context(self, _attempt_id: object) -> tuple[object, ...]:
            return (
                attempt,
                object(),
                object(),
                SimpleNamespace(base_url="http://comfyui"),
                object(),
            )

        def update_progress(
            self,
            _attempt_id: object,
            status: str,
            _progress: int,
            error: str | None = None,
        ) -> bool:
            updates.append((status, error))
            return True

    class FakeRenderer:
        def __init__(self, **_values: object) -> None:
            pass

        async def find_submission(self, _client_id: str) -> None:
            return None

        async def submit(self, _request: object) -> object:
            raise AssertionError("An unknown submission must not be resubmitted")

    monkeypatch.setattr("app.workers.render_tasks.repository", FakeRepository)
    monkeypatch.setattr("app.workers.render_tasks.ComfyUIRenderer", FakeRenderer)

    await _prepare_and_submit(attempt_id)

    assert updates[0][0] == "failed"
    assert updates[0][1] is not None
    assert "not resubmitted automatically" in updates[0][1]


@pytest.mark.asyncio
async def test_render_uses_selected_create_video_audio_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt_id = uuid4()
    saved_values: dict[str, object] = {}
    uploaded: list[tuple[str, bytes, str]] = []
    scheduled: list[tuple[list[str], int]] = []
    attempt = SimpleNamespace(
        id=attempt_id,
        external_job_id=None,
        client_id="client-selected-audio",
        status="queued",
        workflow_snapshot={
            "bound-audio": {
                "class_type": "LoadAudio",
                "inputs": {"audio": "workflow-bound-default.mp3"},
            },
            "downstream-audio": {
                "class_type": "LoadAudio",
                "inputs": {"audio": "workflow-actual-default.mp3"},
            },
            "1": {"class_type": "Text", "inputs": {"text": "ready"}},
        },
        binding_snapshot=[
            {
                "semantic_key": "audio",
                "node_id": "bound-audio",
                "input_name": "audio",
                "value_type": "string",
                "required": True,
            }
        ],
    )
    old_audio = SimpleNamespace(
        id=uuid4(),
        kind="audio",
        object_key="audio/old-profile-default.mp3",
        filename="old-profile-default.mp3",
        created_at=datetime(2026, 8, 10, 10, tzinfo=UTC),
        updated_at=datetime(2026, 8, 10, 10, tzinfo=UTC),
    )
    selected_audio = SimpleNamespace(
        id=uuid4(),
        kind="audio",
        object_key="audio/selected-create-video.mp3",
        filename="selected-create-video.mp3",
        created_at=datetime(2026, 8, 10, 12, tzinfo=UTC),
        updated_at=datetime(2026, 8, 10, 12, tzinfo=UTC),
    )
    attempt.effective_values = {
        "requested_inputs": {
            "values": {"script": "Captured script", "duration": 12},
            "audio": {
                "object_key": selected_audio.object_key,
                "filename": selected_audio.filename,
            },
            "source_image": {},
            "workflow_metadata": {},
        }
    }
    job = SimpleNamespace(
        speech_script="Selected script",
        topic="Selected topic",
        hook=None,
        target_duration_seconds=30,
        render_overrides={},
        media_assets=[old_audio],
    )
    profile = SimpleNamespace(
        default_parameters={"audio": "profile-default.mp3"},
        prompt_template=None,
        character=SimpleNamespace(name="Elena"),
    )

    class FakeRepository:
        def get_attempt(self, _attempt_id: object) -> object:
            return attempt

        def claim_submission(self, _attempt_id: object) -> tuple[bool, int]:
            return True, 0

        def execution_context(self, _attempt_id: object) -> tuple[object, ...]:
            return (
                attempt,
                job,
                profile,
                SimpleNamespace(base_url="http://comfyui"),
                SimpleNamespace(metadata_json={}),
            )

        def save_prepared(
            self,
            _attempt_id: object,
            workflow: dict[str, object],
            values: dict[str, object],
        ) -> None:
            saved_values.update(values)
            saved_values["prepared_workflow"] = workflow

        def mark_submission_started(self, _attempt_id: object) -> bool:
            return True

        def save_submission(
            self,
            _attempt_id: object,
            _external_job_id: str,
            _client_id: str,
        ) -> bool:
            return True

    class FakeRenderer:
        def __init__(self, **_values: object) -> None:
            pass

        async def upload(self, filename: str, content: bytes, input_type: str) -> str:
            uploaded.append((filename, content, input_type))
            return f"uploaded-{filename}"

        async def submit(self, request: object) -> object:
            return SimpleNamespace(
                external_job_id="prompt-selected-audio",
                client_id=request.client_id,
            )

    class FakeStorage:
        def get(self, object_key: str) -> bytes:
            return object_key.encode()

    monkeypatch.setattr("app.workers.render_tasks.repository", FakeRepository)
    monkeypatch.setattr("app.workers.render_tasks.ComfyUIRenderer", FakeRenderer)
    monkeypatch.setattr("app.workers.render_tasks.LocalStorageProvider", FakeStorage)
    monkeypatch.setattr(
        "app.workers.render_tasks.monitor_render.apply_async",
        lambda *, args, countdown: scheduled.append((args, countdown)),
    )

    await _prepare_and_submit(attempt_id)
    assert saved_values["script"] == "Captured script"
    assert saved_values["duration"] == 12

    assert uploaded == [
        (
            f"{attempt_id}-selected-create-video.mp3",
            b"audio/selected-create-video.mp3",
            "audio",
        )
    ]
    assert saved_values["audio"] == f"uploaded-{attempt_id}-selected-create-video.mp3"
    prepared_workflow = saved_values["prepared_workflow"]
    assert isinstance(prepared_workflow, dict)
    assert (
        prepared_workflow["bound-audio"]["inputs"]["audio"] == saved_values["audio"]  # type: ignore[index]
    )
    assert (
        prepared_workflow["downstream-audio"]["inputs"]["audio"]
        == saved_values["audio"]  # type: ignore[index]
    )
    assert scheduled == [([str(attempt_id)], 3)]


@pytest.mark.asyncio
async def test_batch_media_overrides_workflow_defaults() -> None:
    values: dict[str, object] = {
        "source_image": "batch-image.png",
        "audio": "batch-audio.mp3",
    }
    renderer = AsyncMock()
    storage = Mock()

    await apply_default_workflow_media(
        values,
        {
            "default_workflow_media": {
                "source_image": "workflow-media/default.png",
                "audio": "workflow-media/default.mp3",
            }
        },
        renderer,
        storage,
    )

    assert values == {
        "source_image": "batch-image.png",
        "audio": "batch-audio.mp3",
    }
    storage.get.assert_not_called()
    renderer.upload.assert_not_awaited()


@pytest.mark.asyncio
async def test_workflow_media_is_used_only_as_a_missing_value_fallback() -> None:
    values: dict[str, object] = {"source_image": "batch-image.png"}
    renderer = AsyncMock()
    renderer.upload.return_value = "comfy-default.mp3"
    storage = Mock()
    storage.get.return_value = b"audio"

    await apply_default_workflow_media(
        values,
        {
            "default_workflow_media": {
                "source_image": "workflow-media/default.png",
                "audio": "workflow-media/default.mp3",
            }
        },
        renderer,
        storage,
        upload_namespace="attempt-2",
    )

    assert values["source_image"] == "batch-image.png"
    assert values["audio"] == "comfy-default.mp3"
    storage.get.assert_called_once_with("workflow-media/default.mp3")
    renderer.upload.assert_awaited_once_with("attempt-2-default.mp3", b"audio", "audio")


def test_each_render_uses_a_distinct_comfyui_input_filename() -> None:
    first = render_input_filename("topic_content1_0001.mp3", uuid4())
    second = render_input_filename("topic_content1_0001.mp3", uuid4())

    assert first != second
    assert first.endswith("-topic_content1_0001.mp3")
    assert second.endswith("-topic_content1_0001.mp3")


@pytest.mark.asyncio
async def test_default_audio_duration_is_measured_when_workflow_uses_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values: dict[str, object] = {}
    renderer = AsyncMock()
    renderer.upload.return_value = "comfy-default.mp3"
    storage = Mock()
    storage.get.return_value = b"audio"
    probe = Mock(return_value=4.5)
    monkeypatch.setattr("app.workers.render_tasks.probe_audio_duration", probe)

    await apply_default_workflow_media(
        values,
        {"default_workflow_media": {"audio": "workflow-media/default.mp3"}},
        renderer,
        storage,
        measure_audio_duration=True,
    )

    assert values["audio_duration"] == 4.5
    probe.assert_called_once_with(b"audio", "default.mp3")


def test_render_monitor_timeout_is_bounded() -> None:
    checked_at = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)

    assert render_has_timed_out(
        checked_at - timedelta(seconds=3600),
        3600,
        current_time=checked_at,
    )
    assert not render_has_timed_out(
        checked_at - timedelta(seconds=3599),
        3600,
        current_time=checked_at,
    )


def test_render_attempt_queue_is_idempotent_and_completion_persists_asset() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        voice = VoiceProfile(
            name="Voice", provider="elevenlabs", provider_voice_id="voice"
        )
        character = Character(name="Elena", slug="elena", default_voice_profile=voice)
        workflow = WorkflowTemplate(
            name="LTX",
            renderer_provider="comfyui",
            workflow_json={
                "1": {"class_type": "Text", "inputs": {"text": "{{SCRIPT}}"}}
            },
            checksum="checksum",
        )
        profile = RenderProfile(
            name="Elena LTX",
            character=character,
            voice_profile=voice,
            renderer_provider="comfyui",
            workflow_template_id=None,
        )
        session.add_all([workflow, profile])
        session.flush()
        profile.workflow_template_id = workflow.id
        batch = Batch(name="Batch")
        job = TopicJob(batch=batch, topic="Topic", render_profile_id=profile.id)
        job.media_assets = [
            MediaAsset(
                kind="audio",
                object_key="jobs/topic/audio.mp3",
                filename="audio.mp3",
                content_type="audio/mpeg",
                size_bytes=5,
            )
        ]
        session.add(job)
        session.commit()
        job_id = job.id

    repo = RenderExecutionRepository(factory)
    node = repo.create_node(
        RenderNodeCreate(name="Local", base_url="http://comfyui:8188")
    )
    first = repo.queue_attempt(job_id, node.id)
    second = repo.queue_attempt(job_id, node.id)
    assert first.id == second.id

    repo.save_prepared(
        first.id,
        {"1": {"class_type": "Text", "inputs": {"text": "Topic"}}},
        {"script": "Topic"},
    )
    repo.save_submission(first.id, "prompt-1", "client-1")
    assert repo.claim_finalization(first.id) == (True, 0)
    duplicate_claim, retry_after = repo.claim_finalization(first.id)
    assert duplicate_claim is False
    assert retry_after > 0
    assert not repo.update_progress(first.id, "rendering", 50)
    assert repo.complete(first.id, "jobs/video.mp4", "video.mp4", "video/mp4", 12)
    assert not repo.complete(
        first.id, "jobs/duplicate.mp4", "duplicate.mp4", "video/mp4", 12
    )
    assert not repo.update_progress(first.id, "failed", 0, "late monitor failure")
    completed = repo.get_attempt(first.id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.external_job_id == "prompt-1"
    assert completed.error_message is None
    assert render_attempt_read(completed).effective_values == {"script": "Topic"}
    assert len(completed.assets) == 1
    assert completed.assets[0].object_key == "jobs/video.mp4"
    rerender = repo.queue_attempt(job_id, node.id)
    assert rerender.id != first.id
    assert repo.delete_video_asset(completed.assets[0].id)
    with factory() as session:
        active_job = session.get(TopicJob, job_id)
        assert active_job is not None
        assert active_job.status == "queued"
    assert repo.update_progress(rerender.id, "failed", 0, "Stopped")
    deleted_attempt = repo.get_attempt(first.id)
    assert deleted_attempt is not None
    assert deleted_attempt.assets == []
    assert deleted_attempt.output_filename == "video.mp4"
    assert deleted_attempt.output_deleted_at is not None
    with factory() as session:
        reset_job = session.get(TopicJob, job_id)
        assert reset_job is not None
        assert reset_job.status == "failed"


def test_created_video_queue_captures_inputs_and_allows_removing_waiting_renders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    repo = RenderExecutionRepository(factory)
    node = repo.create_node(
        RenderNodeCreate(name="Local", base_url="http://comfyui:8188")
    )
    with factory() as session:
        workflow = WorkflowTemplate(
            name="LTX",
            renderer_provider="comfyui",
            workflow_json={"1": {"class_type": "Text", "inputs": {}}},
            checksum="original",
            metadata_json={"revision": 1},
        )
        profile = RenderProfile(
            name="LTX",
            character=Character(name="Elena", slug="elena"),
            voice_profile=VoiceProfile(
                name="Voice", provider="elevenlabs", provider_voice_id="voice"
            ),
            renderer_provider="comfyui",
            default_parameters={"fps": 24},
        )
        job = TopicJob(
            batch=Batch(name="Created video", creation_mode="created_video"),
            topic="Saved draft",
            media_assets=[
                MediaAsset(
                    kind=kind, object_key=filename, filename=filename, size_bytes=1
                )
                for kind, filename in [
                    ("source_image", "image.png"),
                    ("audio", "first.mp3"),
                    ("audio_archive", "second.mp3"),
                ]
            ],
        )
        session.add_all([job, profile, workflow])
        session.commit()
        image, first_audio, second_audio = job.media_assets
        request = CreatedVideoRenderRequest(
            title="First title",
            render_profile_id=profile.id,
            workflow_template_id=workflow.id,
            speech_script="First script",
            audio_asset_id=first_audio.id,
            source_image_asset_id=image.id,
            render_overrides=OnDemandRenderOverrides(
                video_prompt="First prompt", seed=1
            ),
        )

    first = repo.queue_attempt(job.id, node.id, request)
    request.audio_asset_id = second_audio.id
    request.render_overrides.seed = 2
    request.render_overrides.video_prompt = "Second prompt"
    second = repo.queue_attempt(job.id, node.id, request)
    third = repo.queue_attempt(job.id, node.id, request)
    assert len({first.id, second.id, third.id}) == 3
    assert repo.claim_submission(second.id) == (False, 5)

    # The first request committed without publishing. A fresh process can
    # rediscover the head from the database, even if no later request arrives.
    restarted_repo = RenderExecutionRepository(factory)
    deliveries: list[str] = []
    monkeypatch.setattr(
        "app.workers.render_tasks.submit_render.apply_async",
        lambda *, args, retry: deliveries.extend(args),
    )
    dispatch_recoverable_created_video_heads(restarted_repo)
    dispatch_recoverable_created_video_heads(restarted_repo)
    assert deliveries == [str(first.id), str(first.id)]
    assert restarted_repo.claim_submission(first.id) == (True, 0)
    assert not restarted_repo.claim_submission(first.id)[0]
    dispatch_recoverable_created_video_heads(restarted_repo)
    assert deliveries == [str(first.id), str(first.id)]
    with pytest.raises(ValueError, match="already left the queue"):
        repo.cancel_attempt(first.id, queued_only=True)
    removed = repo.cancel_attempt(second.id, queued_only=True)
    assert removed is not None and removed.status == "cancelled"
    assert repo.claim_submission(second.id) == (False, 0)
    assert repo.claim_submission(third.id) == (False, 5)

    prepared = repo.save_prepared(first.id, {}, {"rendered": True})
    first_inputs = prepared.effective_values["requested_inputs"]
    assert isinstance(first_inputs, dict)
    assert first_inputs["values"]["script"] == "First script"
    assert first_inputs["values"]["video_prompt"] == "First prompt"
    assert first_inputs["values"]["seed"] == 1
    assert first_inputs["audio"]["filename"] == "first.mp3"
    assert first_inputs["workflow_metadata"] == {"revision": 1}
    assert first_inputs["workflow_checksum"] == "original"
    loaded = repo.get_attempt(first.id)
    assert loaded is not None
    public_inputs = render_attempt_read(loaded).effective_values["requested_inputs"]
    assert isinstance(public_inputs, dict)
    assert "object_key" not in public_inputs["audio"]
    assert "object_key" in first_inputs["audio"]

    second_inputs = removed.effective_values["requested_inputs"]
    assert isinstance(second_inputs, dict)
    assert second_inputs["values"]["seed"] == 2
    assert second_inputs["audio"]["filename"] == "second.mp3"
    assert repo.update_progress(first.id, "failed", 0, "Failed")
    with factory() as session:
        current = session.get(TopicJob, job.id)
        assert current is not None and current.status == "queued"
    dispatch_recoverable_created_video_heads(restarted_repo)
    assert deliveries == [str(first.id), str(first.id), str(third.id)]
    fourth = repo.queue_attempt(job.id, node.id, request)
    provider_submit = AsyncMock(
        return_value=SimpleNamespace(external_job_id="saved-prompt", client_id=None)
    )
    provider_status = AsyncMock(
        return_value=RenderStatus(
            external_job_id="saved-prompt",
            state="failed",
            message="Provider reported failure",
        )
    )
    renderer = SimpleNamespace(
        upload=AsyncMock(return_value="uploaded"),
        submit=provider_submit,
        get_status=provider_status,
    )
    monkeypatch.setattr("app.workers.render_tasks.repository", lambda: restarted_repo)
    monkeypatch.setattr(
        "app.workers.render_tasks.ComfyUIRenderer", lambda **_: renderer
    )
    monkeypatch.setattr(
        "app.workers.render_tasks.LocalStorageProvider",
        lambda: SimpleNamespace(get=lambda _: b"media"),
    )
    publish_monitor = Mock(side_effect=OperationalError("Redis unavailable"))
    monkeypatch.setattr(
        "app.workers.render_tasks.monitor_render.apply_async", publish_monitor
    )

    with pytest.raises(OperationalError, match="Redis unavailable"):
        asyncio.run(_prepare_and_submit(third.id))
    saved = repo.get_attempt(third.id)
    assert saved is not None and saved.external_job_id == "saved-prompt"
    assert repo.claim_submission(fourth.id) == (False, 5)

    publish_monitor.reset_mock(side_effect=True)
    dispatch_recoverable_created_video_heads(restarted_repo)
    publish_monitor.assert_not_called()
    with factory() as session:
        stale = session.get(RenderAttempt, third.id)
        assert stale is not None
        stale.updated_at = datetime.now(UTC) - timedelta(seconds=31)
        session.commit()

    dispatch_recoverable_created_video_heads(restarted_repo)
    publish_monitor.assert_called_once_with(args=[str(third.id)], retry=False)
    assert deliveries == [str(first.id), str(first.id), str(third.id)]
    assert asyncio.run(_monitor(third.id)) == "failed"
    provider_status.assert_awaited_once_with("saved-prompt")
    provider_submit.assert_awaited_once()
    fifth = repo.queue_attempt(job.id, node.id, request)
    provider_submit.reset_mock()
    provider_submit.side_effect = ComfyUISubmissionOutcomeUnknown("Response lost")
    find_submission = AsyncMock(return_value="saved-prompt")
    renderer.find_submission = find_submission
    publish_submission = Mock(side_effect=OperationalError("Redis unavailable"))
    monkeypatch.setattr(
        "app.workers.render_tasks.submit_render.apply_async", publish_submission
    )

    with pytest.raises(OperationalError, match="Redis unavailable"):
        submit_render.run(str(fourth.id))
    publish_submission.assert_called_once_with(args=[str(fourth.id)], countdown=5)
    unresolved = repo.get_attempt(fourth.id)
    assert unresolved is not None and unresolved.external_job_id is None
    assert unresolved.status == "submitting_render"
    assert unresolved.submission_started_at is not None
    assert repo.claim_submission(fifth.id) == (False, 5)
    publish_submission.reset_mock(side_effect=True)
    dispatch_recoverable_created_video_heads(restarted_repo)
    publish_submission.assert_not_called()

    with factory() as session:
        expired = session.get(RenderAttempt, fourth.id)
        assert expired is not None
        expired.submission_claim_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()

    dispatch_recoverable_created_video_heads(restarted_repo)
    publish_submission.assert_called_once_with(args=[str(fourth.id)], retry=False)
    assert submit_render.run(str(fourth.id))["status"] == "submitted"
    find_submission.assert_awaited_once_with(unresolved.client_id)
    assert asyncio.run(_monitor(fourth.id)) == "failed"
    provider_submit.assert_awaited_once()
    assert repo.claim_submission(fifth.id) == (True, 0)


def test_failed_attempt_deletion_is_scoped_to_the_selected_created_video() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    repo = RenderExecutionRepository(factory)
    node = repo.create_node(
        RenderNodeCreate(name="Local", base_url="http://comfyui:8188")
    )

    with factory() as session:
        voice = VoiceProfile(
            name="Voice", provider="elevenlabs", provider_voice_id="voice"
        )
        workflow = WorkflowTemplate(
            name="LTX",
            renderer_provider="comfyui",
            workflow_json={},
            checksum="checksum",
        )
        profile = RenderProfile(
            name="LTX",
            character=Character(name="Elena", slug="elena"),
            voice_profile=voice,
            renderer_provider="comfyui",
        )
        selected = TopicJob(
            batch=Batch(name="Selected video", creation_mode="created_video"),
            topic="Selected video",
        )
        other = TopicJob(
            batch=Batch(name="Other video", creation_mode="created_video"),
            topic="Other video",
        )
        ordinary = TopicJob(batch=Batch(name="Ordinary topic"), topic="Ordinary topic")
        session.add_all([workflow, profile, selected, other, ordinary])
        session.flush()

        def attempt(job: TopicJob, status: str) -> RenderAttempt:
            return RenderAttempt(
                job_id=job.id,
                render_profile_id=profile.id,
                render_node_id=node.id,
                workflow_template_id=workflow.id,
                provider="comfyui",
                status=status,
                error_message="Provider failed" if status == "failed" else None,
            )

        first = attempt(selected, "failed")
        second = attempt(selected, "failed")
        completed = attempt(selected, "completed")
        active = attempt(selected, "rendering")
        other_failed = attempt(other, "failed")
        ordinary_failed = attempt(ordinary, "failed")
        session.add_all(
            [first, second, completed, active, other_failed, ordinary_failed]
        )
        session.commit()

    def deleted_ids() -> set[UUID]:
        return {
            entry.id
            for entry in repo.list_attempts()
            if entry.output_deleted_at is not None
        }

    repo.delete_failed_attempts(selected.id, completed.id)
    repo.delete_failed_attempts(selected.id, other_failed.id)
    repo.delete_failed_attempts(ordinary.id, None)
    assert deleted_ids() == set()

    repo.delete_failed_attempts(selected.id, first.id)
    assert deleted_ids() == {first.id}
    repo.delete_failed_attempts(selected.id, None)
    assert deleted_ids() == {first.id, second.id}

    for attempt_id in (first.id, second.id):
        entry = repo.get_attempt(attempt_id)
        assert entry is not None
        assert entry.status == "failed"
        assert entry.error_message == "Provider failed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage", ["local", "submitting", "discovered", "submitted", "provider_error"]
)
async def test_cancel_render_attempt_returns_job_to_ready_to_render(
    stage: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        voice = VoiceProfile(
            name="Voice", provider="elevenlabs", provider_voice_id="voice"
        )
        character = Character(
            name="Elena", slug="cancel-elena", default_voice_profile=voice
        )
        workflow = WorkflowTemplate(
            name="LTX",
            renderer_provider="comfyui",
            workflow_json={
                "1": {"class_type": "Text", "inputs": {"text": "{{SCRIPT}}"}}
            },
            checksum="cancel-checksum",
        )
        profile = RenderProfile(
            name="Elena LTX",
            character=character,
            voice_profile=voice,
            renderer_provider="comfyui",
        )
        session.add_all([workflow, profile])
        session.flush()
        profile.workflow_template_id = workflow.id
        batch = Batch(name="Batch")
        job = TopicJob(batch=batch, topic="Topic", render_profile_id=profile.id)
        job.media_assets = [
            MediaAsset(
                kind="audio",
                object_key="jobs/topic/audio.mp3",
                filename="audio.mp3",
                content_type="audio/mpeg",
                size_bytes=5,
            )
        ]
        session.add(job)
        session.commit()
        job_id = job.id

    repo = RenderExecutionRepository(factory)
    node = repo.create_node(
        RenderNodeCreate(name="Local", base_url="http://comfyui:8188")
    )
    attempt = repo.queue_attempt(job_id, node.id)
    assert repo.claim_submission(attempt.id) == (True, 0)
    repo.save_prepared(
        attempt.id,
        {"1": {"class_type": "Text", "inputs": {"text": "Topic"}}},
        {"script": "Topic"},
    )
    if stage != "local":
        assert repo.mark_submission_started(attempt.id)
    if stage in {"submitted", "provider_error"}:
        assert repo.save_submission(attempt.id, "prompt-id", attempt.client_id)
    upstream = AsyncMock()
    upstream.find_submission.return_value = (
        "prompt-id" if stage == "discovered" else None
    )
    if stage == "provider_error":
        upstream.cancel.side_effect = ComfyUIProviderError("unavailable")
    monkeypatch.setattr("app.api.routes.ComfyUIRenderer", lambda **_: upstream)

    if stage in {"submitting", "provider_error"}:
        with pytest.raises(HTTPException) as exc:
            await cancel_render_attempt(attempt.id, repo=repo)
        assert exc.value.status_code == (409 if stage == "submitting" else 503)
        persisted = repo.get_attempt(attempt.id)
        assert persisted is not None
        assert persisted.status == (
            "submitting_render" if stage == "submitting" else "rendering"
        )
        return

    cancelled = await cancel_render_attempt(attempt.id, repo=repo)
    if stage == "local":
        upstream.cancel.assert_not_awaited()
    else:
        upstream.cancel.assert_awaited_once_with("prompt-id")
    if stage == "discovered":
        upstream.find_submission.assert_awaited_once_with(attempt.client_id)
        assert cancelled.external_job_id == "prompt-id"
    assert cancelled is not None
    assert cancelled.status == "cancelled"
    assert cancelled.error_message == "Render cancelled."
    with factory() as session:
        loaded_job = session.get(TopicJob, job_id)
        assert loaded_job is not None
        assert loaded_job.status == "ready_to_render"
        assert loaded_job.error_message is None


def test_job_workflow_override_is_snapshotted_for_render() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        voice = VoiceProfile(
            name="Voice", provider="elevenlabs", provider_voice_id="voice"
        )
        character = Character(name="Elena", slug="workflow-override")
        default_workflow = WorkflowTemplate(
            name="Default",
            renderer_provider="comfyui",
            workflow_json={"1": {"class_type": "Text", "inputs": {"text": "default"}}},
            checksum="default",
        )
        override_workflow = WorkflowTemplate(
            name="Override",
            renderer_provider="comfyui",
            workflow_json={"2": {"class_type": "Text", "inputs": {"text": "override"}}},
            checksum="override",
        )
        session.add_all([voice, character, default_workflow, override_workflow])
        session.flush()
        profile = RenderProfile(
            name="Profile",
            character_id=character.id,
            voice_profile_id=voice.id,
            renderer_provider="comfyui",
            workflow_template_id=default_workflow.id,
        )
        batch = Batch(name="Batch")
        session.add_all([profile, batch])
        session.flush()
        job = TopicJob(
            batch_id=batch.id,
            topic="Topic",
            render_profile_id=profile.id,
            workflow_template_id=override_workflow.id,
        )
        job.media_assets = [
            MediaAsset(
                kind="audio",
                object_key="audio.mp3",
                filename="audio.mp3",
                content_type="audio/mpeg",
                size_bytes=5,
            )
        ]
        session.add(job)
        session.commit()
        job_id = job.id
        override_id = override_workflow.id

    repo = RenderExecutionRepository(factory)
    node = repo.create_node(
        RenderNodeCreate(name="Local", base_url="http://comfyui:8188")
    )
    attempt = repo.queue_attempt(job_id, node.id)

    assert attempt.workflow_template_id == override_id
    assert attempt.workflow_snapshot == {
        "2": {"class_type": "Text", "inputs": {"text": "override"}}
    }


def test_render_submission_claim_allows_only_one_concurrent_worker(tmp_path) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'render-claim.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        voice = VoiceProfile(
            name="Voice", provider="elevenlabs", provider_voice_id="voice"
        )
        character = Character(
            name="Elena", slug="claim-elena", default_voice_profile=voice
        )
        workflow = WorkflowTemplate(
            name="Claim workflow",
            renderer_provider="comfyui",
            workflow_json={"1": {"class_type": "Text", "inputs": {"text": "x"}}},
            checksum="claim-checksum",
        )
        profile = RenderProfile(
            name="Claim profile",
            character=character,
            voice_profile=voice,
            renderer_provider="comfyui",
        )
        session.add_all([workflow, profile])
        session.flush()
        profile.workflow_template_id = workflow.id
        batch = Batch(name="Claim batch")
        job = TopicJob(batch=batch, topic="Claim topic", render_profile_id=profile.id)
        job.media_assets = [
            MediaAsset(
                kind="audio",
                object_key="jobs/claim/audio.mp3",
                filename="audio.mp3",
                content_type="audio/mpeg",
                size_bytes=5,
            )
        ]
        session.add(job)
        session.commit()
        job_id = job.id

    repository = RenderExecutionRepository(factory)
    node = repository.create_node(
        RenderNodeCreate(name="Claim node", base_url="http://comfyui:8188")
    )
    attempt = repository.queue_attempt(job_id, node.id)
    barrier = Barrier(2)

    def claim() -> bool:
        barrier.wait()
        return repository.claim_submission(attempt.id)[0]

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(lambda _index: claim(), range(2)))

    assert sorted(claims) == [False, True]
    assert repository.mark_submission_started(attempt.id)
    assert not repository.mark_submission_started(attempt.id)

    with factory() as session:
        stored = session.get(type(attempt), attempt.id)
        assert stored is not None
        stored.status = "submitting_render"
        stored.submission_claim_expires_at = None
        stored.updated_at = datetime.now(UTC) - timedelta(minutes=6)
        session.commit()

    assert repository.claim_submission(attempt.id) == (False, 300)


def test_video_output_selection_skips_preview_images() -> None:
    selected = select_video_output(
        [
            RenderOutput(filename="preview.png", media_type="image"),
            RenderOutput(filename="final.mp4", media_type="video"),
        ]
    )

    assert selected.filename == "final.mp4"


def test_video_output_selection_rejects_image_only_results() -> None:
    with pytest.raises(ComfyUIProviderError, match="video or GIF"):
        select_video_output([RenderOutput(filename="preview.png", media_type="image")])


def test_queued_attempt_keeps_workflow_and_binding_snapshots() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        voice = VoiceProfile(
            name="Voice", provider="elevenlabs", provider_voice_id="voice"
        )
        character = Character(
            name="Elena", slug="snapshot-elena", default_voice_profile=voice
        )
        workflow = WorkflowTemplate(
            name="Snapshot workflow",
            renderer_provider="comfyui",
            workflow_json={"1": {"class_type": "Text", "inputs": {"text": "old"}}},
            checksum="snapshot-checksum",
        )
        profile = RenderProfile(
            name="Snapshot profile",
            character=character,
            voice_profile=voice,
            renderer_provider="comfyui",
        )
        session.add_all([workflow, profile])
        session.flush()
        profile.workflow_template_id = workflow.id
        workflow.bindings = [
            WorkflowParameterBinding(
                semantic_key="custom.camera_strength",
                node_id="1",
                input_name="text",
                value_type="string",
                required=True,
            )
        ]
        batch = Batch(name="Snapshot batch")
        job = TopicJob(
            batch=batch, topic="Snapshot topic", render_profile_id=profile.id
        )
        job.media_assets = [
            MediaAsset(
                kind="audio",
                object_key="jobs/snapshot/audio.mp3",
                filename="audio.mp3",
                content_type="audio/mpeg",
                size_bytes=5,
            )
        ]
        session.add(job)
        session.commit()
        job_id = job.id
        workflow_id = workflow.id

    repository = RenderExecutionRepository(factory)
    node = repository.create_node(
        RenderNodeCreate(name="Snapshot node", base_url="http://comfyui:8188")
    )
    attempt = repository.queue_attempt(job_id, node.id)
    with factory() as session:
        current = session.get(WorkflowTemplate, workflow_id)
        assert current is not None
        current.workflow_json = {"1": {"class_type": "Text", "inputs": {"text": "new"}}}
        current.bindings[0].semantic_key = "different_key"
        session.commit()

    queued = repository.get_attempt(attempt.id)
    assert queued is not None
    assert queued.workflow_snapshot["1"]["inputs"]["text"] == "old"  # type: ignore[index]
    assert queued.binding_snapshot[0]["semantic_key"] == "custom.camera_strength"


def test_queued_attempt_infers_ltx_control_bindings() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        voice = VoiceProfile(
            name="Voice", provider="elevenlabs", provider_voice_id="voice"
        )
        character = Character(
            name="Elena", slug="ltx-elena", default_voice_profile=voice
        )
        workflow = WorkflowTemplate(
            name="LTX workflow",
            renderer_provider="comfyui",
            workflow_json={
                "269": {
                    "class_type": "LoadImage",
                    "inputs": {"image": "workflow-default.png"},
                },
                "276": {
                    "class_type": "LoadAudio",
                    "inputs": {"audio": "workflow-default.mp3"},
                },
                "340:319": {
                    "_meta": {"title": "Prompt"},
                    "class_type": "PrimitiveStringMultiline",
                    "inputs": {"value": "Elena says {{SCRIPT}}"},
                },
                "340:323": {
                    "_meta": {"title": "Frame Rate"},
                    "class_type": "PrimitiveInt",
                    "inputs": {"value": 30},
                },
                "340:331": {
                    "_meta": {"title": "Duration"},
                    "class_type": "PrimitiveInt",
                    "inputs": {"value": 25},
                },
                "340:286": {
                    "_meta": {"title": "RandomNoise"},
                    "class_type": "RandomNoise",
                    "inputs": {"noise_seed": 473920259086225},
                },
            },
            checksum="ltx-checksum",
        )
        profile = RenderProfile(
            name="LTX profile",
            character=character,
            voice_profile=voice,
            renderer_provider="comfyui",
        )
        session.add_all([workflow, profile])
        session.flush()
        profile.workflow_template_id = workflow.id
        workflow.bindings = [
            WorkflowParameterBinding(
                semantic_key="audio",
                node_id="276",
                input_name="audio",
                value_type="string",
                required=True,
            ),
            WorkflowParameterBinding(
                semantic_key="source_image",
                node_id="269",
                input_name="image",
                value_type="string",
                required=True,
            ),
        ]
        batch = Batch(name="LTX batch")
        job = TopicJob(batch=batch, topic="LTX topic", render_profile_id=profile.id)
        job.media_assets = [
            MediaAsset(
                kind="audio",
                object_key="jobs/ltx/audio.mp3",
                filename="audio.mp3",
                content_type="audio/mpeg",
                size_bytes=5,
            )
        ]
        session.add(job)
        session.commit()
        job_id = job.id

    repository = RenderExecutionRepository(factory)
    node = repository.create_node(
        RenderNodeCreate(name="LTX node", base_url="http://comfyui:8188")
    )
    attempt = repository.queue_attempt(job_id, node.id)

    semantic_keys = {
        binding["semantic_key"]: binding for binding in attempt.binding_snapshot
    }
    assert semantic_keys["video_prompt"]["node_id"] == "340:319"
    assert semantic_keys["fps"]["node_id"] == "340:323"
    assert semantic_keys["duration"]["node_id"] == "340:331"
    assert semantic_keys["seed"]["node_id"] == "340:286"
    assert semantic_keys["audio"]["node_id"] == "276"
