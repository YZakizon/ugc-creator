import copy
from pathlib import Path

import httpx
import pytest

from app.main import app
from app.repositories import InMemoryBatchRepository, InMemoryConfigurationRepository
from app.services.workflow_service import (
    WorkflowValidationError,
    prepare_workflow,
)


def workflow_fixture() -> dict[str, object]:
    return {
        "1": {
            "class_type": "TextNode",
            "inputs": {"text": "Topic: {{TOPIC}}\nScript: {{SCRIPT}}"},
        },
        "2": {"class_type": "Sampler", "inputs": {"seed": 1}},
    }


def binding_fixture() -> list[dict[str, object]]:
    return [
        {
            "semantic_key": "video_prompt",
            "node_id": "1",
            "input_name": "text",
            "value_type": "template",
            "required": True,
        },
        {
            "semantic_key": "seed",
            "node_id": "2",
            "input_name": "seed",
            "value_type": "integer",
            "required": True,
        },
    ]


def test_prepare_workflow_deep_copies_and_applies_bindings() -> None:
    original = workflow_fixture()
    prepared = prepare_workflow(
        original,
        binding_fixture(),
        {
            "video_prompt": "A direct-to-camera delivery about {{TOPIC}}",
            "topic": "Morning routines",
            "script": "Start with one small habit.",
            "seed": 42,
        },
    )

    assert prepared is not original
    assert prepared["2"]["inputs"]["seed"] == 42  # type: ignore[index]
    assert "Morning routines" in prepared["1"]["inputs"]["text"]  # type: ignore[index]
    assert original == workflow_fixture()


def test_prepare_workflow_rejects_missing_binding_value() -> None:
    with pytest.raises(WorkflowValidationError, match="Missing required"):
        prepare_workflow(workflow_fixture(), binding_fixture(), {"seed": 42})


def test_prepare_workflow_rejects_unknown_placeholder() -> None:
    invalid_workflow = copy.deepcopy(workflow_fixture())
    invalid_workflow["1"]["inputs"]["text"] = "{{NOT_ALLOWED}}"  # type: ignore[index]
    with pytest.raises(WorkflowValidationError, match="Unknown workflow placeholder"):
        prepare_workflow(invalid_workflow, binding_fixture(), {})


def test_prepare_workflow_evaluates_audio_duration_offset_as_number() -> None:
    workflow = {
        "1": {
            "class_type": "PrimitiveFloat",
            "inputs": {"value": "{{AUDIO_DURATION + 1}}"},
        }
    }

    prepared = prepare_workflow(workflow, [], {"audio_duration": 12.25})

    assert prepared["1"]["inputs"]["value"] == 13.25  # type: ignore[index]


@pytest.mark.parametrize(
    "expression",
    ["{{AUDIO_DURATION * 2}}", "{{AUDIO_DURATION + __import__}}"],
)
def test_prepare_workflow_rejects_unsupported_audio_duration_expression(
    expression: str,
) -> None:
    workflow = {"1": {"class_type": "PrimitiveFloat", "inputs": {"value": expression}}}

    with pytest.raises(WorkflowValidationError, match="Unknown workflow placeholder"):
        prepare_workflow(workflow, [], {"audio_duration": 12.25})


def test_prepare_workflow_accepts_custom_provider_semantic_key() -> None:
    workflow = {"1": {"class_type": "Camera", "inputs": {"strength": 0.5}}}
    prepared = prepare_workflow(
        workflow,
        [
            {
                "semantic_key": "kling.camera_strength",
                "node_id": "1",
                "input_name": "strength",
                "value_type": "number",
                "required": True,
            }
        ],
        {"kling.camera_strength": 0.8},
    )

    assert prepared["1"]["inputs"]["strength"] == 0.8  # type: ignore[index]


@pytest.mark.asyncio
async def test_workflow_template_endpoint_validates_and_persists_bindings() -> None:
    app.state.batch_repository = InMemoryBatchRepository()
    app.state.configuration_repository = InMemoryConfigurationRepository()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/v1/workflow-templates",
            json={
                "name": "Shelf LTX API workflow",
                "workflow_json": workflow_fixture(),
                "bindings": binding_fixture(),
            },
        )
        listed = await client.get("/api/v1/workflow-templates")

    assert response.status_code == 201
    assert response.json()["renderer_provider"] == "comfyui"
    assert len(response.json()["bindings"]) == 2
    assert listed.status_code == 200
    assert listed.json()["total"] == 1


