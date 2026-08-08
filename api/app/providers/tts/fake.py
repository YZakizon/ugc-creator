from app.providers.tts.contracts import TTSRequest, TTSResult


class FakeTTSProvider:
    async def synthesize(self, request: TTSRequest) -> TTSResult:
        return TTSResult(
            audio=b"ID3" + request.text.encode("utf-8"),
            content_type="audio/mpeg",
            extension="mp3",
            provider_request_id="fake-tts-request",
        )
