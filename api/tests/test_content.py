import asyncio
import json

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.providers.llm.contracts import UGCContentRequest
from app.providers.llm.fake import FakeLLMProvider
from app.providers.llm.openai_responses import (
    LLMProviderError,
    OpenAIResponsesProvider,
)
from app.repositories import (
    InMemoryBatchRepository,
    InMemoryConfigurationRepository,
    SqlAlchemyBatchRepository,
)
from app.schemas import BatchCreate
from app.services.content_service import run_content_generation


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
async def test_openai_provider_requires_server_key() -> None:
    provider = OpenAIResponsesProvider(api_key=None)
    with pytest.raises(LLMProviderError, match="not configured"):
        await provider.generate_ugc_content(
            UGCContentRequest(topic="A topic", target_duration_seconds=30)
        )


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


@pytest.mark.asyncio
async def test_content_endpoint_queues_job_by_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
