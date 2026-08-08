import os
from collections.abc import Mapping
from uuid import uuid4

import httpx

from app.core.urls import validate_render_node_url
from app.providers.render.contracts import (
    RenderOutput,
    RenderRequest,
    RenderStatus,
    RenderSubmission,
    VideoRenderer,
)


class ComfyUIProviderError(RuntimeError):
    """Safe ComfyUI failure without returning response bodies or credentials."""


class ComfyUIRenderer(VideoRenderer):
    def __init__(
        self,
        base_url: str | None = None,
        client: httpx.AsyncClient | None = None,
        client_id: str | None = None,
    ) -> None:
        self.base_url = validate_render_node_url(
            base_url or os.getenv("COMFYUI_BASE_URL") or "http://localhost:8188",
            resolve_dns=False,
        )
        self.client = client
        self.client_id = client_id or str(uuid4())

    async def health_check(self) -> bool:
        response = await self._request("GET", "/system_stats")
        return response.is_success

    async def submit(self, request: RenderRequest) -> RenderSubmission:
        response = await self._request(
            "POST",
            "/prompt",
            json_body={
                "prompt": request.workflow,
                "client_id": request.client_id or self.client_id,
            },
        )
        payload = _json_object(response)
        prompt_id = payload.get("prompt_id")
        if not isinstance(prompt_id, str) or not prompt_id:
            raise ComfyUIProviderError("ComfyUI returned no prompt ID")
        return RenderSubmission(
            provider="comfyui",
            external_job_id=prompt_id,
            client_id=request.client_id or self.client_id,
        )

    async def get_status(self, external_job_id: str) -> RenderStatus:
        response = await self._request("GET", f"/history/{external_job_id}")
        payload = _json_object(response)
        history = payload.get(external_job_id)
        if not isinstance(history, dict):
            return RenderStatus(external_job_id=external_job_id, state="queued")

        status = history.get("status")
        progress = _extract_progress(history)
        if isinstance(status, dict):
            status_string = status.get("status_str")
            if status_string == "success":
                return RenderStatus(
                    external_job_id=external_job_id,
                    state="completed",
                    progress=100,
                )
            if status_string == "error":
                return RenderStatus(
                    external_job_id=external_job_id,
                    state="failed",
                    progress=progress,
                    message="ComfyUI reported a workflow error",
                )
        return RenderStatus(
            external_job_id=external_job_id,
            state="running",
            progress=progress,
        )

    async def cancel(self, external_job_id: str) -> None:
        del external_job_id  # ComfyUI's interrupt endpoint is process-wide.
        await self._request("POST", "/interrupt", json_body={})

    async def fetch_outputs(self, external_job_id: str) -> list[RenderOutput]:
        response = await self._request("GET", f"/history/{external_job_id}")
        payload = _json_object(response)
        history = payload.get(external_job_id)
        if not isinstance(history, dict):
            return []
        outputs = history.get("outputs")
        if not isinstance(outputs, dict):
            return []
        return _extract_outputs(outputs)

    async def download_output(self, output: RenderOutput) -> tuple[bytes, str | None]:
        response = await self._request(
            "GET",
            "/view",
            params={
                "filename": output.filename,
                "subfolder": output.subfolder,
                "type": output.output_type or "output",
            },
        )
        return response.content, response.headers.get("content-type")

    async def upload(
        self,
        filename: str,
        content: bytes,
        input_type: str = "image",
        overwrite: bool = False,
    ) -> str:
        if input_type not in {"image", "audio"}:
            raise ComfyUIProviderError(f"Unsupported ComfyUI upload type: {input_type}")
        response = await self._request(
            "POST",
            f"/upload/{input_type}",
            files={"image": (filename, content)},
            data={"overwrite": str(overwrite).lower()},
        )
        payload = _json_object(response)
        uploaded_name = payload.get("name")
        if not isinstance(uploaded_name, str) or not uploaded_name:
            raise ComfyUIProviderError("ComfyUI returned no uploaded filename")
        return uploaded_name

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, object] | None = None,
        files: Mapping[str, tuple[str, bytes]] | None = None,
        data: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        try:
            if self.client is None:
                validate_render_node_url(self.base_url)
                async with httpx.AsyncClient(timeout=60) as client:
                    response = await client.request(
                        method,
                        f"{self.base_url}{path}",
                        json=json_body,
                        files=files,
                        data=data,
                        params=params,
                    )
            else:
                response = await self.client.request(
                    method,
                    f"{self.base_url}{path}",
                    json=json_body,
                    files=files,
                    data=data,
                    params=params,
                )
        except httpx.HTTPError as exc:
            raise ComfyUIProviderError("ComfyUI is unavailable") from exc
        if response.status_code >= 400:
            raise ComfyUIProviderError(
                f"ComfyUI request failed with status {response.status_code}"
            )
        return response


def _json_object(response: httpx.Response) -> dict[str, object]:
    try:
        payload = response.json()
    except (ValueError, TypeError) as exc:
        raise ComfyUIProviderError("ComfyUI returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ComfyUIProviderError("ComfyUI returned an invalid response")
    return payload


def _extract_outputs(outputs: Mapping[str, object]) -> list[RenderOutput]:
    discovered: list[RenderOutput] = []
    for output in outputs.values():
        if not isinstance(output, dict):
            continue
        for output_type in ("videos", "gifs", "images"):
            items = output.get(output_type)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                filename = item.get("filename")
                if not isinstance(filename, str) or not filename:
                    continue
                subfolder = item.get("subfolder", "")
                item_type = item.get("type", "")
                discovered.append(
                    RenderOutput(
                        filename=filename,
                        subfolder=subfolder if isinstance(subfolder, str) else "",
                        output_type=item_type if isinstance(item_type, str) else "",
                    )
                )
    return discovered


def _extract_progress(history: Mapping[str, object]) -> float:
    direct = history.get("progress")
    if isinstance(direct, (int, float)) and not isinstance(direct, bool):
        return max(0, min(100, float(direct)))
    status = history.get("status")
    if not isinstance(status, dict):
        return 0
    status_progress = status.get("progress")
    if isinstance(status_progress, (int, float)) and not isinstance(
        status_progress, bool
    ):
        return max(0, min(100, float(status_progress)))
    messages = status.get("messages")
    if not isinstance(messages, list):
        return 0
    for message in reversed(messages):
        if (
            isinstance(message, list)
            and len(message) >= 2
            and message[0] == "progress"
            and isinstance(message[1], dict)
        ):
            value = message[1].get("value")
            maximum = message[1].get("max")
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and isinstance(maximum, (int, float))
                and not isinstance(maximum, bool)
                and maximum > 0
            ):
                return max(0, min(100, float(value) / float(maximum) * 100))
    return 0
