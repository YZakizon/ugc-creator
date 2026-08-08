from typing import Protocol

from pydantic import BaseModel, Field


class PlatformMetadata(BaseModel):
    title: str
    description: str
    hashtags: list[str] = Field(min_length=1, max_length=20)


class UGCContent(BaseModel):
    speech_script: str = Field(min_length=1)
    hook: str = Field(min_length=1)
    instagram: PlatformMetadata
    tiktok: PlatformMetadata


class UGCContentRequest(BaseModel):
    topic: str = Field(min_length=1)
    target_duration_seconds: int = Field(ge=5, le=180)


class UGCContentResult(BaseModel):
    content: UGCContent
    provider: str
    model: str
    prompt_version: str
    request_id: str | None = None


class LLMProvider(Protocol):
    async def generate_ugc_content(
        self, request: UGCContentRequest
    ) -> UGCContentResult: ...
