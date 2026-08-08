import os

import httpx

from app.providers.tts.contracts import TTSProviderError, TTSRequest, TTSResult

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
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise TTSProviderError(
                "ElevenLabs is temporarily unreachable.",
                category="provider_unavailable",
                retriable=True,
            ) from exc
        if response.is_error:
            category = {
                401: "provider_auth_error",
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
                retriable=response.status_code == 429 or response.status_code >= 500,
            )
        content_type, extension = output
        return TTSResult(
            audio=response.content,
            content_type=content_type,
            extension=extension,
            provider_request_id=response.headers.get("request-id"),
        )
