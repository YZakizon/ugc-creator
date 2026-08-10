from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models import (
    Batch,
    Character,
    MediaAsset,
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
from app.providers.render.contracts import RenderOutput
from app.render_repository import RenderExecutionRepository
from app.schemas import RenderNodeCreate
from app.services.media_service import MediaProcessingError
from app.workers.render_tasks import (
    _prepare_and_submit,
    apply_default_workflow_media,
    render_has_timed_out,
    select_video_output,
    submit_render,
)


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
        workflow_snapshot={"1": {"class_type": "Text", "inputs": {}}},
        binding_snapshot=[],
    )
    job = SimpleNamespace(
        speech_script="Prepared script",
        topic="Prepared topic",
        hook=None,
        target_duration_seconds=30,
        media_assets=[],
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
    )

    assert values["source_image"] == "batch-image.png"
    assert values["audio"] == "comfy-default.mp3"
    storage.get.assert_called_once_with("workflow-media/default.mp3")
    renderer.upload.assert_awaited_once_with("default.mp3", b"audio", "audio")


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
    assert len(completed.assets) == 1
    assert completed.assets[0].object_key == "jobs/video.mp4"
    assert repo.delete_video_asset(completed.assets[0].id)
    with factory() as session:
        reset_job = session.get(TopicJob, job_id)
        assert reset_job is not None
        assert reset_job.status == "ready_to_render"


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
