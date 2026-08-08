import json

import httpx
import pytest

from app.providers.render.comfyui import ComfyUIRenderer
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

    assert submission.external_job_id == "prompt-123"
    assert status.state == "completed"
    assert status.progress == 100
    assert outputs[0].filename == "final.mp4"


@pytest.mark.asyncio
async def test_comfyui_upload_returns_server_filename() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/upload/audio"
        assert b"audio.mp3" in request.content
        assert b"audio-bytes" in request.content
        return httpx.Response(200, json={"name": "audio.mp3", "subfolder": ""})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        renderer = ComfyUIRenderer(base_url="http://comfyui.test", client=client)
        filename = await renderer.upload("audio.mp3", b"audio-bytes", "audio")

    assert filename == "audio.mp3"
