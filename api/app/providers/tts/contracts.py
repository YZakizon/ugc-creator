from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class TTSRequest:
    text: str
    voice_id: str
    model_id: str
    output_format: str = "mp3_44100_128"
    language_code: str | None = None
    voice_settings: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class TTSResult:
    audio: bytes
    content_type: str
    extension: str
    provider_request_id: str | None = None


class TTSProvider(Protocol):
    async def synthesize(self, request: TTSRequest) -> TTSResult: ...


class TTSProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        category: str,
        retriable: bool,
        provider_request_id: str | None = None,
        upstream_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.retriable = retriable
        self.provider_request_id = provider_request_id
        self.upstream_code = upstream_code
