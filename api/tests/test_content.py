import asyncio
import json

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.content_prompts import DEFAULT_CONTENT_PROMPT_TEMPLATE
from app.db import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.providers.llm.contracts import LLMProviderError, UGCContentRequest
from app.providers.llm.fake import FakeLLMProvider
from app.providers.llm.openai_responses import OpenAIResponsesProvider
from app.repositories import (
    InMemoryBatchRepository,
    InMemoryConfigurationRepository,
    SqlAlchemyBatchRepository,
    SqlAlchemyConfigurationRepository,
)
from app.schemas import BatchCreate
from app.services.content_service import run_content_generation
from app.workers.content_tasks import content_provider


def structured_content() -> dict[str, object]:
    return {
        "speech_script": "A short script.",
        "hook": "Here is the hook.",
        "instagram": {
            "title": "Instagram title",
            "description": "Instagram description",
            "hashtags": ["#ugc"],
        },
        "tiktok": {
            "title": "TikTok title",
            "description": "TikTok description",
            "hashtags": ["#tiktok"],
        },
    }


@pytest.mark.asyncio
async def test_openai_responses_provider_parses_structured_output() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/responses"
        payload = json.loads(request.content)
        assert payload["text"]["format"]["type"] == "json_schema"
        assert "30 seconds" in payload["input"][0]["content"]
        return httpx.Response(
            200,
            json={"output_text": json.dumps(structured_content())},
            headers={"x-request-id": "req_test"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAIResponsesProvider(
            api_key="test-key", model="test-model", client=client
        )
        result = await provider.generate_ugc_content(
            UGCContentRequest(topic="A useful reminder", target_duration_seconds=30)
        )

    assert result.provider == "openai"
    assert result.request_id == "req_test"
    assert result.content.speech_script == "A short script."


@pytest.mark.asyncio
async def test_openai_provider_uses_saved_prompt_text_and_version() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["input"][0]["content"] == "Make it fit 45 seconds."
        return httpx.Response(
            200,
            json={"output_text": json.dumps(structured_content())},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAIResponsesProvider(
            api_key="test-key",
            client=client,
            prompt_template="Make it fit {{TARGET_DURATION_SECONDS}} seconds.",
            prompt_version="custom-test",
        )
        result = await provider.generate_ugc_content(
            UGCContentRequest(topic="A topic", target_duration_seconds=45)
        )

    assert result.prompt_version == "custom-test"


@pytest.mark.asyncio
async def test_openai_provider_requires_server_key() -> None:
    provider = OpenAIResponsesProvider(api_key=None)
    with pytest.raises(LLMProviderError, match="not configured"):
        await provider.generate_ugc_content(
            UGCContentRequest(topic="A topic", target_duration_seconds=30)
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_category", "expected_retriable"),
    [
        (401, "provider_auth_error", False),
        (422, "provider_rejected", False),
        (429, "provider_rate_limited", True),
        (503, "provider_unavailable", True),
    ],
)
async def test_openai_provider_normalizes_http_errors(
    status_code: int, expected_category: str, expected_retriable: bool
) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            headers={"x-request-id": "openai-request"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAIResponsesProvider(api_key="test-key", client=client)
        with pytest.raises(LLMProviderError) as raised:
            await provider.generate_ugc_content(
                UGCContentRequest(topic="A topic", target_duration_seconds=30)
            )

    assert raised.value.category == expected_category
    assert raised.value.retriable is expected_retriable
    assert raised.value.provider_request_id == "openai-request"


@pytest.mark.asyncio
async def test_openai_provider_normalizes_timeout_as_retriable() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAIResponsesProvider(api_key="test-key", client=client)
        with pytest.raises(LLMProviderError) as raised:
            await provider.generate_ugc_content(
                UGCContentRequest(topic="A topic", target_duration_seconds=30)
            )

    assert raised.value.category == "provider_timeout"
    assert raised.value.retriable is True


@pytest.mark.asyncio
async def test_content_service_persists_fake_provider_result() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    batch_repository = SqlAlchemyBatchRepository(factory)
    batch = batch_repository.create_batch(
        BatchCreate(name="Content test", topics=["A topic"])
    )
    job_id = batch.jobs[0].id

    job = await asyncio.to_thread(
        run_content_generation, job_id, factory, FakeLLMProvider()
    )

    assert job.status == "content_ready"
    assert job.speech_script
    assert job.llm_provider == "fake"


def test_content_worker_loads_persisted_openai_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    SqlAlchemyConfigurationRepository(factory).upsert_content_prompt_setting(
        "openai", "Saved {{TARGET_DURATION_SECONDS}} prompt.", "custom-saved"
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("UGC_FAKE_PROVIDERS", raising=False)

    provider = content_provider(factory)

    assert isinstance(provider, OpenAIResponsesProvider)
    assert provider.prompt_template == "Saved {{TARGET_DURATION_SECONDS}} prompt."
    assert provider.prompt_version == "custom-saved"


@pytest.mark.asyncio
async def test_content_prompt_settings_api_saves_validated_prompt() -> None:
    app.state.configuration_repository = InMemoryConfigurationRepository()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        initial = await client.get("/api/v1/settings/content-generation")
        updated = await client.put(
            "/api/v1/settings/content-generation",
            json={
                "prompt_template": (
                    "Write a calm script lasting {{TARGET_DURATION_SECONDS}} seconds."
                )
            },
        )
        reread = await client.get("/api/v1/settings/content-generation")

    assert initial.status_code == 200
    assert initial.json()["prompt_template"] == DEFAULT_CONTENT_PROMPT_TEMPLATE
    assert updated.status_code == 200
    assert updated.json()["prompt_version"].startswith("custom-")
    assert reread.json() == updated.json()
    assert reread.json()["supported_placeholders"] == ["TARGET_DURATION_SECONDS"]


@pytest.mark.asyncio
async def test_content_prompt_settings_api_rejects_unknown_placeholder() -> None:
    app.state.configuration_repository = InMemoryConfigurationRepository()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.put(
            "/api/v1/settings/content-generation",
            json={"prompt_template": "Write about {{UNKNOWN_VALUE}}."},
        )

    assert response.status_code == 422
    assert "Unsupported prompt placeholder" in response.text


@pytest.mark.asyncio
async def test_content_endpoint_queues_job_by_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UGC_FAKE_PROVIDERS", "1")
    batch_repository = InMemoryBatchRepository()
    app.state.batch_repository = batch_repository
    app.state.configuration_repository = InMemoryConfigurationRepository()
    batch = batch_repository.create_batch(BatchCreate(name="Test", topics=["A topic"]))
    queued: list[str] = []

    def record_delay(job_id: str) -> None:
        queued.append(job_id)

    monkeypatch.setattr("app.api.routes.generate_job_content.delay", record_delay)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/api/v1/jobs/{batch.jobs[0].id}/generate-content",
            json={},
        )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert queued == [str(batch.jobs[0].id)]


@pytest.mark.asyncio
async def test_content_endpoint_rejects_unconfigured_openai_before_queueing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("UGC_FAKE_PROVIDERS", raising=False)
    batch_repository = InMemoryBatchRepository()
    app.state.batch_repository = batch_repository
    app.state.configuration_repository = InMemoryConfigurationRepository()
    batch = batch_repository.create_batch(
        BatchCreate(name="Unconfigured", topics=["A topic"])
    )
    queued: list[str] = []
    monkeypatch.setattr("app.api.routes.generate_job_content.delay", queued.append)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/api/v1/jobs/{batch.jobs[0].id}/generate-content",
            json={},
        )

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "provider_not_configured",
        "provider": "openai",
        "message": (
            "OpenAI is not configured. Set OPENAI_API_KEY in the root .env file "
            "and restart Docker before generating content."
        ),
        "retriable": False,
    }
    assert queued == []
    stored = batch_repository.get_job(batch.jobs[0].id)
    assert stored is not None
    assert stored.status == "draft"
