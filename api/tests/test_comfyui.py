import json

import httpx
import pytest

from app.providers.render.comfyui import (
    ComfyUIProviderError,
    ComfyUIRenderer,
    ComfyUISubmissionOutcomeUnknown,
    _progress_from_message,
    _websocket_url,
)
from app.providers.render.comfyui_controls import rendered_ltx_controls
from app.providers.render.contracts import RenderRequest


@pytest.mark.asyncio
async def test_comfyui_submit_status_and_outputs() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/prompt":
            payload = json.loads(request.content)
            assert payload["prompt"]["1"]["class_type"] == "TextNode"
            return httpx.Response(200, json={"prompt_id": "prompt-123"})
        if request.url.path == "/history/prompt-123":
            return httpx.Response(
                200,
                json={
                    "prompt-123": {
                        "status": {"status_str": "success"},
                        "outputs": {
                            "7": {
                                "videos": [
                                    {
                                        "filename": "final.mp4",
                                        "subfolder": "",
                                        "type": "output",
                                    }
                                ]
                            }
                        },
                    }
                },
            )
        if request.url.path == "/view":
            assert request.url.params["filename"] == "final.mp4"
            return httpx.Response(
                200, content=b"video-bytes", headers={"content-type": "video/mp4"}
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        renderer = ComfyUIRenderer(
            base_url="http://comfyui.test", client=client, client_id="client-1"
        )
        submission = await renderer.submit(
            RenderRequest(workflow={"1": {"class_type": "TextNode"}})
        )
        status = await renderer.get_status(submission.external_job_id)
        outputs = await renderer.fetch_outputs(submission.external_job_id)
        content, content_type = await renderer.download_output(outputs[0])

    assert submission.external_job_id == "prompt-123"
    assert status.state == "completed"
    assert status.progress == 100
    assert outputs[0].filename == "final.mp4"
    assert content == b"video-bytes"
    assert content_type == "video/mp4"


def test_rendered_ltx_controls_use_prepared_workflow_values() -> None:
    workflow = {
        "image": {
            "class_type": "LoadImage",
            "inputs": {"image": "attempt-image.png"},
        },
        "audio": {
            "class_type": "LoadAudio",
            "inputs": {"audio": "attempt-audio.mp3"},
        },
        "prompt": {
            "_meta": {"title": "Prompt"},
            "class_type": "PrimitiveStringMultiline",
            "inputs": {"value": 'Elena says: "Expanded script"'},
        },
        "fps": {
            "_meta": {"title": "Frame Rate"},
            "class_type": "PrimitiveInt",
            "inputs": {"value": 30},
        },
        "duration": {
            "_meta": {"title": "Duration"},
            "class_type": "PrimitiveFloat",
            "inputs": {"value": 25.5},
        },
        "seed": {
            "class_type": "RandomNoise",
            "inputs": {"noise_seed": 987654},
        },
        "sigmas": {
            "class_type": "ManualSigmas",
            "inputs": {"sigmas": "1.0, 0.5, 0.0"},
        },
        "sampler": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {"noise": ["seed", 0], "sigmas": ["sigmas", 0]},
        },
        "width": {
            "_meta": {"title": "Width"},
            "class_type": "PrimitiveInt",
            "inputs": {"value": 576},
        },
        "height": {
            "_meta": {"title": "Height"},
            "class_type": "PrimitiveInt",
            "inputs": {"value": 1024},
        },
    }

    assert rendered_ltx_controls(workflow) == [
        {
            "label": "Image source",
            "node_id": "image",
            "input_name": "image",
            "value": "attempt-image.png",
        },
        {
            "label": "Audio source",
            "node_id": "audio",
            "input_name": "audio",
            "value": "attempt-audio.mp3",
        },
        {
            "label": "Prompt",
            "node_id": "prompt",
            "input_name": "value",
            "value": 'Elena says: "Expanded script"',
        },
        {"label": "FPS", "node_id": "fps", "input_name": "value", "value": 30},
        {
            "label": "Duration",
            "node_id": "duration",
            "input_name": "value",
            "value": 25.5,
        },
        {
            "label": "Seed",
            "node_id": "seed",
            "input_name": "noise_seed",
            "value": 987654,
        },
        {"label": "Width", "node_id": "width", "input_name": "value", "value": 576},
        {"label": "Height", "node_id": "height", "input_name": "value", "value": 1024},
    ]


