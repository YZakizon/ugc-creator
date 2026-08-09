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
    usage: "TTSUsage | None" = None


@dataclass(frozen=True)
class TTSUsage:
    generated_units: int | None = None
    account_used_units: int | None = None
    account_limit_units: int | None = None
    account_remaining_units: int | None = None
    resets_at_unix: int | None = None
    unit: str = "characters"


@dataclass(frozen=True)
class TTSVoice:
    voice_id: str
    name: str
    category: str | None = None
    description: str | None = None
    preview_url: str | None = None


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


class TTSProviderOutcomeUnknown(TTSProviderError):
    """The paid synthesis may have been accepted and must not auto-retry."""
