from typing import Literal, Protocol

from pydantic import BaseModel, Field


class RendererCapabilities(BaseModel):
    supports_image: bool = False
    supports_audio: bool = False
    supports_native_lipsync: bool = False
    supports_seed: bool = False
    supports_fps: bool = False
    supports_duration: bool = False
    supports_negative_prompt: bool = False
    supports_camera_control: bool = False


class RenderRequest(BaseModel):
    workflow: dict[str, object]
    client_id: str | None = None


class RenderSubmission(BaseModel):
    provider: str
    external_job_id: str
    client_id: str | None = None


RenderState = Literal[
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
]


class RenderStatus(BaseModel):
    external_job_id: str
    state: RenderState
    progress: float | None = Field(default=None, ge=0, le=100)
    message: str | None = None


class RenderOutput(BaseModel):
    filename: str
    subfolder: str = ""
    output_type: str = ""
    media_type: str | None = None


class VideoRenderer(Protocol):
    async def submit(self, request: RenderRequest) -> RenderSubmission: ...

    async def get_status(self, external_job_id: str) -> RenderStatus: ...

    async def cancel(self, external_job_id: str) -> None: ...

    async def fetch_outputs(self, external_job_id: str) -> list[RenderOutput]: ...
