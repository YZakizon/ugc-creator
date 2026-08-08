import json
import os
from typing import Any

import httpx

from app.providers.llm.contracts import (
    LLMProvider,
    UGCContent,
    UGCContentRequest,
    UGCContentResult,
)


class LLMProviderError(RuntimeError):
    """Safe provider failure with no secret or raw response leakage."""


UGC_CONTENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "speech_script": {"type": "string"},
        "hook": {"type": "string"},
        "instagram": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
                "hashtags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "description", "hashtags"],
        },
        "tiktok": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
                "hashtags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "description", "hashtags"],
        },
    },
    "required": ["speech_script", "hook", "instagram", "tiktok"],
}


class OpenAIResponsesProvider(LLMProvider):
    default_prompt_template = (
        "You write conversational UGC scripts. Return content for Instagram and "
        "TikTok. Keep the speech natural and target about "
        "{{TARGET_DURATION_SECONDS}} seconds."
    )

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        client: httpx.AsyncClient | None = None,
        prompt_template: str | None = None,
        prompt_version: str | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model or os.getenv("OPENAI_MODEL") or "gpt-5.6"
        self.client = client
        self.prompt_template = (
            prompt_template
            or os.getenv("OPENAI_PROMPT_TEMPLATE")
            or self.default_prompt_template
        )
        self.prompt_version = (
            prompt_version or os.getenv("OPENAI_PROMPT_VERSION") or "ugc-v1"
        )

    async def generate_ugc_content(
        self, request: UGCContentRequest
    ) -> UGCContentResult:
        if not self.api_key:
            raise LLMProviderError("OpenAI is not configured on the server")

        payload = {
            "model": self.model,
            "input": [
                {
                    "role": "system",
                    "content": self.prompt_template.replace(
                        "{{TARGET_DURATION_SECONDS}}",
                        str(request.target_duration_seconds),
                    ),
                },
                {"role": "user", "content": f"Topic: {request.topic}"},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "ugc_content",
                    "strict": True,
                    "schema": UGC_CONTENT_SCHEMA,
                }
            },
            "store": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        if self.client is None:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    "https://api.openai.com/v1/responses",
                    headers=headers,
                    json=payload,
                )
        else:
            response = await self.client.post(
                "https://api.openai.com/v1/responses",
                headers=headers,
                json=payload,
            )

        if response.status_code >= 400:
            raise LLMProviderError(
                f"OpenAI request failed with status {response.status_code}"
            )

        try:
            response_data = response.json()
            output_text = response_data.get("output_text")
            if not output_text:
                output_text = _extract_output_text(response_data)
            content = UGCContent.model_validate(json.loads(output_text))
        except (ValueError, TypeError, KeyError) as exc:
            raise LLMProviderError(
                "OpenAI returned invalid structured content"
            ) from exc

        return UGCContentResult(
            content=content,
            provider="openai",
            model=self.model,
            prompt_version=self.prompt_version,
            request_id=response.headers.get("x-request-id"),
        )


def _extract_output_text(response_data: dict[str, Any]) -> str:
    for item in response_data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"}:
                text = content.get("text")
                if isinstance(text, str):
                    return text
    raise ValueError("No output text")
