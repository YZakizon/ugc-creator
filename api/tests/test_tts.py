import httpx
import pytest

from app.providers.tts.contracts import (
    TTSProviderError,
    TTSProviderOutcomeUnknown,
    TTSRequest,
)
from app.providers.tts.elevenlabs import ElevenLabsTTSProvider


@pytest.mark.asyncio
async def test_elevenlabs_adapter_maps_voice_settings_and_audio() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/text-to-speech/voice-123"
        assert request.url.params["output_format"] == "mp3_44100_128"
        assert request.headers["xi-api-key"] == "secret"
        payload = __import__("json").loads(request.content)
        assert payload["model_id"] == "eleven_multilingual_v2"
        assert payload["voice_settings"] == {
            "speed": 1.0,
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.5,
            "use_speaker_boost": True,
        }
        return httpx.Response(200, content=b"ID3audio", headers={"request-id": "req-1"})

    provider = ElevenLabsTTSProvider(
        api_key="secret", transport=httpx.MockTransport(handler)
    )
    result = await provider.synthesize(
        TTSRequest(
            text="Hello",
            voice_id="voice-123",
            model_id="eleven_multilingual_v2",
            voice_settings={
                "speed": 1.0,
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.5,
                "use_speaker_boost": True,
            },
        )
    )

    assert result.audio == b"ID3audio"
    assert result.provider_request_id == "req-1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_category", "expected_retriable"),
    [
        (401, "provider_auth_error", False),
        (402, "provider_quota_exceeded", False),
        (422, "provider_rejected", False),
        (429, "provider_rate_limited", True),
        (503, "provider_unavailable", True),
    ],
)
async def test_elevenlabs_adapter_normalizes_provider_errors(
    status_code: int, expected_category: str, expected_retriable: bool
) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json={
                "detail": {
                    "code": "upstream-code",
                    "request_id": "body-request-id",
                }
            },
        )

    provider = ElevenLabsTTSProvider(
        api_key="secret", transport=httpx.MockTransport(handler)
    )

    with pytest.raises(TTSProviderError) as raised:
        await provider.synthesize(
            TTSRequest(
                text="Hello",
                voice_id="voice-123",
                model_id="eleven_multilingual_v2",
            )
        )

    assert raised.value.category == expected_category
    assert raised.value.retriable is expected_retriable
    assert raised.value.provider_request_id == "body-request-id"
    assert raised.value.upstream_code == "upstream-code"


@pytest.mark.asyncio
async def test_elevenlabs_lost_response_is_not_automatically_retriable() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    provider = ElevenLabsTTSProvider(
        api_key="secret", transport=httpx.MockTransport(handler)
    )

    with pytest.raises(TTSProviderOutcomeUnknown) as raised:
        await provider.synthesize(
            TTSRequest(
                text="Hello",
                voice_id="voice-123",
                model_id="eleven_multilingual_v2",
            )
        )

    assert raised.value.category == "provider_timeout"
    assert raised.value.retriable is False
    assert "response was lost" in str(raised.value)


@pytest.mark.asyncio
async def test_elevenlabs_connect_failure_remains_retriable() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = ElevenLabsTTSProvider(
        api_key="secret", transport=httpx.MockTransport(handler)
    )

    with pytest.raises(TTSProviderError) as raised:
        await provider.synthesize(
            TTSRequest(
                text="Hello",
                voice_id="voice-123",
                model_id="eleven_multilingual_v2",
            )
        )

    assert not isinstance(raised.value, TTSProviderOutcomeUnknown)
    assert raised.value.category == "provider_unavailable"
    assert raised.value.retriable is True