@pytest.mark.asyncio
async def test_comfyui_upload_returns_server_filename() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/upload/image"
        assert b"audio.mp3" in request.content
        assert b"audio-bytes" in request.content
        assert b'name="type"' in request.content
        assert b"input" in request.content
        return httpx.Response(200, json={"name": "audio.mp3", "subfolder": ""})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        renderer = ComfyUIRenderer(base_url="http://comfyui.test", client=client)
        filename = await renderer.upload("audio.mp3", b"audio-bytes", "audio")

    assert filename == "audio.mp3"


@pytest.mark.asyncio
async def test_comfyui_history_polling_reports_indeterminate_progress() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "prompt-1": {
                    "status": {
                        "status_str": "running",
                        "messages": [["progress", {"value": 7, "max": 10}]],
                    }
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        status = await ComfyUIRenderer(
            base_url="http://comfyui.test", client=client
        ).get_status("prompt-1")

    assert status.state == "running"
    assert status.progress is None


def test_comfyui_builds_prompt_progress_websocket_url() -> None:
    assert _websocket_url("http://comfyui.test:8188", "client one") == (
        "ws://comfyui.test:8188/ws?clientId=client+one"
    )
    assert _websocket_url("https://render.test/comfy", "client-2") == (
        "wss://render.test/comfy/ws?clientId=client-2"
    )


def test_comfyui_parses_prompt_scoped_progress_percentage() -> None:
    assert (
        _progress_from_message(
            json.dumps(
                {
                    "type": "progress",
                    "data": {"value": 17, "max": 20, "prompt_id": "prompt-1"},
                }
            ),
            "prompt-1",
        )
        == 85
    )
    assert (
        _progress_from_message(
            json.dumps(
                {
                    "type": "progress",
                    "data": {"value": 17, "max": 20, "prompt_id": "another"},
                }
            ),
            "prompt-1",
        )
        is None
    )
    assert _progress_from_message("not-json", "prompt-1") is None


@pytest.mark.asyncio
async def test_comfyui_reconciles_submission_by_persisted_client_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/queue":
            return httpx.Response(
                200,
                json={
                    "queue_running": [],
                    "queue_pending": [
                        [1, "prompt-queued", {}, {"client_id": "attempt-client"}]
                    ],
                },
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        renderer = ComfyUIRenderer(base_url="http://comfyui.test", client=client)
        prompt_id = await renderer.find_submission("attempt-client")

    assert prompt_id == "prompt-queued"


@pytest.mark.asyncio
async def test_comfyui_lost_submit_response_has_unknown_outcome() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/prompt"
        raise httpx.ReadTimeout(
            "response lost after prompt acceptance", request=request
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        renderer = ComfyUIRenderer(base_url="http://comfyui.test", client=client)
        with pytest.raises(
            ComfyUISubmissionOutcomeUnknown, match="submission outcome is unknown"
        ):
            await renderer.submit(
                RenderRequest(
                    workflow={"1": {"class_type": "TextNode"}},
                    client_id="durable-client-id",
                )
            )


@pytest.mark.asyncio
async def test_comfyui_rejected_submit_is_a_known_failure() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/prompt"
        return httpx.Response(400, json={"error": "invalid workflow"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        renderer = ComfyUIRenderer(base_url="http://comfyui.test", client=client)
        with pytest.raises(ComfyUIProviderError, match="status 400") as error:
            await renderer.submit(
                RenderRequest(workflow={"1": {"class_type": "TextNode"}})
            )

    assert not isinstance(error.value, ComfyUISubmissionOutcomeUnknown)