@pytest.mark.asyncio
async def test_workflow_media_endpoint_persists_durable_asset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MEDIA_STORAGE_ROOT", str(tmp_path))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/v1/workflow-media",
            json={
                "filename": "source.png",
                "content_base64": "aW1hZ2U=",
                "input_type": "image",
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "source.png"
    assert body["input_type"] == "image"
    assert body["asset_key"].startswith("workflow-media/")
    assert (tmp_path / body["asset_key"]).read_bytes() == b"image"


@pytest.mark.asyncio
async def test_workflow_template_can_be_deleted() -> None:
    app.state.batch_repository = InMemoryBatchRepository()
    app.state.configuration_repository = InMemoryConfigurationRepository()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        created = await client.post(
            "/api/v1/workflow-templates",
            json={"name": "Delete me", "workflow_json": workflow_fixture()},
        )
        template_id = created.json()["id"]
        deleted = await client.delete(f"/api/v1/workflow-templates/{template_id}")
        missing = await client.get(f"/api/v1/workflow-templates/{template_id}")

    assert created.status_code == 201
    assert deleted.status_code == 204
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_updated_workflow_can_be_deleted_without_reappearing() -> None:
    app.state.batch_repository = InMemoryBatchRepository()
    app.state.configuration_repository = InMemoryConfigurationRepository()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        created = await client.post(
            "/api/v1/workflow-templates",
            json={"name": "Delete lineage", "workflow_json": workflow_fixture()},
        )
        updated = await client.put(
            f"/api/v1/workflow-templates/{created.json()['id']}",
            json={"name": "Delete lineage", "workflow_json": workflow_fixture()},
        )
        deleted = await client.delete(
            f"/api/v1/workflow-templates/{updated.json()['id']}"
        )
        listed = await client.get("/api/v1/workflow-templates")

    assert deleted.status_code == 204
    assert listed.json()["total"] == 0


@pytest.mark.asyncio
async def test_workflow_template_edit_updates_same_record() -> None:
    app.state.batch_repository = InMemoryBatchRepository()
    app.state.configuration_repository = InMemoryConfigurationRepository()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        created = await client.post(
            "/api/v1/workflow-templates",
            json={"name": "Versioned workflow", "workflow_json": workflow_fixture()},
        )
        voice = await client.post(
            "/api/v1/voice-profiles",
            json={"name": "Voice", "provider": "elevenlabs", "provider_voice_id": "v1"},
        )
        character = await client.post(
            "/api/v1/characters",
            json={"name": "Character", "default_voice_profile_id": voice.json()["id"]},
        )
        await client.post(
            "/api/v1/render-profiles",
            json={
                "name": "Uses latest workflow",
                "character_id": character.json()["id"],
                "voice_profile_id": voice.json()["id"],
                "renderer_provider": "comfyui",
                "workflow_template_id": created.json()["id"],
            },
        )
        updated = await client.put(
            f"/api/v1/workflow-templates/{created.json()['id']}",
            json={
                "name": "Versioned workflow",
                "workflow_json": {
                    **workflow_fixture(),
                    "3": {"class_type": "TextNode", "inputs": {"text": "new"}},
                },
            },
        )
        listed = await client.get("/api/v1/workflow-templates")
        profiles = await client.get("/api/v1/render-profiles")

    assert created.status_code == 201
    assert updated.status_code == 200
    assert updated.json()["id"] == created.json()["id"]
    assert updated.json()["version"] == 2
    assert updated.json()["logical_id"] == created.json()["logical_id"]
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == created.json()["id"]
    assert profiles.json()["items"][0]["workflow_template_id"] == created.json()["id"]


@pytest.mark.asyncio
async def test_workflow_delete_is_blocked_when_profile_uses_it() -> None:
    app.state.batch_repository = InMemoryBatchRepository()
    app.state.configuration_repository = InMemoryConfigurationRepository()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        workflow = await client.post(
            "/api/v1/workflow-templates",
            json={"name": "In use", "workflow_json": workflow_fixture()},
        )
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
                "name": "Uses workflow",
                "character_id": character.json()["id"],
                "voice_profile_id": voice.json()["id"],
                "renderer_provider": "comfyui",
                "workflow_template_id": workflow.json()["id"],
            },
        )
        deleted = await client.delete(
            f"/api/v1/workflow-templates/{workflow.json()['id']}"
        )

    assert profile.status_code == 201
    assert deleted.status_code == 409


@pytest.mark.asyncio
async def test_render_profile_can_disconnect_workflow() -> None:
    app.state.batch_repository = InMemoryBatchRepository()
    app.state.configuration_repository = InMemoryConfigurationRepository()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        workflow = await client.post(
            "/api/v1/workflow-templates",
            json={"name": "Disconnectable", "workflow_json": workflow_fixture()},
        )
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
                "name": "Connected profile",
                "character_id": character.json()["id"],
                "voice_profile_id": voice.json()["id"],
                "renderer_provider": "comfyui",
                "workflow_template_id": workflow.json()["id"],
            },
        )
        disconnected = await client.patch(
            f"/api/v1/render-profiles/{profile.json()['id']}",
            json={"name": "Connected profile", "workflow_template_id": None},
        )

    assert profile.status_code == 201
    assert disconnected.status_code == 200
    assert disconnected.json()["workflow_template_id"] is None
