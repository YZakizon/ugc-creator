from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.repositories import (
    InMemoryBatchRepository,
    InMemoryConfigurationRepository,
    SqlAlchemyBatchRepository,
    SqlAlchemyConfigurationRepository,
    utc_now,
)
from app.schemas import (
    BatchCreate,
    RenderProfileSetupCreate,
    RenderProfileUpdate,
    VoiceProfileCreate,
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
        created = await client.post(
            f"/api/v1/voice-profiles/{voice.json()['id']}/previews",
            json={"text": "This is a speech preview."},
        )
        preview = repository.voice_previews[next(iter(repository.voice_previews))]
        preview.status = "completed"
        preview.asset_key = f"voice-previews/{preview.id}/speech.mp3"
        preview.content_type = "audio/mpeg"
        preview.filename = "preview.mp3"
        (tmp_path / preview.asset_key).parent.mkdir(parents=True)
        (tmp_path / preview.asset_key).write_bytes(b"ID3preview")
        polled = await client.get(f"/api/v1/voice-previews/{preview.id}")
        audio = await client.get(f"/api/v1/voice-previews/{preview.id}/audio")

    assert created.status_code == 202
    assert created.json()["status"] == "queued"
    assert queued == [created.json()["id"]]
    assert polled.json()["download_url"].endswith(f"/{preview.id}/audio")
    assert audio.status_code == 200
    assert audio.content == b"ID3preview"
    assert audio.headers["content-type"] == "audio/mpeg"


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
