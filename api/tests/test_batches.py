import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.providers.storage.local import LocalStorageProvider
from app.repositories import (
    InMemoryBatchRepository,
    InMemoryConfigurationRepository,
    SqlAlchemyBatchRepository,
    SqlAlchemyConfigurationRepository,
    topic_to_dict,
    utc_now,
)
from app.schemas import (
    BatchCreate,
    RenderProfileSetupCreate,
    RenderProfileUpdate,
    TopicBulkCreate,
    VoiceProfileCreate,
    WorkflowTemplateCreate,
)


@pytest.mark.asyncio
async def test_create_batch_creates_draft_jobs_and_summary() -> None:
    app.state.batch_repository = InMemoryBatchRepository()
    app.state.configuration_repository = InMemoryConfigurationRepository()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/v1/batches",
            json={
                "name": "Ideas for Tuesday",
                "topics": ["Burnout is not laziness", "A reminder for overthinkers"],
                "target_duration_seconds": 30,
                "auto_fit_duration": True,
            },
        )
        summary = await client.get("/api/v1/dashboard/summary")

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Ideas for Tuesday"
    assert body["status"] == "draft"
    assert [job["status"] for job in body["jobs"]] == ["draft", "draft"]
    assert summary.status_code == 200
    assert {job["topic"] for job in summary.json()["recent_jobs"]} == {
        "Burnout is not laziness",
        "A reminder for overthinkers",
    }


@pytest.mark.asyncio
async def test_topic_generates_incrementing_content_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batches = InMemoryBatchRepository()
    configuration = InMemoryConfigurationRepository()
    app.state.batch_repository = batches
    app.state.configuration_repository = configuration
    voice = configuration.create_voice_profile(
        VoiceProfileCreate(
            name="Voice", provider="elevenlabs", provider_voice_id="voice-1"
        )
    )
    profile = configuration.create_render_profile_setup(
        RenderProfileSetupCreate(
            profile_name="Shelf",
            character_name="Elena",
            voice_profile_id=voice.id,
            renderer_provider="comfyui",
        )
    )
    queued: list[str] = []
    monkeypatch.setenv("UGC_FAKE_PROVIDERS", "1")
    monkeypatch.setattr("app.api.routes.generate_job_content.delay", queued.append)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        created = await client.post(
            "/api/v1/topics",
            json={
                "topic": "Burnout is not laziness",
                "render_profile_id": str(profile.id),
                "target_duration_seconds": 30,
                "auto_fit_duration": True,
            },
        )
        topic_id = created.json()["id"]
        second = await client.post(f"/api/v1/topics/{topic_id}/contents")
        third = await client.post(f"/api/v1/topics/{topic_id}/contents")
        listed = await client.get("/api/v1/topics")

    assert created.status_code == 201
    assert created.json()["contents"][0]["content_number"] == 1
    assert second.status_code == 202
    assert third.status_code == 202
    assert [
        item["content_number"] for item in listed.json()["items"][0]["contents"]
    ] == [1, 2, 3]
    assert queued == [second.json()["id"], third.json()["id"]]


