import os

import httpx

from app.providers.tts.contracts import (
    TTSProviderError,
    TTSProviderOutcomeUnknown,
    TTSRequest,
    TTSResult,
    TTSUsage,
    TTSVoice,
)

SUPPORTED_OUTPUT_FORMATS = {
    "mp3_44100_128": ("audio/mpeg", "mp3"),
    "mp3_44100_192": ("audio/mpeg", "mp3"),
    "pcm_44100": ("audio/pcm", "pcm"),
    "wav_44100": ("audio/wav", "wav"),
}


class ElevenLabsTTSProvider:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.elevenlabs.io",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("ELEVENLABS_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.transport = transport

    async def synthesize(self, request: TTSRequest) -> TTSResult:
        if not self.api_key:
            raise TTSProviderError(
                "ElevenLabs is not configured. Set ELEVENLABS_API_KEY on the worker.",
                category="provider_auth_error",
                retriable=False,
            )
        output = SUPPORTED_OUTPUT_FORMATS.get(request.output_format)
        if output is None:
            raise TTSProviderError(
                "The selected ElevenLabs output format is not supported.",
                category="validation_error",
                retriable=False,
            )
        payload: dict[str, object] = {
            "text": request.text,
            "model_id": request.model_id,
            "voice_settings": request.voice_settings,
        }
        if request.language_code:
            payload["language_code"] = request.language_code
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(90),
                transport=self.transport,
            ) as client:
                response = await client.post(
                    f"/v1/text-to-speech/{request.voice_id}",
                    params={"output_format": request.output_format},
                    headers={"xi-api-key": self.api_key},
                    json=payload,
                )
                usage = (
                    await self._get_usage(client, response)
                    if not response.is_error
                    else None
                )
        except (httpx.ConnectTimeout, httpx.ConnectError) as exc:
            raise TTSProviderError(
                "ElevenLabs is temporarily unreachable.",
                category="provider_timeout"
                if isinstance(exc, httpx.ConnectTimeout)
                else "provider_unavailable",
                retriable=True,
            ) from exc
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise TTSProviderOutcomeUnknown(
                "ElevenLabs may have accepted the speech request, but its response "
                "was lost. It was not retried automatically.",
                category="provider_timeout"
                if isinstance(exc, httpx.TimeoutException)
                else "provider_unavailable",
                retriable=False,
            ) from exc
        if response.is_error:
            request_id = response.headers.get("request-id")
            upstream_code: str | None = None
            try:
                detail = response.json().get("detail")
                if isinstance(detail, dict):
                    code = detail.get("code")
                    upstream_code = code if isinstance(code, str) else None
                    detail_request_id = detail.get("request_id")
                    if request_id is None and isinstance(detail_request_id, str):
                        request_id = detail_request_id
            except (ValueError, AttributeError):
                pass
            category = {
                401: "provider_auth_error",
                402: "provider_quota_exceeded",
                408: "provider_timeout",
                429: "provider_rate_limited",
            }.get(
                response.status_code,
                "provider_rejected"
                if response.status_code < 500
                else "provider_unavailable",
            )
            raise TTSProviderError(
                f"ElevenLabs speech generation failed ({response.status_code}).",
                category=category,
                retriable=response.status_code in {408, 429}
                or response.status_code >= 500,
                provider_request_id=request_id,
                upstream_code=upstream_code,
            )
        content_type, extension = output
        return TTSResult(
            audio=response.content,
            content_type=content_type,
            extension=extension,
            provider_request_id=response.headers.get("request-id"),
            usage=usage,
        )

    async def _get_usage(
        self, client: httpx.AsyncClient, speech_response: httpx.Response
    ) -> TTSUsage:
        generated_units = _optional_int(speech_response.headers.get("character-cost"))
        try:
            response = await client.get(
                "/v1/user/subscription",
                headers={"xi-api-key": self.api_key or ""},
            )
            response.raise_for_status()
            return _usage_from_subscription(response.json(), generated_units)
        except (httpx.HTTPError, ValueError, AttributeError):
            return TTSUsage(generated_units=generated_units)

    async def get_account_usage(self) -> TTSUsage:
        if not self.api_key:
            raise TTSProviderError(
                "ElevenLabs is not configured. Set ELEVENLABS_API_KEY on the server.",
                category="provider_auth_error",
                retriable=False,
            )
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(20),
                transport=self.transport,
            ) as client:
                response = await client.get(
                    "/v1/user/subscription",
                    headers={"xi-api-key": self.api_key},
                )
            response.raise_for_status()
            return _usage_from_subscription(response.json())
        except httpx.TimeoutException as exc:
            raise TTSProviderError(
                "ElevenLabs account usage timed out.",
                category="provider_timeout",
                retriable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise TTSProviderError(
                "ElevenLabs account usage is unavailable.",
                category="provider_unavailable",
                retriable=True,
            ) from exc
        except (ValueError, AttributeError) as exc:
            raise TTSProviderError(
                "ElevenLabs returned malformed account usage.",
                category="provider_rejected",
                retriable=False,
            ) from exc

    async def list_voices(self) -> list[TTSVoice]:
        if not self.api_key:
            raise TTSProviderError(
                "ElevenLabs is not configured. Set ELEVENLABS_API_KEY on the server.",
                category="provider_auth_error",
                retriable=False,
            )
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(20),
                transport=self.transport,
            ) as client:
                response = await client.get(
                    "/v2/voices",
                    params={"page_size": 100, "voice_type": "saved"},
                    headers={"xi-api-key": self.api_key},
                )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(
                payload.get("voices"), list
            ):
                raise ValueError("Voices response must contain a list")
            voices: list[TTSVoice] = []
            for item in payload["voices"]:
                if not isinstance(item, dict):
                    continue
                voice_id = item.get("voice_id")
                name = item.get("name")
                if not isinstance(voice_id, str) or not isinstance(name, str):
                    continue
                voices.append(
                    TTSVoice(
                        voice_id=voice_id,
                        name=name,
                        category=item.get("category")
                        if isinstance(item.get("category"), str)
                        else None,
                        description=item.get("description")
                        if isinstance(item.get("description"), str)
                        else None,
                        preview_url=item.get("preview_url")
                        if isinstance(item.get("preview_url"), str)
                        else None,
                    )
                )
            return voices
        except httpx.HTTPError as exc:
            raise TTSProviderError(
                "ElevenLabs voices are unavailable.",
                category="provider_unavailable",
                retriable=True,
            ) from exc
        except (ValueError, AttributeError) as exc:
            raise TTSProviderError(
                "ElevenLabs returned malformed voices.",
                category="provider_rejected",
                retriable=False,
            ) from exc


def _usage_from_subscription(
    payload: object, generated_units: int | None = None
) -> TTSUsage:
    if not isinstance(payload, dict):
        raise ValueError("Subscription response must be an object")
    used = _optional_int(payload.get("character_count"))
    limit = _optional_int(payload.get("character_limit"))
    remaining = max(limit - used, 0) if used is not None and limit is not None else None
    return TTSUsage(
        generated_units=generated_units,
        account_used_units=used,
        account_limit_units=limit,
        account_remaining_units=remaining,
        resets_at_unix=_optional_int(payload.get("next_character_count_reset_unix")),
    )


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if not isinstance(value, (str, bytes, bytearray, int, float)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
