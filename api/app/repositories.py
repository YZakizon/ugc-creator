import re
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from app.core.statuses import BatchStatus, JobStatus
from app.db.models import (
    Batch,
    Character,
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
    VoiceProfileCreate,
    VoiceProfileUpdate,
    WorkflowTemplateCreate,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


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
            created_at=now,
            updated_at=now,
        )
        batch.jobs = []
        for topic in payload.topics:
            job = TopicJob(
                id=uuid4(),
                batch_id=batch.id,
                topic=topic,
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

    def list_batches(self, limit: int, offset: int) -> tuple[list[Batch], int]:
        batches = sorted(
            self.batches.values(), key=lambda item: item.created_at, reverse=True
        )
        return batches[offset : offset + limit], len(batches)

    def get_batch(self, batch_id: UUID) -> Batch | None:
        return self.batches.get(batch_id)

    def get_job(self, job_id: UUID) -> TopicJob | None:
        return self.jobs.get(job_id)

    def queue_job_for_content(self, job_id: UUID) -> TopicJob | None:
        job = self.jobs.get(job_id)
        if job is not None:
            job.status = JobStatus.QUEUED.value
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
            )
            batch.jobs = [
                TopicJob(
                    topic=topic,
                    status=JobStatus.DRAFT.value,
                    render_profile_id=payload.default_render_profile_id,
                    target_duration_seconds=payload.target_duration_seconds,
                )
                for topic in payload.topics
            ]
            session.add(batch)
            session.commit()
            session.refresh(batch)
            # Load the relationship while the session is still attached.
            _ = batch.jobs
            return batch

    def list_batches(self, limit: int, offset: int) -> tuple[list[Batch], int]:
        with self.factory() as session:
            query = (
                select(Batch)
                .options(selectinload(Batch.jobs))
                .order_by(Batch.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            batches = list(session.scalars(query).unique().all())
            total = session.scalar(select(func.count(Batch.id))) or 0
            return batches, total

    def get_batch(self, batch_id: UUID) -> Batch | None:
        with self.factory() as session:
            batch = session.scalar(
                select(Batch)
                .options(selectinload(Batch.jobs))
                .where(Batch.id == batch_id)
            )
            return batch

    def get_job(self, job_id: UUID) -> TopicJob | None:
        with self.factory() as session:
            return session.get(TopicJob, job_id)

    def queue_job_for_content(self, job_id: UUID) -> TopicJob | None:
        with self.factory() as session:
            job = session.get(TopicJob, job_id)
            if job is None:
                return None
            job.status = JobStatus.QUEUED.value
            session.commit()
            session.refresh(job)
            return job

    def list_jobs(self, limit: int = 5) -> list[TopicJob]:
        with self.factory() as session:
            return list(
                session.scalars(
                    select(TopicJob).order_by(TopicJob.created_at.desc()).limit(limit)
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
            if existing.status == "failed":
                existing.status = "queued"
                existing.error_message = None
                existing.updated_at = utc_now()
                return existing, True
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
                select(VoicePreview).where(
                    VoicePreview.request_fingerprint == fingerprint
                )
            )
            if existing is not None:
                if existing.status == "failed":
                    existing.status = "queued"
                    existing.error_message = None
                    existing.updated_at = utc_now()
                    session.commit()
                    session.refresh(existing)
                    return existing, True
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
    ) -> VoicePreview:
        with self.factory() as session:
            preview = session.get(VoicePreview, preview_id)
            if preview is None:
                raise LookupError("Voice preview not found")
            preview.status = status
            preview.provider_request_id = provider_request_id
            preview.asset_key = asset_key
            preview.content_type = content_type
            preview.filename = filename
            preview.error_message = error_message
            preview.updated_at = utc_now()
            session.commit()
            session.refresh(preview)
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


def job_to_dict(job: TopicJob) -> dict[str, object]:
    return {
        "id": job.id,
        "batch_id": job.batch_id,
        "topic": job.topic,
        "status": job.status,
        "render_profile_id": job.render_profile_id,
        "target_duration_seconds": job.target_duration_seconds,
        "error_message": job.error_message,
        "speech_script": job.speech_script,
        "hook": job.hook,
        "instagram_metadata": job.instagram_metadata,
        "tiktok_metadata": job.tiktok_metadata,
        "llm_provider": job.llm_provider,
        "llm_model": job.llm_model,
        "prompt_version": job.prompt_version,
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
