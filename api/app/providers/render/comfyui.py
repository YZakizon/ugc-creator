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


class ComfyUISubmissionOutcomeUnknown(ComfyUIProviderError):
    """The prompt may have been accepted, so submission must be reconciled."""


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
            outcome_unknown_on_transport_error=True,
        )
        try:
            payload = _json_object(response)
        except ComfyUIProviderError as exc:
            raise ComfyUISubmissionOutcomeUnknown(
                "ComfyUI submission outcome is unknown"
            ) from exc
        prompt_id = payload.get("prompt_id")
        if not isinstance(prompt_id, str) or not prompt_id:
            raise ComfyUISubmissionOutcomeUnknown(
                "ComfyUI submission outcome is unknown"
            )
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
                    message="ComfyUI reported a workflow error",
                )
        return RenderStatus(
            external_job_id=external_job_id,
            state="running",
        )

    async def find_submission(self, client_id: str) -> str | None:
        queue = _json_object(await self._request("GET", "/queue"))
        prompt_id = _find_client_prompt_in_queue(queue, client_id)
        if prompt_id is not None:
            return prompt_id
        history = _json_object(
            await self._request("GET", "/history", params={"max_items": "100"})
        )
        return _find_client_prompt_in_history(history, client_id)

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
            "/upload/image",
            files={"image": (filename, content)},
            data={
                "overwrite": str(overwrite).lower(),
                "type": "input",
            },
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
        outcome_unknown_on_transport_error: bool = False,
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
            if outcome_unknown_on_transport_error:
                raise ComfyUISubmissionOutcomeUnknown(
                    "ComfyUI submission outcome is unknown"
                ) from exc
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
                        media_type=(
                            "video" if output_type in {"videos", "gifs"} else "image"
                        ),
                    )
                )
    return discovered


def _find_client_prompt_in_queue(
    payload: Mapping[str, object], client_id: str
) -> str | None:
    for queue_name in ("queue_running", "queue_pending"):
        entries = payload.get(queue_name)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            prompt_id = _prompt_record_client_match(entry, client_id)
            if prompt_id is not None:
                return prompt_id
    return None


def _find_client_prompt_in_history(
    payload: Mapping[str, object], client_id: str
) -> str | None:
    for key, value in payload.items():
        if not isinstance(value, dict):
            continue
        prompt_id = _prompt_record_client_match(value.get("prompt"), client_id)
        if prompt_id is not None:
            return prompt_id
        extra_data = value.get("extra_data")
        if isinstance(extra_data, dict) and extra_data.get("client_id") == client_id:
            return key
    return None


def _prompt_record_client_match(record: object, client_id: str) -> str | None:
    if not isinstance(record, list) or len(record) < 4:
        return None
    prompt_id = record[1]
    extra_data = record[3]
    if (
        isinstance(prompt_id, str)
        and isinstance(extra_data, dict)
        and extra_data.get("client_id") == client_id
    ):
        return prompt_id
    return None
