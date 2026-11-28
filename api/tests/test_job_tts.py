from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.statuses import JobStatus
from app.db.base import Base
from app.db.models import (
    Batch,
    Character,
    MediaAsset,
    RenderAttempt,
    RenderNode,
    RenderProfile,
    TopicJob,
    VoiceProfile,
    WorkflowTemplate,
)
from app.job_tts_repository import JobTTSRepository
from app.main import app
from app.providers.tts.fake import FakeTTSProvider
from app.render_repository import RenderExecutionRepository
from app.repositories import (
    InMemoryBatchRepository,
    InMemoryConfigurationRepository,
    SqlAlchemyBatchRepository,
)
from app.schemas import BatchCreate
from app.workers import tts_tasks


@pytest.mark.asyncio
async def test_job_tts_endpoint_queues_content_ready_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UGC_FAKE_PROVIDERS", "1")
    batches = InMemoryBatchRepository()
    config = InMemoryConfigurationRepository()
    voice = VoiceProfile(
        id=uuid4(),
        name="Hope",
        provider="elevenlabs",
        provider_voice_id="voice-hope",
    )
    character = Character(id=uuid4(), name="Elena", slug="elena")
    profile = RenderProfile(
        id=uuid4(),
        name="Elena LTX",
        character_id=character.id,
        voice_profile_id=voice.id,
        renderer_provider="comfyui",
    )
    config.voice_profiles[voice.id] = voice
    config.characters[character.id] = character
    config.render_profiles[profile.id] = profile
    batch = batches.create_batch(
        BatchCreate(
            name="Topics",
            topics=["A topic"],
            default_render_profile_id=profile.id,
        )
    )
    job = batch.jobs[0]
    job.status = JobStatus.CONTENT_READY.value
    job.speech_script = "Generated content"
    queued: list[str] = []
    monkeypatch.setattr("app.api.routes.generate_job_tts.delay", queued.append)
    app.state.batch_repository = batches
    app.state.configuration_repository = config

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(f"/api/v1/jobs/{job.id}/generate-tts")

    assert response.status_code == 202
    assert response.json()["status"] == JobStatus.GENERATING_TTS.value
    assert queued == [str(job.id)]


@pytest.mark.asyncio
async def test_job_tts_enqueue_failure_keeps_existing_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UGC_FAKE_PROVIDERS", "1")
    batches = InMemoryBatchRepository()
    config = InMemoryConfigurationRepository()
    voice = VoiceProfile(
        id=uuid4(),
        name="Hope",
        provider="elevenlabs",
        provider_voice_id="voice-hope",
    )
    character = Character(id=uuid4(), name="Elena", slug="enqueue-elena")
    profile = RenderProfile(
        id=uuid4(),
        name="Elena LTX",
        character_id=character.id,
        voice_profile_id=voice.id,
        renderer_provider="comfyui",
    )
    config.voice_profiles[voice.id] = voice
    config.characters[character.id] = character
    config.render_profiles[profile.id] = profile
    topic = batches.create_batch(
        BatchCreate(
            name="Topic",
            topics=["A topic"],
            default_render_profile_id=profile.id,
        )
    )
    job = topic.jobs[0]
    job.status = JobStatus.READY_TO_RENDER.value
    job.speech_script = "Generated content"
    job.media_assets = [
        MediaAsset(
            id=uuid4(),
            job_id=job.id,
            kind="audio",
            object_key="audio/original.mp3",
            filename="original.mp3",
            content_type="audio/mpeg",
            size_bytes=5,
        )
    ]
    monkeypatch.setattr(
        "app.api.routes.generate_job_tts.delay",
        lambda _job_id: (_ for _ in ()).throw(RuntimeError("Redis unavailable")),
    )
    app.state.batch_repository = batches
    app.state.configuration_repository = config

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(f"/api/v1/jobs/{job.id}/generate-tts")

    assert response.status_code == 503
    assert response.json()["detail"]["message"].endswith("current audio was kept.")
    assert job.status == JobStatus.READY_TO_RENDER.value
    assert job.media_assets[0].kind == "audio"


