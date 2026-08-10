import io
import wave

from app.providers.tts.contracts import TTSRequest, TTSResult, TTSUsage


class FakeTTSProvider:
    async def synthesize(self, request: TTSRequest) -> TTSResult:
        sample_rate = 8_000
        duration_seconds = max(1, min(10, len(request.text.split()) // 3))
        output = io.BytesIO()
        with wave.open(output, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(sample_rate)
            audio.writeframes(b"\x00\x00" * sample_rate * duration_seconds)
        return TTSResult(
            audio=output.getvalue(),
            content_type="audio/wav",
            extension="wav",
            provider_request_id="fake-tts-request",
            usage=TTSUsage(
                generated_units=len(request.text),
                account_used_units=125,
                account_limit_units=10_000,
                account_remaining_units=9_875,
            ),
        )
