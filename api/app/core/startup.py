import os
from typing import TypedDict


class StartupCheck(TypedDict):
    configured: bool
    message: str


class StartupSanityReport(TypedDict):
    status: str
    ready: bool
    checks: dict[str, StartupCheck]
    warnings: list[str]


def content_generation_configured() -> bool:
    return os.getenv("UGC_FAKE_PROVIDERS") == "1" or bool(
        os.getenv("OPENAI_API_KEY", "").strip()
    )


def build_startup_sanity_report() -> StartupSanityReport:
    fake_providers = os.getenv("UGC_FAKE_PROVIDERS") == "1"
    checks: dict[str, StartupCheck] = {
        "database": _check(
            bool(os.getenv("DATABASE_URL", "").strip()),
            "Database is configured.",
            "DATABASE_URL is missing; data will use temporary in-memory storage.",
        ),
        "redis": _check(
            bool(os.getenv("REDIS_URL", "").strip()),
            "Redis is configured.",
            "REDIS_URL is missing; background jobs cannot be queued reliably.",
        ),
        "openai": _check(
            content_generation_configured(),
            "OpenAI content generation is configured."
            if not fake_providers
            else "Fake content generation is enabled.",
            "OpenAI is not configured. Set OPENAI_API_KEY in the root .env file "
            "and restart Docker before generating content.",
        ),
        "elevenlabs": _check(
            fake_providers or bool(os.getenv("ELEVENLABS_API_KEY", "").strip()),
            "ElevenLabs speech generation is configured."
            if not fake_providers
            else "Fake speech generation is enabled.",
            "ElevenLabs is not configured. Set ELEVENLABS_API_KEY in the root "
            ".env file and restart Docker before generating speech.",
        ),
        "comfyui": _check(
            bool(os.getenv("COMFYUI_BASE_URL", "").strip()),
            "A default ComfyUI URL is configured; test connectivity in Settings.",
            "COMFYUI_BASE_URL is missing; add a render node in Settings before "
            "rendering.",
        ),
    }
    warnings = [
        check["message"] for check in checks.values() if not check["configured"]
    ]
    return {
        "status": "ok",
        "ready": not warnings,
        "checks": checks,
        "warnings": warnings,
    }


def _check(configured: bool, ready: str, missing: str) -> StartupCheck:
    return {"configured": configured, "message": ready if configured else missing}