def test_job_tts_uses_profile_voice_and_persists_render_audio(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        voice = VoiceProfile(
            name="Hope",
            provider="elevenlabs",
            provider_voice_id="voice-hope",
            provider_model="eleven_multilingual_v2",
            speed=1.1,
            stability=0.4,
            similarity=0.8,
            style_exaggeration=0.5,
        )
        character = Character(name="Elena", slug="elena")
        session.add_all([voice, character])
        session.flush()
        profile = RenderProfile(
            name="Elena LTX",
            character_id=character.id,
            voice_profile_id=voice.id,
            renderer_provider="comfyui",
        )
        batch = Batch(name="Batch")
        session.add_all([profile, batch])
        session.flush()
        job = TopicJob(
            batch_id=batch.id,
            topic="A topic",
            status=JobStatus.GENERATING_TTS.value,
            render_profile_id=profile.id,
            speech_script="This is the generated speech.",
        )
        session.add(job)
        session.commit()
        job_id = job.id

    monkeypatch.setattr(tts_tasks, "create_database_engine", lambda: engine)
    monkeypatch.setattr(tts_tasks, "tts_provider", lambda _provider: FakeTTSProvider())
    monkeypatch.setattr(
        tts_tasks, "probe_audio_duration", lambda _audio, _filename: 2.0
    )
    monkeypatch.setenv("MEDIA_STORAGE_ROOT", str(tmp_path))

    result = tts_tasks.generate_job_tts.run(str(job_id))

    assert result["status"] == JobStatus.READY_TO_RENDER.value
    with factory() as session:
        saved = session.get(TopicJob, job_id)
        asset = session.scalar(
            select(MediaAsset).where(
                MediaAsset.job_id == job_id, MediaAsset.kind == "audio"
            )
        )
        assert saved is not None
        assert saved.tts_voice_id == "voice-hope"
        assert saved.tts_model == "eleven_multilingual_v2"
        assert saved.tts_settings == {
            "speed": 1.1,
            "stability": 0.4,
            "similarity_boost": 0.8,
            "style": 0.5,
            "output_format": "mp3_44100_128",
            "language_code": None,
        }
        assert asset is not None
        assert asset.generation_metadata is not None
        assert asset.generation_metadata["provider"] == "elevenlabs"
        assert asset.generation_metadata["voice_id"] == "voice-hope"
        assert asset.generation_metadata["voice_name"] == "Hope"
        assert asset.generation_metadata["model"] == "eleven_multilingual_v2"
        assert asset.generation_metadata["settings"] == saved.tts_settings
        assert isinstance(asset.generation_metadata["duration_seconds"], float)
        assert asset.generation_metadata["duration_seconds"] > 0
        assert len(str(asset.generation_metadata["script_sha256"])) == 64
        assert asset.content_type == "audio/wav"
        assert (tmp_path / asset.object_key).read_bytes().startswith(b"RIFF")


def test_job_tts_uses_job_voice_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        profile_voice = VoiceProfile(
            name="Profile voice", provider="elevenlabs", provider_voice_id="profile"
        )
        job_voice = VoiceProfile(
            name="Job voice", provider="elevenlabs", provider_voice_id="override"
        )
        character = Character(name="Elena", slug="override-elena")
        session.add_all([profile_voice, job_voice, character])
        session.flush()
        profile = RenderProfile(
            name="Profile",
            character_id=character.id,
            voice_profile_id=profile_voice.id,
            renderer_provider="comfyui",
        )
        batch = Batch(name="Batch")
        session.add_all([profile, batch])
        session.flush()
        job = TopicJob(
            batch_id=batch.id,
            topic="Topic",
            status=JobStatus.GENERATING_TTS.value,
            render_profile_id=profile.id,
            voice_profile_id=job_voice.id,
            speech_script="Override this voice.",
        )
        session.add(job)
        session.commit()
        job_id = job.id

    monkeypatch.setattr(tts_tasks, "create_database_engine", lambda: engine)
    monkeypatch.setattr(tts_tasks, "tts_provider", lambda _provider: FakeTTSProvider())
    monkeypatch.setattr(
        tts_tasks, "probe_audio_duration", lambda _audio, _filename: 2.0
    )
    monkeypatch.setenv("MEDIA_STORAGE_ROOT", str(tmp_path))

    tts_tasks.generate_job_tts.run(str(job_id))

    with factory() as session:
        saved = session.get(TopicJob, job_id)
        assert saved is not None
        assert saved.tts_voice_id == "override"


def test_stale_paid_tts_claim_requires_manual_retry() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        batch = Batch(name="Batch")
        session.add(batch)
        session.flush()
        job = TopicJob(
            batch_id=batch.id,
            topic="A topic",
            status=JobStatus.GENERATING_TTS.value,
            speech_script="Speech",
            tts_claim_token=uuid4(),
        )
        session.add(job)
        session.commit()
        job_id = job.id

    assert JobTTSRepository(factory).claim(job_id) is None
    with factory() as session:
        saved = session.get(TopicJob, job_id)
        assert saved is not None
        assert saved.status == JobStatus.FAILED.value
        assert "outcome is unknown" in (saved.error_message or "")


def test_failed_tts_replacement_preserves_current_audio() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        voice = VoiceProfile(
            name="Hope", provider="elevenlabs", provider_voice_id="voice-hope"
        )
        character = Character(name="Elena", slug="replacement-elena")
        session.add_all([voice, character])
        session.flush()
        profile = RenderProfile(
            name="Profile",
            character_id=character.id,
            voice_profile_id=voice.id,
            renderer_provider="comfyui",
        )
        batch = Batch(name="Topic")
        session.add_all([profile, batch])
        session.flush()
        job = TopicJob(
            batch_id=batch.id,
            topic="A topic",
            status=JobStatus.GENERATING_TTS.value,
            render_profile_id=profile.id,
            speech_script="Generate a replacement.",
        )
        session.add(job)
        session.flush()
        original = MediaAsset(
            job_id=job.id,
            kind="audio",
            object_key="audio/original.mp3",
            filename="original.mp3",
            content_type="audio/mpeg",
            size_bytes=5,
        )
        session.add(original)
        session.commit()
        job_id = job.id

    repository = JobTTSRepository(factory)
    context = repository.claim(job_id)
    assert context is not None
    repository.fail(context, "Provider unavailable", None)

    with factory() as session:
        saved = session.get(TopicJob, job_id)
        active_audio = session.scalar(
            select(MediaAsset).where(
                MediaAsset.job_id == job_id, MediaAsset.kind == "audio"
            )
        )
        assert saved is not None
        assert saved.status == JobStatus.READY_TO_RENDER.value
        assert saved.error_message == "Provider unavailable"
        assert active_audio is not None
        assert active_audio.filename == "original.mp3"


@pytest.mark.parametrize(
    "outcome", ["speech_first", "render_first", "speech_failed", "both_failed"]
)
def test_created_video_speech_and_render_finish_independently(
    outcome: str,
) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        profile = RenderProfile(
            name="Profile",
            character=Character(name="Elena", slug="elena"),
            voice_profile=VoiceProfile(
                name="Hope", provider="elevenlabs", provider_voice_id="hope"
            ),
            renderer_provider="comfyui",
        )
        node = RenderNode(name="Local", base_url="http://comfyui:8188")
        workflow = WorkflowTemplate(
            name="LTX",
            renderer_provider="comfyui",
            checksum="original",
            workflow_json={},
        )
        session.add_all([profile, node, workflow])
        session.flush()
        job = TopicJob(
            batch=Batch(name="Created Video", creation_mode="created_video"),
            topic="Elena",
            speech_script="Current speech",
            render_profile_id=profile.id,
            status=JobStatus.RENDERING.value,
            media_assets=[
                MediaAsset(
                    kind="audio",
                    object_key="original.mp3",
                    filename="original.mp3",
                    size_bytes=1,
                )
            ],
        )
        attempt = RenderAttempt(
            job=job,
            render_profile_id=profile.id,
            render_node_id=node.id,
            workflow_template_id=workflow.id,
            status="rendering",
            provider="comfyui",
            external_job_id="prompt",
            effective_values={
                "requested_inputs": {"audio": {"object_key": "original.mp3"}}
            },
        )
        session.add(attempt)
        session.commit()
        job_id, attempt_id, audio_id = job.id, attempt.id, job.media_assets[0].id

    batches = SqlAlchemyBatchRepository(factory)
    tts = JobTTSRepository(factory)
    renders = RenderExecutionRepository(factory)
    assert batches.update_job_voice_profile(job_id, profile.voice_profile_id)
    assert batches.update_job_script(job_id, "Replacement speech")
    assert batches.queue_job_for_tts(job_id)
    with pytest.raises(ValueError, match="cannot be deleted"):
        batches.delete_job_audio_asset(audio_id)
    assert renders.update_progress(attempt_id, "rendering", 40)
    context = tts.claim(job_id)
    assert context is not None
    assert context.speech_script == "Replacement speech"
    assert tts.claim(job_id) is None

    if outcome in {"speech_failed", "both_failed"}:
        tts.fail(context, "Replacement audio failed", None)
        assert renders.update_progress(attempt_id, "rendering", 60)
        job_after_progress = batches.get_job(job_id)
        assert job_after_progress is not None
        assert job_after_progress.status == JobStatus.RENDERING.value
        assert job_after_progress.error_message == "Replacement audio failed"
        render_failed = outcome == "both_failed"
        terminal = JobStatus.FAILED if render_failed else JobStatus.COMPLETED
        render_error = "ComfyUI ran out of GPU memory" if render_failed else None
        assert renders.update_progress(attempt_id, terminal.value, 100, render_error)
        job_after_render = batches.get_job(job_id)
        assert job_after_render is not None
        assert job_after_render.status == terminal.value
        assert job_after_render.error_message == "Replacement audio failed"
        saved_attempt = renders.get_attempt(attempt_id)
        assert saved_attempt is not None and saved_attempt.error_message == render_error
        return

    if outcome == "render_first":
        assert renders.update_progress(attempt_id, "completed", 100)
        assert batches.get_job(job_id).status == JobStatus.GENERATING_TTS.value

    saved = tts.complete(
        context,
        provider_request_id="speech",
        model_id="test",
        settings={},
        object_key="replacement.mp3",
        filename="replacement.mp3",
        content_type="audio/mpeg",
        size_bytes=1,
    )
    assert saved is not None
    if outcome == "speech_first":
        assert saved.status == JobStatus.RENDERING.value
        with pytest.raises(ValueError, match="cannot be deleted"):
            batches.delete_job_audio_asset(audio_id)
        assert tts.claim(job_id) is None
        assert renders.update_progress(attempt_id, "completed", 100)
    else:
        assert saved.status == JobStatus.READY_TO_RENDER.value
    assert renders.get_attempt(attempt_id).effective_values == attempt.effective_values
    assert batches.delete_job_audio_asset(audio_id) is not None