@pytest.mark.asyncio
async def test_generate_more_content_recovers_when_broker_enqueue_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batches = InMemoryBatchRepository()
    topic = batches.create_batch(BatchCreate(name="Topic", topics=["A topic"]))
    app.state.batch_repository = batches
    app.state.configuration_repository = InMemoryConfigurationRepository()
    monkeypatch.setenv("UGC_FAKE_PROVIDERS", "1")
    monkeypatch.setattr(
        "app.api.routes.generate_job_content.delay",
        lambda _job_id: (_ for _ in ()).throw(RuntimeError("Redis unavailable")),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(f"/api/v1/topics/{topic.id}/contents")
        recovered = batches.get_batch(topic.id)
        assert recovered is not None
        new_content = max(recovered.jobs, key=lambda item: item.content_number)
        deleted = await client.delete(f"/api/v1/contents/{new_content.id}")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "provider_unavailable"
    assert new_content.status == "draft"
    assert new_content.error_message == "Content could not be queued. Try again."
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_bulk_topic_creation_keeps_topics_independent() -> None:
    batches = InMemoryBatchRepository()
    configuration = InMemoryConfigurationRepository()
    app.state.batch_repository = batches
    app.state.configuration_repository = configuration
    voice = configuration.create_voice_profile(
        VoiceProfileCreate(
            name="Voice", provider="elevenlabs", provider_voice_id="voice-1"
        )
    )
    profile = configuration.create_render_profile_setup(
        RenderProfileSetupCreate(
            profile_name="Shelf",
            character_name="Elena",
            voice_profile_id=voice.id,
            renderer_provider="comfyui",
        )
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/v1/topics/bulk",
            json={
                "topics": ["Burnout is not laziness", "A reminder for overthinkers"],
                "render_profile_id": str(profile.id),
                "target_duration_seconds": 30,
                "auto_fit_duration": True,
            },
        )

    assert response.status_code == 201
    assert response.json()["total"] == 2
    assert [item["content_count"] for item in response.json()["items"]] == [1, 1]
    assert [
        item["contents"][0]["content_number"] for item in response.json()["items"]
    ] == [1, 1]


def test_content_numbers_use_high_water_mark_and_topic_defaults() -> None:
    batches = InMemoryBatchRepository()
    default_profile_id = uuid4()
    topic = batches.create_batch(
        BatchCreate(
            name="Topic",
            topics=["A topic"],
            default_render_profile_id=default_profile_id,
            target_duration_seconds=45,
        )
    )
    first = topic.jobs[0]
    first.render_profile_id = uuid4()
    first.voice_profile_id = uuid4()
    first.workflow_template_id = uuid4()
    second = batches.create_content(topic.id)
    assert second is not None
    second.status = "content_ready"
    assert batches.delete_content(second.id)

    third = batches.create_content(topic.id)

    assert third is not None
    assert third.content_number == 3
    assert third.render_profile_id == default_profile_id
    assert third.voice_profile_id is None
    assert third.workflow_template_id is None
    assert third.target_duration_seconds == 45


def test_topic_status_is_derived_from_content_lifecycle() -> None:
    batches = InMemoryBatchRepository()
    topic = batches.create_batch(BatchCreate(name="Topic", topics=["A topic"]))
    content = topic.jobs[0]
    assert topic_to_dict(topic)["status"] == "draft"

    content.status = "generating_content"
    assert topic_to_dict(topic)["status"] == "processing"

    content.status = "completed"
    assert topic_to_dict(topic)["status"] == "completed"

    content.status = "failed"
    assert topic_to_dict(topic)["status"] == "failed"


@pytest.mark.asyncio
async def test_content_and_topic_delete_all_stored_assets(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    batches = InMemoryBatchRepository()
    app.state.batch_repository = batches
    app.state.configuration_repository = InMemoryConfigurationRepository()
    monkeypatch.setenv("MEDIA_STORAGE_ROOT", str(tmp_path))
    storage = LocalStorageProvider()
    topic = batches.create_batch(BatchCreate(name="Topic", topics=["A topic"]))
    first = topic.jobs[0]
    second = batches.create_content(topic.id)
    assert second is not None
    first_key = f"topics/{topic.id}/contents/{first.id}/audio/first.mp3"
    second_key = f"topics/{topic.id}/contents/{second.id}/video/second.mp4"
    storage.put(first_key, b"audio")
    storage.put(second_key, b"video")
    first.media_assets = [
        models.MediaAsset(
            id=uuid4(),
            job_id=first.id,
            kind="audio",
            object_key=first_key,
            filename="first.mp3",
            content_type="audio/mpeg",
            size_bytes=5,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
    ]
    second.media_assets = [
        models.MediaAsset(
            id=uuid4(),
            job_id=second.id,
            kind="video",
            object_key=second_key,
            filename="second.mp4",
            content_type="video/mp4",
            size_bytes=5,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
    ]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        deleted_content = await client.delete(f"/api/v1/contents/{first.id}")
        rejected_last_content = await client.delete(f"/api/v1/contents/{second.id}")
        deleted_topic = await client.delete(f"/api/v1/topics/{topic.id}")

    assert deleted_content.status_code == 204
    assert rejected_last_content.status_code == 409
    assert rejected_last_content.json()["detail"] == (
        "Delete the topic to remove its only content version"
    )
    assert deleted_topic.status_code == 204
    assert not (tmp_path / first_key).exists()
    assert not (tmp_path / second_key).exists()
    assert batches.get_batch(topic.id) is None


@pytest.mark.asyncio
async def test_completed_job_render_profile_can_change_before_rerendering() -> None:
    batches = InMemoryBatchRepository()
    configuration = InMemoryConfigurationRepository()
    app.state.batch_repository = batches
    app.state.configuration_repository = configuration
    voice = configuration.create_voice_profile(
        VoiceProfileCreate(
            name="Voice", provider="elevenlabs", provider_voice_id="voice-1"
        )
    )
    first = configuration.create_render_profile_setup(
        RenderProfileSetupCreate(
            profile_name="Shelf",
            character_name="Elena",
            voice_profile_id=voice.id,
            renderer_provider="comfyui",
        )
    )
    second = configuration.create_render_profile_setup(
        RenderProfileSetupCreate(
            profile_name="Studio",
            character_name="Elena",
            voice_profile_id=voice.id,
            renderer_provider="comfyui",
        )
    )
    batch = batches.create_batch(
        BatchCreate(
            name="Tuesday videos",
            topics=["One topic"],
            default_render_profile_id=first.id,
        )
    )
    batch.jobs[0].status = "completed"
    batch.jobs[0].speech_script = "Finished speech"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.patch(
            f"/api/v1/jobs/{batch.jobs[0].id}/render-profile",
            json={"render_profile_id": str(second.id)},
        )
        batch.jobs[0].status = "rendering"
        locked = await client.patch(
            f"/api/v1/jobs/{batch.jobs[0].id}/render-profile",
            json={"render_profile_id": str(first.id)},
        )

    assert response.status_code == 200
    assert response.json()["render_profile_id"] == str(second.id)
    assert response.json()["status"] == "ready_to_render"
    assert batches.get_job(batch.jobs[0].id).render_profile_id == second.id
    assert locked.status_code == 409


@pytest.mark.asyncio
async def test_job_voice_and_workflow_can_override_profile_defaults() -> None:
    batches = InMemoryBatchRepository()
    configuration = InMemoryConfigurationRepository()
    app.state.batch_repository = batches
    app.state.configuration_repository = configuration
    first_voice = configuration.create_voice_profile(
        VoiceProfileCreate(
            name="First voice", provider="elevenlabs", provider_voice_id="voice-1"
        )
    )
    second_voice = configuration.create_voice_profile(
        VoiceProfileCreate(
            name="Second voice", provider="elevenlabs", provider_voice_id="voice-2"
        )
    )
    first_workflow = configuration.create_workflow_template(
        WorkflowTemplateCreate(
            name="First workflow",
            workflow_json={"1": {"class_type": "Text", "inputs": {"text": "one"}}},
        ),
        "first-checksum",
    )
    second_workflow = configuration.create_workflow_template(
        WorkflowTemplateCreate(
            name="Second workflow",
            workflow_json={"1": {"class_type": "Text", "inputs": {"text": "two"}}},
        ),
        "second-checksum",
    )
    profile = configuration.create_render_profile_setup(
        RenderProfileSetupCreate(
            profile_name="Shelf",
            character_name="Elena",
            voice_profile_id=first_voice.id,
            workflow_template_id=first_workflow.id,
        )
    )
    batch = batches.create_batch(
        BatchCreate(
            name="Overrides",
            topics=["Voice topic", "Workflow topic"],
            default_render_profile_id=profile.id,
        )
    )
    voice_job, workflow_job = batch.jobs
    voice_job.status = "completed"
    voice_job.speech_script = "Finished voice speech"
    workflow_job.status = "completed"
    workflow_job.speech_script = "Finished workflow speech"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        voice_response = await client.patch(
            f"/api/v1/jobs/{voice_job.id}/voice-profile",
            json={"voice_profile_id": str(second_voice.id)},
        )
        workflow_response = await client.patch(
            f"/api/v1/jobs/{workflow_job.id}/workflow-template",
            json={"workflow_template_id": str(second_workflow.id)},
        )

    assert voice_response.status_code == 200
    assert voice_response.json()["voice_profile_id"] == str(second_voice.id)
    assert voice_response.json()["status"] == "content_ready"
    assert workflow_response.status_code == 200
    assert workflow_response.json()["workflow_template_id"] == str(second_workflow.id)
    assert workflow_response.json()["status"] == "ready_to_render"


@pytest.mark.asyncio
async def test_job_audio_upload_becomes_render_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    batches = InMemoryBatchRepository()
    app.state.batch_repository = batches
    app.state.configuration_repository = InMemoryConfigurationRepository()
    batch = batches.create_batch(BatchCreate(name="Audio", topics=["One topic"]))
    job = batch.jobs[0]
    job.status = "completed"
    monkeypatch.setenv("MEDIA_STORAGE_ROOT", str(tmp_path))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/api/v1/jobs/{job.id}/audio",
            json={
                "filename": "replacement.mp3",
                "content_type": "audio/mpeg",
                "content_base64": base64.b64encode(b"audio bytes").decode(),
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "ready_to_render"
    assert (
        response.json()["audio_asset"]["filename"] == "one-topic_content1_1-audio.mp3"
    )
    assert list(tmp_path.rglob("*one-topic_content1_1-audio.mp3"))


@pytest.mark.asyncio
async def test_job_audio_upload_object_keys_are_unique_for_same_filename(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    batches = InMemoryBatchRepository()
    app.state.batch_repository = batches
    app.state.configuration_repository = InMemoryConfigurationRepository()
    batch = batches.create_batch(BatchCreate(name="Audio", topics=["One topic"]))
    job = batch.jobs[0]
    job.status = "completed"
    monkeypatch.setenv("MEDIA_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(
        "app.api.routes.generated_media_filename",
        lambda *_args: "one-topic_content1_1-audio.mp3",
    )
    payload = {
        "filename": "replacement.mp3",
        "content_type": "audio/mpeg",
        "content_base64": base64.b64encode(b"audio bytes").decode(),
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        first = await client.post(f"/api/v1/jobs/{job.id}/audio", json=payload)
        second = await client.post(f"/api/v1/jobs/{job.id}/audio", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    object_keys = {asset.object_key for asset in job.media_assets}
    assert len(object_keys) == 2
    assert len(list(tmp_path.rglob("one-topic_content1_1-audio.mp3"))) == 2


@pytest.mark.asyncio
async def test_create_batch_rejects_blank_topics() -> None:
    app.state.batch_repository = InMemoryBatchRepository()
    app.state.configuration_repository = InMemoryConfigurationRepository()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/v1/batches",
            json={"topics": ["  ", ""]},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_configuration_profiles_connect_character_and_voice() -> None:
    app.state.batch_repository = InMemoryBatchRepository()
    app.state.configuration_repository = InMemoryConfigurationRepository()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        voice_response = await client.post(
            "/api/v1/voice-profiles",
            json={
                "name": "Elena voice",
                "provider": "elevenlabs",
                "provider_voice_id": "voice-elena",
            },
        )
        voice_id = voice_response.json()["id"]
        character_response = await client.post(
            "/api/v1/characters",
            json={"name": "Elena", "default_voice_profile_id": voice_id},
        )
        character_id = character_response.json()["id"]
        profile_response = await client.post(
            "/api/v1/render-profiles",
            json={
                "name": "Elena Shelf ComfyUI",
                "character_id": character_id,
                "voice_profile_id": voice_id,
                "renderer_provider": "comfyui",
                "capabilities": {"supports_audio": True},
            },
        )
        summary = await client.get("/api/v1/dashboard/summary")

    assert voice_response.status_code == 201
    assert character_response.status_code == 201
    assert profile_response.status_code == 201
    assert profile_response.json()["renderer_provider"] == "comfyui"
    assert summary.json()["render_profiles"] == 1


@pytest.mark.asyncio
async def test_voice_profile_parameters_can_be_created_and_updated() -> None:
    app.state.batch_repository = InMemoryBatchRepository()
    app.state.configuration_repository = InMemoryConfigurationRepository()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        created = await client.post(
            "/api/v1/voice-profiles",
            json={
                "name": "Elena voice profile",
                "provider": "elevenlabs",
                "provider_voice_id": "voice-elena",
                "provider_model": "eleven_multilingual_v2",
                "speed": 1.05,
                "stability": 0.5,
                "similarity": 0.75,
                "style_exaggeration": 0.2,
                "extra_settings": {"voice_name": "Hope"},
            },
        )
        updated = await client.patch(
            f"/api/v1/voice-profiles/{created.json()['id']}",
            json={
                "name": "Elena polished",
                "provider": "elevenlabs",
                "provider_voice_id": "voice-elena",
                "provider_model": "eleven_multilingual_v2",
                "speed": 0.95,
                "stability": 0.6,
                "similarity": 0.8,
                "style_exaggeration": 0.1,
                "extra_settings": {"voice_name": "Hope"},
            },
        )

    assert created.status_code == 201
    assert updated.status_code == 200
    assert updated.json()["name"] == "Elena polished"
    assert updated.json()["speed"] == 0.95
    assert updated.json()["stability"] == 0.6
    assert updated.json()["extra_settings"]["voice_name"] == "Hope"


@pytest.mark.asyncio
async def test_voice_profile_delete_respects_profile_references() -> None:
    app.state.batch_repository = InMemoryBatchRepository()
    app.state.configuration_repository = InMemoryConfigurationRepository()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        unused = await client.post(
            "/api/v1/voice-profiles",
            json={
                "name": "Unused",
                "provider": "elevenlabs",
                "provider_voice_id": "unused",
            },
        )
        deleted = await client.delete(f"/api/v1/voice-profiles/{unused.json()['id']}")
        voice = await client.post(
            "/api/v1/voice-profiles",
            json={
                "name": "Used",
                "provider": "elevenlabs",
                "provider_voice_id": "used",
            },
        )
        character = await client.post(
            "/api/v1/characters",
            json={"name": "Uses voice", "default_voice_profile_id": voice.json()["id"]},
        )
        render_profile = await client.post(
            "/api/v1/render-profiles",
            json={
                "name": "Elena Shelf Profile",
                "character_id": character.json()["id"],
                "voice_profile_id": voice.json()["id"],
                "renderer_provider": "comfyui",
            },
        )
        blocked = await client.delete(f"/api/v1/voice-profiles/{voice.json()['id']}")

    assert character.status_code == 201
    assert deleted.status_code == 204
    assert render_profile.status_code == 201
    assert blocked.status_code == 409
    detail = blocked.json()["detail"]
    assert detail["code"] == "voice_profile_in_use"
    assert detail["render_profiles"] == [
        {"id": render_profile.json()["id"], "name": "Elena Shelf Profile"}
    ]
    assert detail["characters"] == [
        {"id": character.json()["id"], "name": "Uses voice"}
    ]
    assert render_profile.json()["id"] in detail["message"]


@pytest.mark.asyncio
async def test_render_profile_can_unassign_voice_then_delete_it() -> None:
    app.state.batch_repository = InMemoryBatchRepository()
    app.state.configuration_repository = InMemoryConfigurationRepository()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        voice = await client.post(
            "/api/v1/voice-profiles",
            json={
                "name": "Temporary voice",
                "provider": "elevenlabs",
                "provider_voice_id": "temporary",
            },
        )
        character = await client.post(
            "/api/v1/characters",
            json={
                "name": "Elena",
                "default_voice_profile_id": voice.json()["id"],
            },
        )
        profile = await client.post(
            "/api/v1/render-profiles",
            json={
                "name": "Elena profile",
                "character_id": character.json()["id"],
                "voice_profile_id": voice.json()["id"],
                "renderer_provider": "comfyui",
            },
        )
        updated = await client.patch(
            f"/api/v1/render-profiles/{profile.json()['id']}",
            json={
                "name": "Elena profile",
                "character_name": "Elena",
                "voice_profile_id": None,
                "workflow_template_id": None,
            },
        )
        blocked_batch = await client.post(
            "/api/v1/batches",
            json={
                "topics": ["A topic"],
                "default_render_profile_id": profile.json()["id"],
            },
        )
        deleted = await client.delete(f"/api/v1/voice-profiles/{voice.json()['id']}")

    assert updated.status_code == 200
    assert updated.json()["voice_profile_id"] is None
    assert blocked_batch.status_code == 422
    assert blocked_batch.json()["detail"] == (
        "Render profile requires a connected voice profile"
    )
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_voice_preview_is_queued_polled_and_downloaded(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    app.state.batch_repository = InMemoryBatchRepository()
    repository = InMemoryConfigurationRepository()
    app.state.configuration_repository = repository
    queued: list[str] = []
    monkeypatch.setattr("app.api.routes.generate_voice_preview.delay", queued.append)
    monkeypatch.setenv("MEDIA_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("UGC_FAKE_PROVIDERS", "1")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        voice = await client.post(
            "/api/v1/voice-profiles",
            json={
                "name": "Preview voice",
                "provider": "elevenlabs",
                "provider_voice_id": "voice-preview",
                "style_exaggeration": 0.5,
                "extra_settings": {"output_format": "mp3_44100_128"},
            },
        )
        account_usage = await client.get("/api/v1/tts-providers/elevenlabs/usage")
        voices = await client.get("/api/v1/tts-providers/elevenlabs/voices")
        created = await client.post(
            f"/api/v1/voice-profiles/{voice.json()['id']}/previews",
            json={"text": "This is a speech preview."},
        )
        preview = repository.voice_previews[next(iter(repository.voice_previews))]
        queued_delete = await client.delete(f"/api/v1/voice-previews/{preview.id}")
        preview.status = "generating"
        generating_delete = await client.delete(f"/api/v1/voice-previews/{preview.id}")
        preview.status = "completed"
        preview.asset_key = f"voice-previews/{preview.id}/speech.mp3"
        preview.content_type = "audio/mpeg"
        preview.filename = "preview.mp3"
        (tmp_path / preview.asset_key).parent.mkdir(parents=True)
        (tmp_path / preview.asset_key).write_bytes(b"ID3preview")
        polled = await client.get(f"/api/v1/voice-previews/{preview.id}")
        audio = await client.get(f"/api/v1/voice-previews/{preview.id}/audio")
        history = await client.get(
            f"/api/v1/voice-profiles/{voice.json()['id']}/previews"
        )
        deleted = await client.delete(f"/api/v1/voice-previews/{preview.id}")
        history_after_delete = await client.get(
            f"/api/v1/voice-profiles/{voice.json()['id']}/previews"
        )

    assert created.status_code == 202
    assert account_usage.json()["remaining_units"] == 9_875
    assert voices.json()["items"][0]["voice_id"] == "fake-voice-hope"
    assert created.json()["status"] == "queued"
    assert queued == [created.json()["id"]]
    assert queued_delete.status_code == 409
    assert queued_delete.json()["detail"]["code"] == "voice_preview_in_progress"
    assert generating_delete.status_code == 409
    assert generating_delete.json()["detail"]["code"] == "voice_preview_in_progress"
    assert polled.json()["download_url"].endswith(f"/{preview.id}/audio")
    assert audio.status_code == 200
    assert audio.content == b"ID3preview"
    assert audio.headers["content-type"] == "audio/mpeg"
    assert history.status_code == 200
    assert [item["id"] for item in history.json()["items"]] == [str(preview.id)]
    assert deleted.status_code == 204
    assert history_after_delete.json() == {"items": [], "total": 0}
    assert not (tmp_path / preview.asset_key).exists()


@pytest.mark.asyncio
async def test_stale_generating_voice_preview_requires_explicit_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app.state.batch_repository = InMemoryBatchRepository()
    repository = InMemoryConfigurationRepository()
    app.state.configuration_repository = repository
    queued: list[str] = []
    monkeypatch.setattr("app.api.routes.generate_voice_preview.delay", queued.append)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        voice = await client.post(
            "/api/v1/voice-profiles",
            json={
                "name": "Recoverable voice",
                "provider": "elevenlabs",
                "provider_voice_id": "voice-recovery",
            },
        )
        endpoint = f"/api/v1/voice-profiles/{voice.json()['id']}/previews"
        first = await client.post(endpoint, json={"text": "Recover this preview."})
        preview = repository.voice_previews[next(iter(repository.voice_previews))]
        preview.status = "generating"
        preview.updated_at = utc_now() - timedelta(minutes=6)
        second = await client.post(endpoint, json={"text": "Recover this preview."})
        third = await client.post(endpoint, json={"text": "Recover this preview."})

    assert second.json()["id"] == first.json()["id"]
    assert second.json()["status"] == "failed"
    assert "outcome is unknown" in second.json()["error_message"]
    assert third.json()["status"] == "queued"
    assert queued == [first.json()["id"], first.json()["id"]]


def test_sql_repository_requires_explicit_retry_for_stale_generating_preview() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repository = SqlAlchemyConfigurationRepository(factory)
    profile = repository.create_voice_profile(
        VoiceProfileCreate(
            name="Elena voice",
            provider="elevenlabs",
            provider_voice_id="voice-elena",
        )
    )
    preview, created = repository.create_voice_preview(
        profile.id, "A short preview", "stale-preview-fingerprint"
    )

    assert created is True
    with factory() as session:
        stored = session.get(models.VoicePreview, preview.id)
        assert stored is not None
        stored.status = "generating"
        stored.updated_at = utc_now() - timedelta(minutes=6)
        session.commit()

    recovered, should_enqueue = repository.create_voice_preview(
        profile.id, "A short preview", "stale-preview-fingerprint"
    )

    assert recovered.id == preview.id
    assert recovered.status == "failed"
    assert recovered.error_message is not None
    assert "outcome is unknown" in recovered.error_message
    assert should_enqueue is False

    retried, should_enqueue = repository.create_voice_preview(
        profile.id, "A short preview", "stale-preview-fingerprint"
    )
    assert retried.status == "queued"
    assert should_enqueue is True


def test_voice_preview_claim_token_rejects_late_worker_update() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repository = SqlAlchemyConfigurationRepository(factory)
    profile = repository.create_voice_profile(
        VoiceProfileCreate(
            name="Owned voice",
            provider="elevenlabs",
            provider_voice_id="voice-owned",
        )
    )
    preview, _ = repository.create_voice_preview(
        profile.id, "Owned preview", "owned-preview"
    )
    first_claim = repository.claim_voice_preview(preview.id)
    assert first_claim is not None
    _claimed_preview, first_token = first_claim

    with factory() as session:
        stored = session.get(models.VoicePreview, preview.id)
        assert stored is not None
        stored.status = "failed"
        stored.claim_token = None
        stored.claim_expires_at = None
        session.commit()
    repository.create_voice_preview(profile.id, "Owned preview", "owned-preview")
    second_claim = repository.claim_voice_preview(preview.id)
    assert second_claim is not None
    _claimed_preview, second_token = second_claim

    assert (
        repository.update_voice_preview(
            preview.id, status="completed", claim_token=first_token
        )
        is None
    )
    completed = repository.update_voice_preview(
        preview.id, status="completed", claim_token=second_token
    )
    assert completed is not None
    assert completed.status == "completed"


def test_expired_voice_preview_claim_is_resolved_without_resynthesis() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repository = SqlAlchemyConfigurationRepository(factory)
    profile = repository.create_voice_profile(
        VoiceProfileCreate(
            name="Recover owned voice",
            provider="elevenlabs",
            provider_voice_id="voice-recover-owned",
        )
    )
    preview, _ = repository.create_voice_preview(
        profile.id, "Recover after worker loss", "worker-loss-preview"
    )
    claim = repository.claim_voice_preview(preview.id)
    assert claim is not None
    _claimed_preview, stale_token = claim
    with factory() as session:
        stored = session.get(models.VoicePreview, preview.id)
        assert stored is not None
        stored.claim_expires_at = utc_now() - timedelta(seconds=1)
        session.commit()

    status, retry_after = repository.reconcile_voice_preview_claim(preview.id)

    assert (status, retry_after) == ("failed", 0)
    resolved = repository.get_voice_preview(preview.id)
    assert resolved is not None
    assert resolved.error_message is not None
    assert "outcome is unknown" in resolved.error_message
    assert resolved.claim_token is None
    assert (
        repository.update_voice_preview(
            preview.id, status="completed", claim_token=stale_token
        )
        is None
    )


def test_voice_preview_claim_allows_only_one_concurrent_worker(tmp_path) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'voice-claim.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repository = SqlAlchemyConfigurationRepository(factory)
    profile = repository.create_voice_profile(
        VoiceProfileCreate(
            name="Claimed voice",
            provider="elevenlabs",
            provider_voice_id="voice-claim",
        )
    )
    preview, _ = repository.create_voice_preview(
        profile.id, "Charge only once", "concurrent-claim"
    )
    barrier = Barrier(2)

    def claim() -> bool:
        barrier.wait()
        return repository.claim_voice_preview(preview.id) is not None

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(lambda _index: claim(), range(2)))

    assert sorted(claims) == [False, True]


@pytest.mark.asyncio
async def test_render_profile_setup_is_atomic_api_operation() -> None:
    app.state.batch_repository = InMemoryBatchRepository()
    app.state.configuration_repository = InMemoryConfigurationRepository()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        voice = await client.post(
            "/api/v1/voice-profiles",
            json={
                "name": "Elena voice",
                "provider": "elevenlabs",
                "provider_voice_id": "voice-elena",
            },
        )
        response = await client.post(
            "/api/v1/render-profiles/setup",
            json={
                "profile_name": "Elena Shelf ComfyUI",
                "character_name": "Elena",
                "voice_profile_id": voice.json()["id"],
                "renderer_provider": "comfyui",
            },
        )
        profiles = await client.get("/api/v1/render-profiles")
        voices = await client.get("/api/v1/voice-profiles")
        characters = await client.get("/api/v1/characters")

    assert response.status_code == 201
    assert profiles.json()["total"] == 1
    assert voices.json()["total"] == 1
    assert characters.json()["total"] == 1


@pytest.mark.asyncio
async def test_render_profile_setup_reuses_character_and_voice() -> None:
    app.state.batch_repository = InMemoryBatchRepository()
    app.state.configuration_repository = InMemoryConfigurationRepository()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        voice = await client.post(
            "/api/v1/voice-profiles",
            json={
                "name": "Elena voice",
                "provider": "elevenlabs",
                "provider_voice_id": "voice-elena",
            },
        )
        setup = {
            "character_name": "Elena",
            "voice_profile_id": voice.json()["id"],
            "renderer_provider": "comfyui",
        }
        first = await client.post(
            "/api/v1/render-profiles/setup",
            json={**setup, "profile_name": "Elena Shelf"},
        )
        second = await client.post(
            "/api/v1/render-profiles/setup",
            json={**setup, "profile_name": "Elena Studio"},
        )
        profiles = await client.get("/api/v1/render-profiles")
        voices = await client.get("/api/v1/voice-profiles")
        characters = await client.get("/api/v1/characters")

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["character_id"] == second.json()["character_id"]
    assert first.json()["voice_profile_id"] == second.json()["voice_profile_id"]
    assert profiles.json()["total"] == 2
    assert voices.json()["total"] == 1
    assert characters.json()["total"] == 1


@pytest.mark.asyncio
async def test_render_profile_rejects_unknown_character() -> None:
    app.state.batch_repository = InMemoryBatchRepository()
    app.state.configuration_repository = InMemoryConfigurationRepository()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/v1/render-profiles",
            json={
                "name": "Invalid profile",
                "character_id": "00000000-0000-0000-0000-000000000001",
                "voice_profile_id": "00000000-0000-0000-0000-000000000002",
                "renderer_provider": "comfyui",
            },
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_render_profile_can_be_updated_and_deleted() -> None:
    app.state.batch_repository = InMemoryBatchRepository()
    app.state.configuration_repository = InMemoryConfigurationRepository()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        voice = await client.post(
            "/api/v1/voice-profiles",
            json={"name": "Voice", "provider": "elevenlabs", "provider_voice_id": "v1"},
        )
        character = await client.post(
            "/api/v1/characters",
            json={"name": "Character", "default_voice_profile_id": voice.json()["id"]},
        )
        profile = await client.post(
            "/api/v1/render-profiles",
            json={
                "name": "Original profile",
                "character_id": character.json()["id"],
                "voice_profile_id": voice.json()["id"],
                "renderer_provider": "comfyui",
            },
        )
        profile_id = profile.json()["id"]
        updated = await client.patch(
            f"/api/v1/render-profiles/{profile_id}",
            json={
                "name": "Updated profile",
                "character_name": "Updated Character",
                "voice_profile_id": voice.json()["id"],
            },
        )
        updated_characters = await client.get("/api/v1/characters")
        updated_voices = await client.get("/api/v1/voice-profiles")
        deleted = await client.delete(f"/api/v1/render-profiles/{profile_id}")
        missing = await client.patch(
            f"/api/v1/render-profiles/{profile_id}",
            json={"name": "Missing profile"},
        )

    assert profile.status_code == 201
    assert updated.status_code == 200
    assert updated.json()["name"] == "Updated profile"
    assert updated_characters.json()["items"][0]["name"] == "Updated Character"
    assert updated_voices.json()["items"][0]["name"] == "Voice"
    assert updated_voices.json()["items"][0]["provider_voice_id"] == "v1"
    assert deleted.status_code == 204
    assert missing.status_code == 404


def test_sqlalchemy_repository_returns_jobs_after_commit() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyBatchRepository(sessionmaker(bind=engine))

    batch = repository.create_batch(
        BatchCreate(name="Persistent batch", topics=["A topic"])
    )

    assert batch.jobs[0].topic == "A topic"


def test_sqlalchemy_topics_are_transactional_and_keep_content_high_water_mark() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyBatchRepository(sessionmaker(bind=engine))
    profile_id = uuid4()
    topics = repository.create_topics(
        TopicBulkCreate(
            topics=["First topic", "Second topic"],
            render_profile_id=profile_id,
            target_duration_seconds=45,
        )
    )

    assert len(topics) == 2
    assert [topic.jobs[0].content_number for topic in topics] == [1, 1]
    second = repository.create_content(topics[0].id)
    assert second is not None
    assert repository.delete_content(second.id)
    third = repository.create_content(topics[0].id)

    assert third is not None
    assert third.content_number == 3
    assert third.render_profile_id == profile_id
    assert third.target_duration_seconds == 45


def test_sqlalchemy_profile_setup_reuses_character_and_voice() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyConfigurationRepository(sessionmaker(bind=engine))
    voice = repository.create_voice_profile(
        VoiceProfileCreate(
            name="Elena voice",
            provider="elevenlabs",
            provider_voice_id="voice-elena",
        )
    )
    setup = {
        "character_name": "Elena",
        "voice_profile_id": voice.id,
        "renderer_provider": "comfyui",
    }

    first = repository.create_render_profile_setup(
        RenderProfileSetupCreate(**setup, profile_name="Elena Shelf")
    )
    second = repository.create_render_profile_setup(
        RenderProfileSetupCreate(**setup, profile_name="Elena Studio")
    )
    updated = repository.update_render_profile(
        second.id,
        RenderProfileUpdate(
            name="Elena Studio Updated",
            character_name="Elena Updated",
            voice_profile_id=voice.id,
        ),
    )
    profiles, profile_count = repository.list_render_profiles()
    voices, voice_count = repository.list_voice_profiles()
    characters, character_count = repository.list_characters()

    assert first.character_id == second.character_id
    assert first.voice_profile_id == second.voice_profile_id
    assert updated is not None
    assert updated.name == "Elena Studio Updated"
    assert profile_count == len(profiles) == 2
    assert voice_count == len(voices) == 1
    assert voices[0].name == "Elena voice"
    assert voices[0].provider_voice_id == "voice-elena"
    assert character_count == len(characters) == 1
    assert characters[0].name == "Elena Updated"
