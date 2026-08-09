import httpx
import pytest

from app.main import app


@pytest.mark.asyncio
async def test_health_reports_missing_provider_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured")
    monkeypatch.setenv("REDIS_URL", "redis://configured")
    monkeypatch.setenv("COMFYUI_BASE_URL", "http://comfyui:8188")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("UGC_FAKE_PROVIDERS", raising=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["ready"] is False
    assert payload["checks"]["openai"]["configured"] is False
    assert payload["checks"]["elevenlabs"]["configured"] is False
    assert any("OPENAI_API_KEY" in warning for warning in payload["warnings"])


@pytest.mark.asyncio
async def test_health_accepts_deterministic_fake_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured")
    monkeypatch.setenv("REDIS_URL", "redis://configured")
    monkeypatch.setenv("COMFYUI_BASE_URL", "http://comfyui:8188")
    monkeypatch.setenv("UGC_FAKE_PROVIDERS", "1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ready"] is True
    assert payload["checks"]["openai"]["configured"] is True
    assert payload["checks"]["elevenlabs"]["configured"] is True
