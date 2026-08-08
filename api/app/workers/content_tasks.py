import os
from uuid import UUID

from celery import Task

from app.db.session import create_database_engine, session_factory
from app.providers.llm.contracts import LLMProviderError
from app.providers.llm.fake import FakeLLMProvider
from app.providers.llm.openai_responses import OpenAIResponsesProvider
from app.services.content_service import run_content_generation
from app.workers.celery_app import celery_app
from app.workers.retry import retry_provider_error


@celery_app.task(
    bind=True,
    name="ugc_creator.generate_job_content",
    max_retries=2,
)  # type: ignore[untyped-decorator]
def generate_job_content(task: Task, job_id: str) -> dict[str, str]:
    engine = create_database_engine()
    if engine is None:
        raise RuntimeError("DATABASE_URL is required for content generation")
    provider = (
        FakeLLMProvider()
        if os.getenv("UGC_FAKE_PROVIDERS") == "1"
        else OpenAIResponsesProvider()
    )
    try:
        job = run_content_generation(
            UUID(job_id),
            session_factory(engine),
            provider,
        )
    except LLMProviderError as exc:
        retry_provider_error(task, exc, retriable=exc.retriable)
        raise
    return {"job_id": str(job.id), "status": job.status}
