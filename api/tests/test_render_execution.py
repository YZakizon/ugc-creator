from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models import (
    Batch,
    Character,
    RenderProfile,
    TopicJob,
    VoiceProfile,
    WorkflowParameterBinding,
    WorkflowTemplate,
)
from app.render_repository import RenderExecutionRepository
from app.schemas import RenderNodeCreate
from app.workers.render_tasks import apply_default_workflow_media, render_has_timed_out


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
    repo.complete(first.id, "jobs/video.mp4", "video.mp4", "video/mp4", 12)
    completed = repo.get_attempt(first.id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.external_job_id == "prompt-1"
    assert completed.assets[0].object_key == "jobs/video.mp4"


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

    with factory() as session:
        stored = session.get(type(attempt), attempt.id)
        assert stored is not None
        stored.status = "submitting_render"
        stored.submission_claim_expires_at = None
        stored.updated_at = datetime.now(UTC) - timedelta(minutes=6)
        session.commit()

    assert repository.claim_submission(attempt.id) == (True, 0)


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
