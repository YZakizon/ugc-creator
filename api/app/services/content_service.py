import asyncio
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.core.statuses import JobStatus
from app.db.models import TopicJob
from app.providers.llm.contracts import LLMProvider, UGCContentRequest


class ContentService:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    async def generate_for_job(
        self, job_id: UUID, factory: sessionmaker[Session]
    ) -> TopicJob:
        with factory() as session:
            job = session.get(TopicJob, job_id)
            if job is None:
                raise ValueError("Job not found")
            if job.status == JobStatus.CONTENT_READY.value and job.speech_script:
                return job
            job.status = JobStatus.GENERATING_CONTENT.value
            job.error_message = None
            session.commit()
            topic = job.topic
            target_duration = job.target_duration_seconds

        try:
            result = await self.provider.generate_ugc_content(
                UGCContentRequest(
                    topic=topic,
                    target_duration_seconds=target_duration,
                )
            )
        except Exception as exc:
            with factory() as session:
                failed_job = session.get(TopicJob, job_id)
                if failed_job is not None:
                    failed_job.status = JobStatus.FAILED.value
                    failed_job.error_message = str(exc)
                    session.commit()
            raise

        with factory() as session:
            completed_job = session.get(TopicJob, job_id)
            if completed_job is None:
                raise ValueError("Job disappeared during content generation")
            completed_job.status = JobStatus.CONTENT_READY.value
            completed_job.speech_script = result.content.speech_script
            completed_job.hook = result.content.hook
            completed_job.instagram_metadata = result.content.instagram.model_dump()
            completed_job.tiktok_metadata = result.content.tiktok.model_dump()
            completed_job.llm_provider = result.provider
            completed_job.llm_model = result.model
            completed_job.prompt_version = result.prompt_version
            completed_job.error_message = None
            session.commit()
            session.refresh(completed_job)
            return completed_job


def run_content_generation(
    job_id: UUID, factory: sessionmaker[Session], provider: LLMProvider
) -> TopicJob:
    return asyncio.run(ContentService(provider).generate_for_job(job_id, factory))
