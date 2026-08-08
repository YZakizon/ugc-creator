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
    WorkflowTemplate,
)
from app.render_repository import RenderExecutionRepository
from app.schemas import RenderNodeCreate
from app.workers.render_tasks import apply_default_workflow_media


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
