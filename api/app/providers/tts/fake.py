from app.providers.tts.contracts import TTSRequest, TTSResult, TTSUsage


class FakeTTSProvider:
    async def synthesize(self, request: TTSRequest) -> TTSResult:
        return TTSResult(
            audio=b"ID3" + request.text.encode("utf-8"),
            content_type="audio/mpeg",
            extension="mp3",
            provider_request_id="fake-tts-request",
            usage=TTSUsage(
                generated_units=len(request.text),
                account_used_units=125,
                account_limit_units=10_000,
                account_remaining_units=9_875,
            ),
        )
