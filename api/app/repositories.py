import re
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, selectinload, sessionmaker

from app.core.statuses import BatchStatus, JobStatus
from app.db.models import (
    Batch,
    Character,
    ContentPromptSetting,
    MediaAsset,
    RenderAttempt,
    RenderProfile,
    TopicJob,
    VoicePreview,
    VoiceProfile,
    WorkflowParameterBinding,
    WorkflowTemplate,
)
from app.schemas import (
    BatchCreate,
    CharacterCreate,
    RenderProfileCreate,
    RenderProfileSetupCreate,
    RenderProfileUpdate,
    TopicBulkCreate,
    VoiceProfileCreate,
    VoiceProfileUpdate,
    WorkflowTemplateCreate,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


VOICE_PREVIEW_STALE_AFTER = timedelta(minutes=5)
VOICE_PREVIEW_OUTCOME_UNKNOWN = (
    "The previous speech request may still be running. Its provider outcome is "
    "unknown, so it was not retried automatically. Request speech again to retry."
)

ACTIVE_CONTENT_STATUSES = {
    JobStatus.GENERATING_CONTENT.value,
    JobStatus.GENERATING_TTS.value,
    JobStatus.FITTING_DURATION.value,
    JobStatus.QUEUED.value,
    JobStatus.SUBMITTING_RENDER.value,
    JobStatus.RENDERING.value,
    JobStatus.DOWNLOADING_OUTPUT.value,
}


def voice_preview_is_stale(preview: VoicePreview, now: datetime) -> bool:
    stale_at = (
        preview.claim_expires_at
        if preview.status == "generating" and preview.claim_expires_at is not None
        else preview.updated_at + VOICE_PREVIEW_STALE_AFTER
    )
    comparable_now = now
    if stale_at.tzinfo is None:
        comparable_now = now.replace(tzinfo=None)
    return preview.status in {"queued", "generating"} and stale_at <= comparable_now


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "character"


class VoiceProfileInUseError(ValueError):
    def __init__(
        self,
        render_profiles: Sequence[RenderProfile],
        characters: Sequence[Character],
    ) -> None:
        self.render_profiles = [
            {"id": str(profile.id), "name": profile.name}
            for profile in sorted(render_profiles, key=lambda item: item.name.lower())
        ]
        self.characters = [
            {"id": str(character.id), "name": character.name}
            for character in sorted(characters, key=lambda item: item.name.lower())
        ]
        references = []
        if self.render_profiles:
            references.append(
                "render profiles: "
                + ", ".join(
                    f"{profile['name']} (ID: {profile['id']})"
                    for profile in self.render_profiles
                )
            )
        if self.characters:
            references.append(
                "characters: "
                + ", ".join(
                    f"{character['name']} (ID: {character['id']})"
                    for character in self.characters
                )
            )
        super().__init__("Voice profile is in use by " + "; ".join(references))


class InMemoryBatchRepository:
    def __init__(self) -> None:
        self.batches: dict[UUID, Batch] = {}
        self.jobs: dict[UUID, TopicJob] = {}

    def create_batch(self, payload: BatchCreate) -> Batch:
        now = utc_now()
        batch = Batch(
            id=uuid4(),
            name=payload.name,
            status=BatchStatus.DRAFT.value,
            default_render_profile_id=payload.default_render_profile_id,
            target_duration_seconds=payload.target_duration_seconds,
            auto_fit_duration=payload.auto_fit_duration,
            next_content_number=len(payload.topics) + 1,
            created_at=now,
            updated_at=now,
        )
        batch.jobs = []
        for content_number, topic in enumerate(payload.topics, start=1):
            job = TopicJob(
                id=uuid4(),
                batch_id=batch.id,
                topic=topic,
                content_number=content_number,
                status=JobStatus.DRAFT.value,
                render_profile_id=payload.default_render_profile_id,
                target_duration_seconds=payload.target_duration_seconds,
                created_at=now,
                updated_at=now,
            )
            batch.jobs.append(job)
            self.jobs[job.id] = job
        self.batches[batch.id] = batch
        return batch

    def create_topics(self, payload: TopicBulkCreate) -> list[Batch]:
        return [
            self.create_batch(
                BatchCreate(
                    name=topic.splitlines()[0].strip()[:160] or "Untitled topic",
                    topics=[topic],
                    default_render_profile_id=payload.render_profile_id,
                    target_duration_seconds=payload.target_duration_seconds,
                    auto_fit_duration=payload.auto_fit_duration,
                )
            )
            for topic in payload.topics
        ]

    def list_batches(self, limit: int, offset: int) -> tuple[list[Batch], int]:
        batches = sorted(
            self.batches.values(), key=lambda item: item.created_at, reverse=True
        )
        return batches[offset : offset + limit], len(batches)

    def list_topics(self, limit: int, offset: int) -> tuple[list[Batch], int]:
        return self.list_batches(limit, offset)

    def list_topic_contents(
        self, topic_id: UUID, limit: int, offset: int
    ) -> tuple[list[TopicJob], int] | None:
        topic = self.batches.get(topic_id)
        if topic is None:
            return None
        contents = sorted(topic.jobs, key=lambda item: item.content_number)
        return contents[offset : offset + limit], len(contents)

    def get_batch(self, batch_id: UUID) -> Batch | None:
        return self.batches.get(batch_id)

    def get_job(self, job_id: UUID) -> TopicJob | None:
        return self.jobs.get(job_id)

    def create_content(self, topic_id: UUID) -> TopicJob | None:
        batch = self.batches.get(topic_id)
        if batch is None or not batch.jobs:
            return None
        source = min(batch.jobs, key=lambda item: item.content_number)
        now = utc_now()
        content = TopicJob(
            id=uuid4(),
            batch_id=batch.id,
            topic=source.topic,
            content_number=batch.next_content_number,
            status=JobStatus.DRAFT.value,
            render_profile_id=batch.default_render_profile_id,
            target_duration_seconds=batch.target_duration_seconds,
            created_at=now,
            updated_at=now,
        )
        content.media_assets = []
        content.render_attempts = []
        batch.jobs.append(content)
        batch.next_content_number += 1
        batch.updated_at = now
        self.jobs[content.id] = content
        return content

    def delete_content(
        self,
        content_id: UUID,
        delete_assets: Callable[[tuple[str, ...]], None],
    ) -> bool:
        content = self.jobs.get(content_id)
        if content is None:
            return False
        if content.status in ACTIVE_CONTENT_STATUSES:
            raise ValueError("Content cannot be deleted while generation is active")
        batch = self.batches.get(content.batch_id)
        if batch is not None and len(batch.jobs) == 1:
            raise ValueError("Delete the topic to remove its only content version")
        object_keys = tuple(
            asset.object_key for asset in content.__dict__.get("media_assets", [])
        )
        delete_assets(object_keys)
        self.jobs.pop(content_id)
        if batch is not None:
            batch.jobs = [job for job in batch.jobs if job.id != content_id]
            batch.updated_at = utc_now()
        return True

    def delete_topic(
        self,
        topic_id: UUID,
        delete_assets: Callable[[tuple[str, ...]], None],
    ) -> bool:
        batch = self.batches.get(topic_id)
        if batch is None:
            return False
        if any(content.status in ACTIVE_CONTENT_STATUSES for content in batch.jobs):
            raise ValueError(
                "Topic cannot be deleted while content generation is active"
            )
        object_keys = tuple(
            asset.object_key
            for content in batch.jobs
            for asset in content.__dict__.get("media_assets", [])
        )
        delete_assets(object_keys)
        self.batches.pop(topic_id)
        for content in batch.jobs:
            self.jobs.pop(content.id, None)
        return True

    def queue_job_for_content(self, job_id: UUID) -> TopicJob | None:
        job = self.jobs.get(job_id)
        if job is not None:
            job.status = JobStatus.QUEUED.value
            job.updated_at = utc_now()
        return job

    def recover_job_content_enqueue(self, job_id: UUID) -> TopicJob | None:
        job = self.jobs.get(job_id)
        if job is None:
            return None
        job.status = JobStatus.DRAFT.value
        job.error_message = "Content could not be queued. Try again."
        job.updated_at = utc_now()
        return job

    def queue_job_for_tts(self, job_id: UUID) -> TopicJob | None:
        job = self.jobs.get(job_id)
        if job is None:
            return None
        if not job.speech_script:
            raise ValueError("Generate job content before generating speech")
        if job.status not in {
            JobStatus.CONTENT_READY.value,
            JobStatus.FAILED.value,
            JobStatus.TTS_READY.value,
            JobStatus.READY_TO_RENDER.value,
            JobStatus.COMPLETED.value,
        }:
            raise ValueError(f"Job cannot generate speech from status {job.status}")
        job.status = JobStatus.GENERATING_TTS.value
        job.error_message = None
        job.updated_at = utc_now()
        return job

    def recover_job_tts_enqueue(self, job_id: UUID) -> TopicJob | None:
        job = self.jobs.get(job_id)
        if job is None:
            return None
        has_audio = any(
            asset.kind == "audio" for asset in job.__dict__.get("media_assets", [])
        )
        job.status = (
            JobStatus.READY_TO_RENDER.value
            if has_audio
            else JobStatus.CONTENT_READY.value
        )
        job.error_message = "Speech could not be queued. Try again."
        job.updated_at = utc_now()
        return job

    def update_job_render_profile(
        self,
        existing_job: TopicJob,
        profile: RenderProfile,
        *,
        archive_audio: bool,
    ) -> TopicJob | None:
        job = self.jobs.get(existing_job.id)
        if job is not None:
            replaced_audio = False
            for asset in job.__dict__.get("media_assets", []):
                if archive_audio and asset.kind == "audio":
                    asset.kind = "audio_archive"
                    replaced_audio = True
            job.render_profile_id = profile.id
            job.voice_profile_id = profile.voice_profile_id
            job.workflow_template_id = profile.workflow_template_id
            if replaced_audio and job.speech_script:
                job.status = JobStatus.CONTENT_READY.value
                job.tts_provider = None
                job.tts_voice_id = None
                job.tts_model = None
                job.tts_settings = None
                job.tts_provider_request_id = None
            elif job.status == JobStatus.COMPLETED.value:
                job.status = JobStatus.READY_TO_RENDER.value
                job.error_message = None
            job.updated_at = utc_now()
        return job

    def update_job_voice_profile(
        self, job_id: UUID, voice_profile_id: UUID
    ) -> TopicJob | None:
        job = self.jobs.get(job_id)
        if job is not None:
            job.voice_profile_id = voice_profile_id
            job.error_message = None
            if job.speech_script and job.status in {
                JobStatus.FAILED.value,
                JobStatus.READY_TO_RENDER.value,
                JobStatus.TTS_READY.value,
                JobStatus.COMPLETED.value,
            }:
                job.status = JobStatus.CONTENT_READY.value
            for asset in job.__dict__.get("media_assets", []):
                if asset.kind == "audio":
                    asset.kind = "audio_archive"
            job.tts_provider = None
            job.tts_voice_id = None
            job.tts_model = None
            job.tts_settings = None
            job.tts_provider_request_id = None
            job.updated_at = utc_now()
        return job

    def update_job_workflow_template(
        self, job_id: UUID, workflow_template_id: UUID
    ) -> TopicJob | None:
        job = self.jobs.get(job_id)
        if job is not None:
            job.workflow_template_id = workflow_template_id
            if job.status == JobStatus.COMPLETED.value:
                job.status = JobStatus.READY_TO_RENDER.value
                job.error_message = None
            job.updated_at = utc_now()
        return job

    def replace_job_audio(
        self,
        job_id: UUID,
        *,
        object_key: str,
        filename: str,
        content_type: str,
        size_bytes: int,
    ) -> TopicJob | None:
        job = self.jobs.get(job_id)
        if job is None:
            return None
        assets = job.__dict__.setdefault("media_assets", [])
        for asset in assets:
            if asset.kind == "audio":
                asset.kind = "audio_archive"
        assets.append(
            MediaAsset(
                id=uuid4(),
                job_id=job.id,
                render_attempt_id=None,
                kind="audio",
                object_key=object_key,
                filename=filename,
                content_type=content_type,
                size_bytes=size_bytes,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
        )
        job.status = JobStatus.READY_TO_RENDER.value
        job.error_message = None
        job.updated_at = utc_now()
        return job

    def list_jobs(self, limit: int = 5) -> list[TopicJob]:
        return sorted(
            self.jobs.values(), key=lambda item: item.created_at, reverse=True
        )[:limit]

    def count_jobs(self, statuses: set[JobStatus]) -> int:
        expected = {status.value for status in statuses}
        return sum(job.status in expected for job in self.jobs.values())


class SqlAlchemyBatchRepository:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self.factory = factory

    def create_batch(self, payload: BatchCreate) -> Batch:
        with self.factory() as session:
            batch = Batch(
                name=payload.name,
                status=BatchStatus.DRAFT.value,
                default_render_profile_id=payload.default_render_profile_id,
                target_duration_seconds=payload.target_duration_seconds,
                auto_fit_duration=payload.auto_fit_duration,
                next_content_number=len(payload.topics) + 1,
            )
            batch.jobs = [
                TopicJob(
                    topic=topic,
                    content_number=content_number,
                    status=JobStatus.DRAFT.value,
                    render_profile_id=payload.default_render_profile_id,
                    target_duration_seconds=payload.target_duration_seconds,
                )
                for content_number, topic in enumerate(payload.topics, start=1)
            ]
            session.add(batch)
            session.commit()
            session.refresh(batch)
            # Load the relationship while the session is still attached.
            _ = batch.jobs
            return batch

    def create_topics(self, payload: TopicBulkCreate) -> list[Batch]:
        with self.factory() as session:
            topics = [
                Batch(
                    name=topic.splitlines()[0].strip()[:160] or "Untitled topic",
                    status=BatchStatus.DRAFT.value,
                    default_render_profile_id=payload.render_profile_id,
                    target_duration_seconds=payload.target_duration_seconds,
                    auto_fit_duration=payload.auto_fit_duration,
                    next_content_number=2,
                    jobs=[
                        TopicJob(
                            topic=topic,
                            content_number=1,
                            status=JobStatus.DRAFT.value,
                            render_profile_id=payload.render_profile_id,
                            target_duration_seconds=payload.target_duration_seconds,
                        )
                    ],
                )
                for topic in payload.topics
            ]
            session.add_all(topics)
            session.commit()
            topic_ids = [topic.id for topic in topics]
            return list(
                session.scalars(
                    select(Batch)
                    .options(
                        selectinload(Batch.jobs).selectinload(TopicJob.media_assets)
                    )
                    .where(Batch.id.in_(topic_ids))
                )
                .unique()
                .all()
            )

    def list_batches(self, limit: int, offset: int) -> tuple[list[Batch], int]:
        with self.factory() as session:
            query = (
                select(Batch)
                .options(selectinload(Batch.jobs).selectinload(TopicJob.media_assets))
                .order_by(Batch.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            batches = list(session.scalars(query).unique().all())
            total = session.scalar(select(func.count(Batch.id))) or 0
            return batches, total

    def list_topics(self, limit: int, offset: int) -> tuple[list[Batch], int]:
        with self.factory() as session:
            query = (
                select(Batch)
                .options(
                    selectinload(Batch.jobs).load_only(TopicJob.id, TopicJob.status)
                )
                .order_by(Batch.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            topics = list(session.scalars(query).unique().all())
            total = session.scalar(select(func.count()).select_from(Batch)) or 0
            return topics, total

    def list_topic_contents(
        self, topic_id: UUID, limit: int, offset: int
    ) -> tuple[list[TopicJob], int] | None:
        with self.factory() as session:
            if session.get(Batch, topic_id) is None:
                return None
            query = (
                select(TopicJob)
                .options(selectinload(TopicJob.media_assets))
                .where(TopicJob.batch_id == topic_id)
                .order_by(TopicJob.content_number)
                .limit(limit)
                .offset(offset)
            )
            contents = list(session.scalars(query).all())
            total = (
                session.scalar(
                    select(func.count())
                    .select_from(TopicJob)
                    .where(TopicJob.batch_id == topic_id)
                )
                or 0
            )
            return contents, total

    def get_batch(self, batch_id: UUID) -> Batch | None:
        with self.factory() as session:
            batch = session.scalar(
                select(Batch)
                .options(selectinload(Batch.jobs).selectinload(TopicJob.media_assets))
                .where(Batch.id == batch_id)
            )
            return batch

    def get_job(self, job_id: UUID) -> TopicJob | None:
        with self.factory() as session:
            return session.scalar(
                select(TopicJob)
                .options(selectinload(TopicJob.media_assets))
                .where(TopicJob.id == job_id)
            )

    def create_content(self, topic_id: UUID) -> TopicJob | None:
        with self.factory() as session:
            batch = session.scalar(
                select(Batch)
                .options(selectinload(Batch.jobs))
                .where(Batch.id == topic_id)
                .with_for_update()
            )
            if batch is None or not batch.jobs:
                return None
            source = min(batch.jobs, key=lambda item: item.content_number)
            content = TopicJob(
                batch_id=batch.id,
                topic=source.topic,
                content_number=batch.next_content_number,
                status=JobStatus.DRAFT.value,
                render_profile_id=batch.default_render_profile_id,
                target_duration_seconds=batch.target_duration_seconds,
            )
            session.add(content)
            batch.next_content_number += 1
            batch.updated_at = utc_now()
            session.commit()
            return session.scalar(
                select(TopicJob)
                .options(selectinload(TopicJob.media_assets))
                .where(TopicJob.id == content.id)
            )

    def delete_content(
        self,
        content_id: UUID,
        delete_assets: Callable[[tuple[str, ...]], None],
    ) -> bool:
        with self.factory() as session:
            batch_id = session.scalar(
                select(TopicJob.batch_id).where(TopicJob.id == content_id)
            )
            if batch_id is None:
                return False
            batch = session.scalar(
                select(Batch).where(Batch.id == batch_id).with_for_update()
            )
            content = session.scalar(
                select(TopicJob)
                .options(selectinload(TopicJob.media_assets))
                .where(TopicJob.id == content_id)
                .with_for_update()
            )
            if content is None:
                return False
            if content.status in ACTIVE_CONTENT_STATUSES:
                raise ValueError("Content cannot be deleted while generation is active")
            content_count = session.scalar(
                select(func.count())
                .select_from(TopicJob)
                .where(TopicJob.batch_id == batch_id)
            )
            if content_count == 1:
                raise ValueError("Delete the topic to remove its only content version")
            object_keys = tuple(asset.object_key for asset in content.media_assets)
            delete_assets(object_keys)
            session.delete(content)
            if batch is not None:
                batch.updated_at = utc_now()
            session.commit()
            return True

    def delete_topic(
        self,
        topic_id: UUID,
        delete_assets: Callable[[tuple[str, ...]], None],
    ) -> bool:
        with self.factory() as session:
            topic = session.scalar(
                select(Batch).where(Batch.id == topic_id).with_for_update()
            )
            if topic is None:
                return False
            contents = list(
                session.scalars(
                    select(TopicJob)
                    .options(selectinload(TopicJob.media_assets))
                    .where(TopicJob.batch_id == topic_id)
                    .order_by(TopicJob.id)
                    .with_for_update()
                ).all()
            )
            if any(content.status in ACTIVE_CONTENT_STATUSES for content in contents):
                raise ValueError(
                    "Topic cannot be deleted while content generation is active"
                )
            object_keys = tuple(
                asset.object_key
                for content in contents
                for asset in content.media_assets
            )
            delete_assets(object_keys)
            session.delete(topic)
            session.commit()
            return True

    def queue_job_for_content(self, job_id: UUID) -> TopicJob | None:
        with self.factory() as session:
            job = session.scalar(
                select(TopicJob)
                .options(selectinload(TopicJob.media_assets))
                .where(TopicJob.id == job_id)
                .with_for_update()
            )
            if job is None:
                return None
            job.status = JobStatus.QUEUED.value
            session.commit()
            session.refresh(job)
            return job

    def recover_job_content_enqueue(self, job_id: UUID) -> TopicJob | None:
        with self.factory() as session:
            job = session.get(TopicJob, job_id)
            if job is None:
                return None
            job.status = JobStatus.DRAFT.value
            job.error_message = "Content could not be queued. Try again."
            session.commit()
            session.refresh(job)
            return job

    def queue_job_for_tts(self, job_id: UUID) -> TopicJob | None:
        with self.factory() as session:
            job = session.scalar(
                select(TopicJob).where(TopicJob.id == job_id).with_for_update()
            )
            if job is None:
                return None
            if not job.speech_script:
                raise ValueError("Generate job content before generating speech")
            if job.status not in {
                JobStatus.CONTENT_READY.value,
                JobStatus.FAILED.value,
                JobStatus.TTS_READY.value,
                JobStatus.READY_TO_RENDER.value,
                JobStatus.COMPLETED.value,
            }:
                raise ValueError(f"Job cannot generate speech from status {job.status}")
            job.status = JobStatus.GENERATING_TTS.value
            job.error_message = None
            job.tts_claim_token = None
            job.tts_claim_expires_at = None
            session.commit()
            return session.scalar(
                select(TopicJob)
                .options(selectinload(TopicJob.media_assets))
                .where(TopicJob.id == job_id)
            )

    def recover_job_tts_enqueue(self, job_id: UUID) -> TopicJob | None:
        with self.factory() as session:
            job = session.scalar(
                select(TopicJob)
                .options(selectinload(TopicJob.media_assets))
                .where(TopicJob.id == job_id)
            )
            if job is None:
                return None
            job.status = (
                JobStatus.READY_TO_RENDER.value
                if any(asset.kind == "audio" for asset in job.media_assets)
                else JobStatus.CONTENT_READY.value
            )
            job.error_message = "Speech could not be queued. Try again."
            job.tts_claim_token = None
            job.tts_claim_expires_at = None
            session.commit()
            return job

    def update_job_render_profile(
        self,
        existing_job: TopicJob,
        profile: RenderProfile,
        *,
        archive_audio: bool,
    ) -> TopicJob | None:
        with self.factory() as session:
            job = session.scalar(
                select(TopicJob)
                .options(selectinload(TopicJob.media_assets))
                .where(TopicJob.id == existing_job.id)
            )
            if job is None:
                return None
            replaced_audio = False
            for asset in job.media_assets:
                if archive_audio and asset.kind == "audio":
                    asset.kind = "audio_archive"
                    replaced_audio = True
            job.render_profile_id = profile.id
            job.voice_profile_id = profile.voice_profile_id
            job.workflow_template_id = profile.workflow_template_id
            if replaced_audio and job.speech_script:
                job.status = JobStatus.CONTENT_READY.value
                job.tts_provider = None
                job.tts_voice_id = None
                job.tts_model = None
                job.tts_settings = None
                job.tts_provider_request_id = None
            elif job.status == JobStatus.COMPLETED.value:
                job.status = JobStatus.READY_TO_RENDER.value
                job.error_message = None
            session.commit()
            return session.scalar(
                select(TopicJob)
                .options(selectinload(TopicJob.media_assets))
                .where(TopicJob.id == existing_job.id)
            )

    def update_job_voice_profile(
        self, job_id: UUID, voice_profile_id: UUID
    ) -> TopicJob | None:
        with self.factory() as session:
            job = session.scalar(
                select(TopicJob)
                .options(selectinload(TopicJob.media_assets))
                .where(TopicJob.id == job_id)
            )
            if job is None:
                return None
            job.voice_profile_id = voice_profile_id
            job.error_message = None
            if job.speech_script and job.status in {
                JobStatus.FAILED.value,
                JobStatus.READY_TO_RENDER.value,
                JobStatus.TTS_READY.value,
                JobStatus.COMPLETED.value,
            }:
                job.status = JobStatus.CONTENT_READY.value
            for asset in job.media_assets:
                if asset.kind == "audio":
                    asset.kind = "audio_archive"
            job.tts_provider = None
            job.tts_voice_id = None
            job.tts_model = None
            job.tts_settings = None
            job.tts_provider_request_id = None
            session.commit()
            return session.scalar(
                select(TopicJob)
                .options(selectinload(TopicJob.media_assets))
                .where(TopicJob.id == job_id)
            )

    def update_job_workflow_template(
        self, job_id: UUID, workflow_template_id: UUID
    ) -> TopicJob | None:
        with self.factory() as session:
            job = session.get(TopicJob, job_id)
            if job is None:
                return None
            job.workflow_template_id = workflow_template_id
            if job.status == JobStatus.COMPLETED.value:
                job.status = JobStatus.READY_TO_RENDER.value
                job.error_message = None
            session.commit()
            return session.scalar(
                select(TopicJob)
                .options(selectinload(TopicJob.media_assets))
                .where(TopicJob.id == job_id)
            )

    def replace_job_audio(
        self,
        job_id: UUID,
        *,
        object_key: str,
        filename: str,
        content_type: str,
        size_bytes: int,
    ) -> TopicJob | None:
        with self.factory() as session:
            job = session.scalar(
                select(TopicJob)
                .options(selectinload(TopicJob.media_assets))
                .where(TopicJob.id == job_id)
            )
            if job is None:
                return None
            for asset in job.media_assets:
                if asset.kind == "audio":
                    asset.kind = "audio_archive"
            session.add(
                MediaAsset(
                    job_id=job.id,
                    render_attempt_id=None,
                    kind="audio",
                    object_key=object_key,
                    filename=filename,
                    content_type=content_type,
                    size_bytes=size_bytes,
                )
            )
            job.status = JobStatus.READY_TO_RENDER.value
            job.error_message = None
            session.commit()
            return session.scalar(
                select(TopicJob)
                .options(selectinload(TopicJob.media_assets))
                .where(TopicJob.id == job_id)
            )

    def list_jobs(self, limit: int = 5) -> list[TopicJob]:
        with self.factory() as session:
            return list(
                session.scalars(
                    select(TopicJob)
                    .options(selectinload(TopicJob.media_assets))
                    .order_by(TopicJob.created_at.desc())
                    .limit(limit)
                ).all()
            )

    def count_jobs(self, statuses: set[JobStatus]) -> int:
        with self.factory() as session:
            return int(
                session.scalar(
                    select(func.count(TopicJob.id)).where(
                        TopicJob.status.in_([status.value for status in statuses])
                    )
                )
                or 0
            )


class InMemoryConfigurationRepository:
    def __init__(self) -> None:
        self.characters: dict[UUID, Character] = {}
        self.voice_profiles: dict[UUID, VoiceProfile] = {}
        self.voice_previews: dict[UUID, VoicePreview] = {}
        self.render_profiles: dict[UUID, RenderProfile] = {}
        self.workflow_templates: dict[UUID, WorkflowTemplate] = {}
        self.content_prompt_settings: dict[str, ContentPromptSetting] = {}

    def get_content_prompt_setting(self, provider: str) -> ContentPromptSetting | None:
        return self.content_prompt_settings.get(provider)

    def upsert_content_prompt_setting(
        self, provider: str, prompt_template: str, prompt_version: str
    ) -> ContentPromptSetting:
        now = utc_now()
        setting = self.content_prompt_settings.get(provider)
        if setting is None:
            setting = ContentPromptSetting(
                provider=provider,
                prompt_template=prompt_template,
                prompt_version=prompt_version,
                created_at=now,
                updated_at=now,
            )
            self.content_prompt_settings[provider] = setting
        else:
            setting.prompt_template = prompt_template
            setting.prompt_version = prompt_version
            setting.updated_at = now
        return setting

    def create_character(self, payload: CharacterCreate) -> Character:
        now = utc_now()
        if payload.default_voice_profile_id not in (None, *self.voice_profiles):
            raise ValueError("Voice profile not found")
        character = Character(
            id=uuid4(),
            name=payload.name,
            slug=payload.slug or slugify(payload.name),
            description=payload.description,
            default_voice_profile_id=payload.default_voice_profile_id,
            default_prompt=payload.default_prompt,
            is_active=payload.is_active,
            created_at=now,
            updated_at=now,
        )
        self.characters[character.id] = character
        return character

    def list_characters(self) -> tuple[list[Character], int]:
        items = sorted(
            self.characters.values(), key=lambda item: item.created_at, reverse=True
        )
        return items, len(items)

    def create_voice_profile(self, payload: VoiceProfileCreate) -> VoiceProfile:
        now = utc_now()
        profile = VoiceProfile(
            id=uuid4(),
            name=payload.name,
            provider=payload.provider,
            provider_voice_id=payload.provider_voice_id,
            provider_model=payload.provider_model,
            speed=payload.speed,
            stability=payload.stability,
            similarity=payload.similarity,
            style_exaggeration=payload.style_exaggeration,
            extra_settings=payload.extra_settings,
            created_at=now,
            updated_at=now,
        )
        self.voice_profiles[profile.id] = profile
        return profile

    def list_voice_profiles(self) -> tuple[list[VoiceProfile], int]:
        items = sorted(
            self.voice_profiles.values(), key=lambda item: item.created_at, reverse=True
        )
        return items, len(items)

    def get_voice_profile(self, profile_id: UUID) -> VoiceProfile | None:
        return self.voice_profiles.get(profile_id)

    def update_voice_profile(
        self, profile_id: UUID, payload: VoiceProfileUpdate
    ) -> VoiceProfile | None:
        profile = self.voice_profiles.get(profile_id)
        if profile is None:
            return None
        profile.name = payload.name
        profile.provider = payload.provider
        profile.provider_voice_id = payload.provider_voice_id
        profile.provider_model = payload.provider_model
        profile.speed = payload.speed
        profile.stability = payload.stability
        profile.similarity = payload.similarity
        profile.style_exaggeration = payload.style_exaggeration
        profile.extra_settings = payload.extra_settings
        profile.updated_at = utc_now()
        return profile

    def delete_voice_profile(self, profile_id: UUID) -> bool:
        render_profiles = [
            profile
            for profile in self.render_profiles.values()
            if profile.voice_profile_id == profile_id
        ]
        characters = [
            character
            for character in self.characters.values()
            if character.default_voice_profile_id == profile_id
        ]
        if render_profiles or characters:
            raise VoiceProfileInUseError(render_profiles, characters)
        return self.voice_profiles.pop(profile_id, None) is not None

    def create_voice_preview(
        self, profile_id: UUID, text: str, fingerprint: str
    ) -> tuple[VoicePreview, bool]:
        profile = self.voice_profiles.get(profile_id)
        if profile is None:
            raise LookupError("Voice profile not found")
        existing = next(
            (
                preview
                for preview in self.voice_previews.values()
                if preview.request_fingerprint == fingerprint
            ),
            None,
        )
        if existing is not None:
            now = utc_now()
            if existing.status == "failed":
                existing.status = "queued"
                existing.error_message = None
                existing.updated_at = now
                return existing, True
            if voice_preview_is_stale(existing, now):
                if existing.status == "queued":
                    existing.updated_at = now
                    return existing, True
                existing.status = "failed"
                existing.error_message = VOICE_PREVIEW_OUTCOME_UNKNOWN
                existing.claim_token = None
                existing.claim_expires_at = None
                existing.updated_at = now
            return existing, False
        now = utc_now()
        preview = VoicePreview(
            id=uuid4(),
            voice_profile_id=profile.id,
            text=text,
            status="queued",
            request_fingerprint=fingerprint,
            provider=profile.provider,
            provider_voice_id=profile.provider_voice_id,
            provider_model=profile.provider_model,
            settings_json=voice_settings_snapshot(profile),
            created_at=now,
            updated_at=now,
        )
        self.voice_previews[preview.id] = preview
        return preview, True

    def get_voice_preview(self, preview_id: UUID) -> VoicePreview | None:
        return self.voice_previews.get(preview_id)

    def list_voice_previews(self, profile_id: UUID) -> tuple[list[VoicePreview], int]:
        items = sorted(
            (
                preview
                for preview in self.voice_previews.values()
                if preview.voice_profile_id == profile_id
            ),
            key=lambda preview: preview.created_at,
            reverse=True,
        )
        return items, len(items)

    def delete_voice_preview(self, preview_id: UUID) -> tuple[bool, str | None]:
        preview = self.voice_previews.pop(preview_id, None)
        return (preview is not None, preview.asset_key if preview else None)

    def get_latest_voice_preview_usage(self) -> VoicePreview | None:
        previews = [
            preview
            for preview in self.voice_previews.values()
            if preview.account_remaining_units is not None
        ]
        return max(previews, key=lambda preview: preview.updated_at, default=None)

    def create_render_profile(self, payload: RenderProfileCreate) -> RenderProfile:
        now = utc_now()
        if payload.character_id not in self.characters:
            raise ValueError("Character not found")
        if payload.voice_profile_id not in self.voice_profiles:
            raise ValueError("Voice profile not found")
        if (
            payload.workflow_template_id is not None
            and payload.workflow_template_id not in self.workflow_templates
        ):
            raise ValueError("Workflow template not found")
        profile = RenderProfile(
            id=uuid4(),
            name=payload.name,
            character_id=payload.character_id,
            voice_profile_id=payload.voice_profile_id,
            renderer_provider=payload.renderer_provider,
            render_node_id=payload.render_node_id,
            workflow_template_id=payload.workflow_template_id,
            prompt_template=payload.prompt_template,
            negative_prompt_template=payload.negative_prompt_template,
            default_parameters=payload.default_parameters,
            parameter_schema=payload.parameter_schema,
            capabilities=payload.capabilities,
            is_active=payload.is_active,
            created_at=now,
            updated_at=now,
        )
        self.render_profiles[profile.id] = profile
        return profile

    def create_render_profile_setup(
        self, payload: RenderProfileSetupCreate
    ) -> RenderProfile:
        if (
            payload.workflow_template_id is not None
            and payload.workflow_template_id not in self.workflow_templates
        ):
            raise ValueError("Workflow template not found")
        voice = self.voice_profiles.get(payload.voice_profile_id)
        if voice is None:
            raise ValueError("Voice profile not found")
        now = utc_now()

        character_slug = slugify(payload.character_name)
        character = next(
            (item for item in self.characters.values() if item.slug == character_slug),
            None,
        )
        if character is None:
            character = Character(
                id=uuid4(),
                name=payload.character_name,
                slug=character_slug,
                default_voice_profile_id=voice.id,
                description=None,
                default_prompt=None,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            self.characters[character.id] = character
        profile = RenderProfile(
            id=uuid4(),
            name=payload.profile_name,
            character_id=character.id,
            voice_profile_id=voice.id,
            renderer_provider=payload.renderer_provider,
            workflow_template_id=payload.workflow_template_id,
            prompt_template="",
            default_parameters={},
            parameter_schema={},
            capabilities={},
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        self.render_profiles[profile.id] = profile
        return profile

    def list_render_profiles(self) -> tuple[list[RenderProfile], int]:
        items = sorted(
            self.render_profiles.values(),
            key=lambda item: item.created_at,
            reverse=True,
        )
        return items, len(items)

    def get_render_profile(self, profile_id: UUID) -> RenderProfile | None:
        return self.render_profiles.get(profile_id)

    def update_render_profile(
        self, profile_id: UUID, payload: RenderProfileUpdate
    ) -> RenderProfile | None:
        profile = self.render_profiles.get(profile_id)
        if profile is None:
            return None
        if (
            payload.workflow_template_id is not None
            and payload.workflow_template_id not in self.workflow_templates
        ):
            raise ValueError("Workflow template not found")
        previous_voice_profile_id = profile.voice_profile_id
        profile.name = payload.name
        profile.workflow_template_id = payload.workflow_template_id
        if (
            payload.voice_profile_id is not None
            and payload.voice_profile_id not in self.voice_profiles
        ):
            raise ValueError("Voice profile not found")
        profile.voice_profile_id = payload.voice_profile_id
        character = self.characters.get(profile.character_id)
        if character is not None:
            if payload.character_name is not None:
                character.name = payload.character_name
            if character.default_voice_profile_id == previous_voice_profile_id:
                character.default_voice_profile_id = payload.voice_profile_id
            character.updated_at = utc_now()
        profile.updated_at = utc_now()
        return profile

    def delete_render_profile(self, profile_id: UUID) -> bool:
        return self.render_profiles.pop(profile_id, None) is not None

    def count_render_profiles(self) -> int:
        return sum(profile.is_active for profile in self.render_profiles.values())

    def count_render_profiles_for_workflow(self, template_id: UUID) -> int:
        source = self.workflow_templates.get(template_id)
        if source is None:
            return 0
        lineage_ids = {
            template.id
            for template in self.workflow_templates.values()
            if template.logical_id == source.logical_id
        }
        return sum(
            profile.workflow_template_id in lineage_ids
            for profile in self.render_profiles.values()
        )

    def create_workflow_template(
        self, payload: WorkflowTemplateCreate, checksum: str
    ) -> WorkflowTemplate:
        now = utc_now()
        template_id = uuid4()
        template = WorkflowTemplate(
            id=template_id,
            logical_id=template_id,
            name=payload.name,
            description=payload.description,
            renderer_provider=payload.renderer_provider,
            workflow_json=payload.workflow_json,
            metadata_json=payload.metadata_json,
            version=payload.version,
            checksum=checksum,
            created_at=now,
            updated_at=now,
        )
        template.bindings = [
            WorkflowParameterBinding(
                id=uuid4(),
                workflow_template_id=template.id,
                semantic_key=binding.semantic_key,
                node_id=binding.node_id,
                input_name=binding.input_name,
                value_type=binding.value_type,
                transform=binding.transform,
                required=binding.required,
            )
            for binding in payload.bindings
        ]
        self.workflow_templates[template.id] = template
        return template

    def update_workflow_template(
        self, template_id: UUID, payload: WorkflowTemplateCreate, checksum: str
    ) -> WorkflowTemplate | None:
        template = self.workflow_templates.get(template_id)
        if template is None:
            return None
        template.name = payload.name
        template.description = payload.description
        template.renderer_provider = payload.renderer_provider
        template.workflow_json = payload.workflow_json
        template.metadata_json = payload.metadata_json
        template.version += 1
        template.checksum = checksum
        template.updated_at = utc_now()
        template.bindings = [
            WorkflowParameterBinding(
                id=uuid4(),
                workflow_template_id=template.id,
                semantic_key=binding.semantic_key,
                node_id=binding.node_id,
                input_name=binding.input_name,
                value_type=binding.value_type,
                transform=binding.transform,
                required=binding.required,
            )
            for binding in payload.bindings
        ]
        return template

    def list_workflow_templates(self) -> tuple[list[WorkflowTemplate], int]:
        versions = sorted(
            self.workflow_templates.values(),
            key=lambda item: (item.version, item.created_at),
            reverse=True,
        )
        latest: dict[UUID, WorkflowTemplate] = {}
        for item in versions:
            latest.setdefault(item.logical_id, item)
        items = list(latest.values())
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items, len(items)

    def get_workflow_template(self, template_id: UUID) -> WorkflowTemplate | None:
        return self.workflow_templates.get(template_id)

    def delete_workflow_template(self, template_id: UUID) -> bool:
        source = self.workflow_templates.get(template_id)
        if source is None:
            return False
        if self.count_render_profiles_for_workflow(template_id):
            raise ValueError(
                "Workflow template is connected to one or more render profiles"
            )
        lineage_ids = [
            template.id
            for template in self.workflow_templates.values()
            if template.logical_id == source.logical_id
        ]
        for lineage_id in lineage_ids:
            self.workflow_templates.pop(lineage_id)
        return True


class SqlAlchemyConfigurationRepository:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self.factory = factory

    def get_content_prompt_setting(self, provider: str) -> ContentPromptSetting | None:
        with self.factory() as session:
            return session.get(ContentPromptSetting, provider)

    def upsert_content_prompt_setting(
        self, provider: str, prompt_template: str, prompt_version: str
    ) -> ContentPromptSetting:
        with self.factory() as session:
            setting = session.get(ContentPromptSetting, provider)
            if setting is None:
                setting = ContentPromptSetting(
                    provider=provider,
                    prompt_template=prompt_template,
                    prompt_version=prompt_version,
                )
                session.add(setting)
            else:
                setting.prompt_template = prompt_template
                setting.prompt_version = prompt_version
            session.commit()
            session.refresh(setting)
            return setting

    def create_character(self, payload: CharacterCreate) -> Character:
        with self.factory() as session:
            character = Character(
                name=payload.name,
                slug=payload.slug or slugify(payload.name),
                description=payload.description,
                default_voice_profile_id=payload.default_voice_profile_id,
                default_prompt=payload.default_prompt,
                is_active=payload.is_active,
            )
            session.add(character)
            session.commit()
            session.refresh(character)
            return character

    def list_characters(self) -> tuple[list[Character], int]:
        with self.factory() as session:
            items = list(
                session.scalars(
                    select(Character).order_by(Character.created_at.desc())
                ).all()
            )
            return items, len(items)

    def create_voice_profile(self, payload: VoiceProfileCreate) -> VoiceProfile:
        with self.factory() as session:
            profile = VoiceProfile(
                name=payload.name,
                provider=payload.provider,
                provider_voice_id=payload.provider_voice_id,
                provider_model=payload.provider_model,
                speed=payload.speed,
                stability=payload.stability,
                similarity=payload.similarity,
                style_exaggeration=payload.style_exaggeration,
                extra_settings=payload.extra_settings,
            )
            session.add(profile)
            session.commit()
            session.refresh(profile)
            return profile

    def list_voice_profiles(self) -> tuple[list[VoiceProfile], int]:
        with self.factory() as session:
            items = list(
                session.scalars(
                    select(VoiceProfile).order_by(VoiceProfile.created_at.desc())
                ).all()
            )
            return items, len(items)

    def get_voice_profile(self, profile_id: UUID) -> VoiceProfile | None:
        with self.factory() as session:
            return session.get(VoiceProfile, profile_id)

    def update_voice_profile(
        self, profile_id: UUID, payload: VoiceProfileUpdate
    ) -> VoiceProfile | None:
        with self.factory() as session:
            profile = session.get(VoiceProfile, profile_id)
            if profile is None:
                return None
            profile.name = payload.name
            profile.provider = payload.provider
            profile.provider_voice_id = payload.provider_voice_id
            profile.provider_model = payload.provider_model
            profile.speed = payload.speed
            profile.stability = payload.stability
            profile.similarity = payload.similarity
            profile.style_exaggeration = payload.style_exaggeration
            profile.extra_settings = payload.extra_settings
            session.commit()
            session.refresh(profile)
            return profile

    def delete_voice_profile(self, profile_id: UUID) -> bool:
        with self.factory() as session:
            profile = session.get(VoiceProfile, profile_id)
            if profile is None:
                return False
            render_profiles = list(
                session.scalars(
                    select(RenderProfile).where(
                        RenderProfile.voice_profile_id == profile_id
                    )
                ).all()
            )
            characters = list(
                session.scalars(
                    select(Character).where(
                        Character.default_voice_profile_id == profile_id
                    )
                ).all()
            )
            if render_profiles or characters:
                raise VoiceProfileInUseError(render_profiles, characters)
            session.delete(profile)
            session.commit()
            return True

    def create_voice_preview(
        self, profile_id: UUID, text: str, fingerprint: str
    ) -> tuple[VoicePreview, bool]:
        with self.factory() as session:
            profile = session.get(VoiceProfile, profile_id)
            if profile is None:
                raise LookupError("Voice profile not found")
            existing = session.scalar(
                select(VoicePreview)
                .where(VoicePreview.request_fingerprint == fingerprint)
                .with_for_update()
            )
            if existing is not None:
                now = utc_now()
                if existing.status == "failed":
                    existing.status = "queued"
                    existing.error_message = None
                    existing.updated_at = now
                    session.commit()
                    session.refresh(existing)
                    return existing, True
                if voice_preview_is_stale(existing, now):
                    if existing.status == "queued":
                        existing.updated_at = now
                        session.commit()
                        session.refresh(existing)
                        return existing, True
                    existing.status = "failed"
                    existing.error_message = VOICE_PREVIEW_OUTCOME_UNKNOWN
                    existing.claim_token = None
                    existing.claim_expires_at = None
                    existing.updated_at = now
                    session.commit()
                    session.refresh(existing)
                return existing, False
            preview = VoicePreview(
                voice_profile_id=profile.id,
                text=text,
                status="queued",
                request_fingerprint=fingerprint,
                provider=profile.provider,
                provider_voice_id=profile.provider_voice_id,
                provider_model=profile.provider_model,
                settings_json=voice_settings_snapshot(profile),
            )
            session.add(preview)
            session.commit()
            session.refresh(preview)
            return preview, True

    def get_voice_preview(self, preview_id: UUID) -> VoicePreview | None:
        with self.factory() as session:
            return session.get(VoicePreview, preview_id)

    def claim_voice_preview(self, preview_id: UUID) -> tuple[VoicePreview, UUID] | None:
        claimed_at = utc_now()
        claim_token = uuid4()
        with self.factory() as session:
            claimed = cast(
                CursorResult[Any],
                session.execute(
                    update(VoicePreview)
                    .where(
                        VoicePreview.id == preview_id,
                        VoicePreview.status == "queued",
                    )
                    .values(
                        status="generating",
                        claim_token=claim_token,
                        claim_expires_at=claimed_at + VOICE_PREVIEW_STALE_AFTER,
                        updated_at=claimed_at,
                    )
                ),
            )
            if claimed.rowcount != 1:
                session.rollback()
                return None
            session.commit()
            preview = session.get(VoicePreview, preview_id)
            if preview is None:
                return None
            return preview, claim_token

    def reconcile_voice_preview_claim(self, preview_id: UUID) -> tuple[str, int]:
        checked_at = utc_now()
        with self.factory() as session:
            preview = session.get(VoicePreview, preview_id)
            if preview is None:
                raise LookupError("Voice preview not found")
            if preview.status != "generating":
                return preview.status, 0
            expires_at = preview.claim_expires_at
            if expires_at is None:
                return preview.status, int(VOICE_PREVIEW_STALE_AFTER.total_seconds())
            comparable_now = checked_at
            if expires_at.tzinfo is None:
                comparable_now = checked_at.replace(tzinfo=None)
            remaining = int((expires_at - comparable_now).total_seconds())
            if remaining > 0:
                return preview.status, max(1, remaining)
            expired = cast(
                CursorResult[Any],
                session.execute(
                    update(VoicePreview)
                    .where(
                        VoicePreview.id == preview_id,
                        VoicePreview.status == "generating",
                        VoicePreview.claim_token == preview.claim_token,
                    )
                    .values(
                        status="failed",
                        error_message=VOICE_PREVIEW_OUTCOME_UNKNOWN,
                        claim_token=None,
                        claim_expires_at=None,
                        updated_at=checked_at,
                    )
                ),
            )
            session.commit()
            if expired.rowcount == 1:
                return "failed", 0
            current = session.get(VoicePreview, preview_id)
            if current is None:
                raise LookupError("Voice preview not found")
            return current.status, 0

    def list_voice_previews(self, profile_id: UUID) -> tuple[list[VoicePreview], int]:
        with self.factory() as session:
            items = list(
                session.scalars(
                    select(VoicePreview)
                    .where(VoicePreview.voice_profile_id == profile_id)
                    .order_by(VoicePreview.created_at.desc())
                ).all()
            )
            return items, len(items)

    def delete_voice_preview(self, preview_id: UUID) -> tuple[bool, str | None]:
        with self.factory() as session:
            preview = session.get(VoicePreview, preview_id)
            if preview is None:
                return False, None
            asset_key = preview.asset_key
            session.delete(preview)
            session.commit()
            return True, asset_key

    def get_latest_voice_preview_usage(self) -> VoicePreview | None:
        with self.factory() as session:
            return session.scalar(
                select(VoicePreview)
                .where(VoicePreview.account_remaining_units.is_not(None))
                .order_by(VoicePreview.updated_at.desc())
                .limit(1)
            )

    def update_voice_preview(
        self,
        preview_id: UUID,
        *,
        status: str,
        provider_request_id: str | None = None,
        asset_key: str | None = None,
        content_type: str | None = None,
        filename: str | None = None,
        error_message: str | None = None,
        generated_usage_units: int | None = None,
        account_used_units: int | None = None,
        account_limit_units: int | None = None,
        account_remaining_units: int | None = None,
        usage_resets_at_unix: int | None = None,
        usage_unit: str | None = None,
        claim_token: UUID,
    ) -> VoicePreview | None:
        with self.factory() as session:
            updated = cast(
                CursorResult[Any],
                session.execute(
                    update(VoicePreview)
                    .where(
                        VoicePreview.id == preview_id,
                        VoicePreview.claim_token == claim_token,
                    )
                    .values(
                        status=status,
                        provider_request_id=provider_request_id,
                        asset_key=asset_key,
                        content_type=content_type,
                        filename=filename,
                        error_message=error_message,
                        generated_usage_units=generated_usage_units,
                        account_used_units=account_used_units,
                        account_limit_units=account_limit_units,
                        account_remaining_units=account_remaining_units,
                        usage_resets_at_unix=usage_resets_at_unix,
                        usage_unit=usage_unit,
                        claim_token=None,
                        claim_expires_at=None,
                        updated_at=utc_now(),
                    )
                ),
            )
            if updated.rowcount != 1:
                session.rollback()
                return None
            session.commit()
            preview = session.get(VoicePreview, preview_id)
            if preview is None:
                raise LookupError("Voice preview not found")
            return preview

    def create_render_profile(self, payload: RenderProfileCreate) -> RenderProfile:
        with self.factory() as session:
            if session.get(Character, payload.character_id) is None:
                raise ValueError("Character not found")
            if session.get(VoiceProfile, payload.voice_profile_id) is None:
                raise ValueError("Voice profile not found")
            if (
                payload.workflow_template_id is not None
                and session.get(WorkflowTemplate, payload.workflow_template_id) is None
            ):
                raise ValueError("Workflow template not found")
            profile = RenderProfile(
                name=payload.name,
                character_id=payload.character_id,
                voice_profile_id=payload.voice_profile_id,
                renderer_provider=payload.renderer_provider,
                render_node_id=payload.render_node_id,
                workflow_template_id=payload.workflow_template_id,
                prompt_template=payload.prompt_template,
                negative_prompt_template=payload.negative_prompt_template,
                default_parameters=payload.default_parameters,
                parameter_schema=payload.parameter_schema,
                capabilities=payload.capabilities,
                is_active=payload.is_active,
            )
            session.add(profile)
            session.commit()
            session.refresh(profile)
            return profile

    def create_render_profile_setup(
        self, payload: RenderProfileSetupCreate
    ) -> RenderProfile:
        with self.factory() as session:
            if (
                payload.workflow_template_id is not None
                and session.get(WorkflowTemplate, payload.workflow_template_id) is None
            ):
                raise ValueError("Workflow template not found")
            voice = session.get(VoiceProfile, payload.voice_profile_id)
            if voice is None:
                raise ValueError("Voice profile not found")

            character_slug = slugify(payload.character_name)
            character = session.scalar(
                select(Character).where(Character.slug == character_slug)
            )
            if character is None:
                character = Character(
                    name=payload.character_name,
                    slug=character_slug,
                    default_voice_profile=voice,
                )
            profile = RenderProfile(
                name=payload.profile_name,
                character=character,
                voice_profile=voice,
                renderer_provider=payload.renderer_provider,
                workflow_template_id=payload.workflow_template_id,
            )
            session.add(profile)
            session.commit()
            session.refresh(profile)
            return profile

    def list_render_profiles(self) -> tuple[list[RenderProfile], int]:
        with self.factory() as session:
            items = list(
                session.scalars(
                    select(RenderProfile).order_by(RenderProfile.created_at.desc())
                ).all()
            )
            return items, len(items)

    def get_render_profile(self, profile_id: UUID) -> RenderProfile | None:
        with self.factory() as session:
            return session.get(RenderProfile, profile_id)

    def update_render_profile(
        self, profile_id: UUID, payload: RenderProfileUpdate
    ) -> RenderProfile | None:
        with self.factory() as session:
            profile = session.get(RenderProfile, profile_id)
            if profile is None:
                return None
            if (
                payload.workflow_template_id is not None
                and session.get(WorkflowTemplate, payload.workflow_template_id) is None
            ):
                raise ValueError("Workflow template not found")
            previous_voice_profile_id = profile.voice_profile_id
            profile.name = payload.name
            profile.workflow_template_id = payload.workflow_template_id
            if (
                payload.voice_profile_id is not None
                and session.get(VoiceProfile, payload.voice_profile_id) is None
            ):
                raise ValueError("Voice profile not found")
            profile.voice_profile_id = payload.voice_profile_id
            character = session.get(Character, profile.character_id)
            if character is not None:
                if payload.character_name is not None:
                    character.name = payload.character_name
                if character.default_voice_profile_id == previous_voice_profile_id:
                    character.default_voice_profile_id = payload.voice_profile_id
            session.commit()
            session.refresh(profile)
            return profile

    def delete_render_profile(self, profile_id: UUID) -> bool:
        with self.factory() as session:
            profile = session.get(RenderProfile, profile_id)
            if profile is None:
                return False
            session.delete(profile)
            session.commit()
            return True

    def count_render_profiles(self) -> int:
        with self.factory() as session:
            return int(
                session.scalar(
                    select(func.count(RenderProfile.id)).where(
                        RenderProfile.is_active.is_(True)
                    )
                )
                or 0
            )

    def count_render_profiles_for_workflow(self, template_id: UUID) -> int:
        with self.factory() as session:
            source = session.get(WorkflowTemplate, template_id)
            if source is None:
                return 0
            lineage_ids = select(WorkflowTemplate.id).where(
                WorkflowTemplate.logical_id == source.logical_id
            )
            return int(
                session.scalar(
                    select(func.count(RenderProfile.id)).where(
                        RenderProfile.workflow_template_id.in_(lineage_ids)
                    )
                )
                or 0
            )

    def create_workflow_template(
        self, payload: WorkflowTemplateCreate, checksum: str
    ) -> WorkflowTemplate:
        with self.factory() as session:
            template = WorkflowTemplate(
                id=(template_id := uuid4()),
                logical_id=template_id,
                name=payload.name,
                description=payload.description,
                renderer_provider=payload.renderer_provider,
                workflow_json=payload.workflow_json,
                metadata_json=payload.metadata_json,
                version=payload.version,
                checksum=checksum,
                bindings=[
                    WorkflowParameterBinding(
                        semantic_key=binding.semantic_key,
                        node_id=binding.node_id,
                        input_name=binding.input_name,
                        value_type=binding.value_type,
                        transform=binding.transform,
                        required=binding.required,
                    )
                    for binding in payload.bindings
                ],
            )
            session.add(template)
            session.commit()
            session.refresh(template)
            _ = template.bindings
            return template

    def update_workflow_template(
        self, template_id: UUID, payload: WorkflowTemplateCreate, checksum: str
    ) -> WorkflowTemplate | None:
        with self.factory() as session:
            template = session.scalar(
                select(WorkflowTemplate)
                .options(selectinload(WorkflowTemplate.bindings))
                .where(WorkflowTemplate.id == template_id)
                .with_for_update()
            )
            if template is None:
                return None
            template.name = payload.name
            template.description = payload.description
            template.renderer_provider = payload.renderer_provider
            template.workflow_json = payload.workflow_json
            template.metadata_json = payload.metadata_json
            template.version += 1
            template.checksum = checksum
            template.bindings.clear()
            session.flush()
            template.bindings = [
                WorkflowParameterBinding(
                    semantic_key=binding.semantic_key,
                    node_id=binding.node_id,
                    input_name=binding.input_name,
                    value_type=binding.value_type,
                    transform=binding.transform,
                    required=binding.required,
                )
                for binding in payload.bindings
            ]
            session.commit()
            session.refresh(template)
            _ = template.bindings
            return template

    def list_workflow_templates(self) -> tuple[list[WorkflowTemplate], int]:
        with self.factory() as session:
            versions = list(
                session.scalars(
                    select(WorkflowTemplate)
                    .options(selectinload(WorkflowTemplate.bindings))
                    .order_by(
                        WorkflowTemplate.version.desc(),
                        WorkflowTemplate.created_at.desc(),
                    )
                )
                .unique()
                .all()
            )
            latest: dict[UUID, WorkflowTemplate] = {}
            for item in versions:
                latest.setdefault(item.logical_id, item)
            items = list(latest.values())
            items.sort(key=lambda item: item.updated_at, reverse=True)
            return items, len(items)

    def get_workflow_template(self, template_id: UUID) -> WorkflowTemplate | None:
        with self.factory() as session:
            return session.scalar(
                select(WorkflowTemplate)
                .options(selectinload(WorkflowTemplate.bindings))
                .where(WorkflowTemplate.id == template_id)
            )

    def delete_workflow_template(self, template_id: UUID) -> bool:
        with self.factory() as session:
            template = session.get(WorkflowTemplate, template_id)
            if template is None:
                return False
            lineage_ids = select(WorkflowTemplate.id).where(
                WorkflowTemplate.logical_id == template.logical_id
            )
            if session.scalar(
                select(func.count(RenderProfile.id)).where(
                    RenderProfile.workflow_template_id.in_(lineage_ids)
                )
            ):
                raise ValueError(
                    "Workflow template is connected to one or more render profiles"
                )
            if session.scalar(
                select(func.count(RenderAttempt.id)).where(
                    RenderAttempt.workflow_template_id.in_(lineage_ids)
                )
            ):
                raise ValueError(
                    "Workflow has historical render attempts and cannot be deleted"
                )
            versions = list(
                session.scalars(
                    select(WorkflowTemplate).where(
                        WorkflowTemplate.logical_id == template.logical_id
                    )
                ).all()
            )
            for version in versions:
                session.delete(version)
            session.commit()
            return True


ConfigurationRepository = (
    InMemoryConfigurationRepository | SqlAlchemyConfigurationRepository
)


BatchRepository = InMemoryBatchRepository | SqlAlchemyBatchRepository


def batch_to_dict(batch: Batch) -> dict[str, object]:
    jobs: Sequence[TopicJob] = batch.jobs
    return {
        "id": batch.id,
        "name": batch.name,
        "status": batch.status,
        "default_render_profile_id": batch.default_render_profile_id,
        "target_duration_seconds": batch.target_duration_seconds,
        "auto_fit_duration": batch.auto_fit_duration,
        "job_count": len(jobs),
        "created_at": batch.created_at,
        "updated_at": batch.updated_at,
        "jobs": [job_to_dict(job) for job in jobs],
    }


def topic_summary_to_dict(batch: Batch) -> dict[str, object]:
    jobs: Sequence[TopicJob] = batch.jobs
    statuses = {job.status for job in jobs}
    if jobs and statuses == {JobStatus.COMPLETED.value}:
        topic_status = BatchStatus.COMPLETED.value
    elif JobStatus.FAILED.value in statuses and statuses.issubset(
        {
            JobStatus.COMPLETED.value,
            JobStatus.FAILED.value,
            JobStatus.CANCELLED.value,
        }
    ):
        topic_status = BatchStatus.FAILED.value
    elif statuses.issubset({JobStatus.DRAFT.value, JobStatus.CANCELLED.value}):
        topic_status = BatchStatus.DRAFT.value
    else:
        topic_status = BatchStatus.PROCESSING.value
    return {
        "id": batch.id,
        "name": batch.name,
        "status": topic_status,
        "default_render_profile_id": batch.default_render_profile_id,
        "target_duration_seconds": batch.target_duration_seconds,
        "auto_fit_duration": batch.auto_fit_duration,
        "content_count": len(jobs),
        "created_at": batch.created_at,
        "updated_at": batch.updated_at,
    }


def topic_to_dict(batch: Batch) -> dict[str, object]:
    summary = topic_summary_to_dict(batch)
    jobs = sorted(batch.jobs, key=lambda item: item.content_number)
    return {**summary, "contents": [job_to_dict(job) for job in jobs]}


def job_to_dict(job: TopicJob) -> dict[str, object]:
    # Newly-created batch jobs may be serialized after their session closes.
    # Only list/get queries eager-load media assets; avoid detached lazy loading.
    assets = job.__dict__.get("media_assets", [])
    audio_asset = next(
        (
            asset
            for asset in sorted(assets, key=lambda item: item.created_at, reverse=True)
            if asset.kind == "audio"
        ),
        None,
    )
    audio_assets = [
        asset
        for asset in sorted(assets, key=lambda item: item.created_at, reverse=True)
        if asset.kind in {"audio", "audio_archive"}
    ]
    return {
        "id": job.id,
        "batch_id": job.batch_id,
        "topic": job.topic,
        "content_number": job.content_number,
        "status": job.status,
        "render_profile_id": job.render_profile_id,
        "voice_profile_id": job.voice_profile_id,
        "workflow_template_id": job.workflow_template_id,
        "target_duration_seconds": job.target_duration_seconds,
        "error_message": job.error_message,
        "speech_script": job.speech_script,
        "hook": job.hook,
        "instagram_metadata": job.instagram_metadata,
        "tiktok_metadata": job.tiktok_metadata,
        "llm_provider": job.llm_provider,
        "llm_model": job.llm_model,
        "prompt_version": job.prompt_version,
        "tts_provider": job.tts_provider,
        "tts_voice_id": job.tts_voice_id,
        "tts_model": job.tts_model,
        "tts_provider_request_id": job.tts_provider_request_id,
        "audio_asset": (
            {
                "id": audio_asset.id,
                "job_id": audio_asset.job_id,
                "render_attempt_id": audio_asset.render_attempt_id,
                "kind": audio_asset.kind,
                "filename": audio_asset.filename,
                "content_type": audio_asset.content_type,
                "size_bytes": audio_asset.size_bytes,
                "generation_metadata": audio_asset.generation_metadata,
                "download_url": f"/api/v1/assets/{audio_asset.id}/download",
                "created_at": audio_asset.created_at,
            }
            if audio_asset is not None
            else None
        ),
        "audio_assets": [
            {
                "id": asset.id,
                "job_id": asset.job_id,
                "render_attempt_id": asset.render_attempt_id,
                "kind": asset.kind,
                "filename": asset.filename,
                "content_type": asset.content_type,
                "size_bytes": asset.size_bytes,
                "generation_metadata": asset.generation_metadata,
                "download_url": f"/api/v1/assets/{asset.id}/download",
                "created_at": asset.created_at,
            }
            for asset in audio_assets
        ],
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def character_to_dict(character: Character) -> dict[str, object]:
    return {
        "id": character.id,
        "name": character.name,
        "slug": character.slug,
        "description": character.description,
        "default_voice_profile_id": character.default_voice_profile_id,
        "default_prompt": character.default_prompt,
        "is_active": character.is_active,
        "created_at": character.created_at,
        "updated_at": character.updated_at,
    }


def voice_profile_to_dict(profile: VoiceProfile) -> dict[str, object]:
    return {
        "id": profile.id,
        "name": profile.name,
        "provider": profile.provider,
        "provider_voice_id": profile.provider_voice_id,
        "provider_model": profile.provider_model,
        "speed": profile.speed,
        "stability": profile.stability,
        "similarity": profile.similarity,
        "style_exaggeration": profile.style_exaggeration,
        "extra_settings": profile.extra_settings,
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }


def voice_settings_snapshot(profile: VoiceProfile) -> dict[str, object]:
    extra = profile.extra_settings
    return {
        "speed": profile.speed,
        "stability": profile.stability,
        "similarity_boost": profile.similarity,
        "style": profile.style_exaggeration,
        "use_speaker_boost": extra.get("use_speaker_boost", True),
        "output_format": extra.get("output_format", "mp3_44100_128"),
        "language_code": extra.get("language_code")
        if extra.get("language_override_enabled") is True
        else None,
    }


def voice_preview_to_dict(preview: VoicePreview) -> dict[str, object]:
    return {
        "id": preview.id,
        "voice_profile_id": preview.voice_profile_id,
        "text": preview.text,
        "status": preview.status,
        "provider": preview.provider,
        "provider_request_id": preview.provider_request_id,
        "generated_usage_units": preview.generated_usage_units,
        "account_used_units": preview.account_used_units,
        "account_limit_units": preview.account_limit_units,
        "account_remaining_units": preview.account_remaining_units,
        "usage_resets_at_unix": preview.usage_resets_at_unix,
        "usage_unit": preview.usage_unit,
        "content_type": preview.content_type,
        "filename": preview.filename,
        "error_message": preview.error_message,
        "download_url": f"/api/v1/voice-previews/{preview.id}/audio"
        if preview.status == "completed"
        else None,
        "created_at": preview.created_at,
        "updated_at": preview.updated_at,
    }


def render_profile_to_dict(profile: RenderProfile) -> dict[str, object]:
    return {
        "id": profile.id,
        "name": profile.name,
        "character_id": profile.character_id,
        "voice_profile_id": profile.voice_profile_id,
        "renderer_provider": profile.renderer_provider,
        "render_node_id": profile.render_node_id,
        "workflow_template_id": profile.workflow_template_id,
        "prompt_template": profile.prompt_template,
        "negative_prompt_template": profile.negative_prompt_template,
        "default_parameters": profile.default_parameters,
        "parameter_schema": profile.parameter_schema,
        "capabilities": profile.capabilities,
        "is_active": profile.is_active,
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }


def workflow_template_to_dict(template: WorkflowTemplate) -> dict[str, object]:
    return {
        "id": template.id,
        "logical_id": template.logical_id,
        "name": template.name,
        "description": template.description,
        "renderer_provider": template.renderer_provider,
        "workflow_json": template.workflow_json,
        "metadata_json": template.metadata_json,
        "version": template.version,
        "checksum": template.checksum,
        "bindings": [
            {
                "id": binding.id,
                "semantic_key": binding.semantic_key,
                "node_id": binding.node_id,
                "input_name": binding.input_name,
                "value_type": binding.value_type,
                "transform": binding.transform,
                "required": binding.required,
            }
            for binding in template.bindings
        ],
        "created_at": template.created_at,
        "updated_at": template.updated_at,
    }
