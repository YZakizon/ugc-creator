from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.statuses import BatchStatus, JobStatus
from app.db.base import Base, TimestampMixin, UUIDPrimaryKey


class Batch(TimestampMixin, Base):
    __tablename__ = "batches"

    id: Mapped[UUIDPrimaryKey]
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default=BatchStatus.DRAFT.value, nullable=False
    )
    default_render_profile_id: Mapped[UUID | None] = mapped_column(nullable=True)
    target_duration_seconds: Mapped[int] = mapped_column(Integer, default=30)
    auto_fit_duration: Mapped[bool] = mapped_column(default=True, nullable=False)

    jobs: Mapped[list["TopicJob"]] = relationship(
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by="TopicJob.created_at",
    )


class TopicJob(TimestampMixin, Base):
    __tablename__ = "topic_jobs"
    __table_args__ = (Index("ix_topic_jobs_batch_id_status", "batch_id", "status"),)

    id: Mapped[UUIDPrimaryKey]
    batch_id: Mapped[UUID] = mapped_column(
        ForeignKey("batches.id", ondelete="CASCADE"), nullable=False
    )
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(40), default=JobStatus.DRAFT.value, nullable=False
    )
    render_profile_id: Mapped[UUID | None] = mapped_column(nullable=True)
    target_duration_seconds: Mapped[int] = mapped_column(Integer, default=30)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    speech_script: Mapped[str | None] = mapped_column(Text, nullable=True)
    hook: Mapped[str | None] = mapped_column(Text, nullable=True)
    instagram_metadata: Mapped[dict[str, object] | None] = mapped_column(
        JSON, nullable=True
    )
    tiktok_metadata: Mapped[dict[str, object] | None] = mapped_column(
        JSON, nullable=True
    )
    llm_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    batch: Mapped[Batch] = relationship(back_populates="jobs")
    render_attempts: Mapped[list["RenderAttempt"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class VoiceProfile(TimestampMixin, Base):
    __tablename__ = "voice_profiles"

    id: Mapped[UUIDPrimaryKey]
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_voice_id: Mapped[str] = mapped_column(String(160), nullable=False)
    provider_model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    speed: Mapped[float] = mapped_column(default=1.0, nullable=False)
    stability: Mapped[float | None] = mapped_column(nullable=True)
    similarity: Mapped[float | None] = mapped_column(nullable=True)
    style_exaggeration: Mapped[float | None] = mapped_column(nullable=True)
    extra_settings: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)


class VoicePreview(TimestampMixin, Base):
    __tablename__ = "voice_previews"
    __table_args__ = (
        Index("ix_voice_previews_voice_created", "voice_profile_id", "created_at"),
        UniqueConstraint("request_fingerprint", name="uq_voice_previews_fingerprint"),
    )

    id: Mapped[UUIDPrimaryKey]
    voice_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("voice_profiles.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_voice_id: Mapped[str] = mapped_column(String(160), nullable=False)
    provider_model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    settings_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    provider_request_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    asset_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    claim_token: Mapped[UUID | None] = mapped_column(nullable=True)
    claim_expires_at: Mapped[datetime | None] = mapped_column(nullable=True)

    voice_profile: Mapped[VoiceProfile] = relationship()


class Character(TimestampMixin, Base):
    __tablename__ = "characters"

    id: Mapped[UUIDPrimaryKey]
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(180), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_voice_profile_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("voice_profiles.id", ondelete="SET NULL"), nullable=True
    )
    default_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    default_voice_profile: Mapped[VoiceProfile | None] = relationship()


class RenderProfile(TimestampMixin, Base):
    __tablename__ = "render_profiles"
    __table_args__ = (
        Index("ix_render_profiles_active", "is_active"),
        Index("ix_render_profiles_provider", "renderer_provider"),
    )

    id: Mapped[UUIDPrimaryKey]
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    character_id: Mapped[UUID] = mapped_column(
        ForeignKey("characters.id", ondelete="RESTRICT"), nullable=False
    )
    voice_profile_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("voice_profiles.id", ondelete="RESTRICT"), nullable=True
    )
    renderer_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    render_node_id: Mapped[UUID | None] = mapped_column(nullable=True)
    workflow_template_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workflow_templates.id", ondelete="RESTRICT"), nullable=True
    )
    prompt_template: Mapped[str] = mapped_column(Text, default="", nullable=False)
    negative_prompt_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_parameters: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    parameter_schema: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    capabilities: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    character: Mapped[Character] = relationship()
    voice_profile: Mapped[VoiceProfile | None] = relationship()


class RenderNode(TimestampMixin, Base):
    __tablename__ = "render_nodes"

    id: Mapped[UUIDPrimaryKey]
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), default="comfyui", nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    health_status: Mapped[str] = mapped_column(
        String(32), default="unknown", nullable=False
    )
    health_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    health_checked_at: Mapped[datetime | None] = mapped_column(nullable=True)


class RenderAttempt(TimestampMixin, Base):
    __tablename__ = "render_attempts"
    __table_args__ = (
        Index("ix_render_attempts_job_created", "job_id", "created_at"),
        Index("ix_render_attempts_external_job", "provider", "external_job_id"),
    )

    id: Mapped[UUIDPrimaryKey]
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("topic_jobs.id", ondelete="CASCADE"), nullable=False
    )
    render_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("render_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    render_node_id: Mapped[UUID] = mapped_column(
        ForeignKey("render_nodes.id", ondelete="RESTRICT"), nullable=False
    )
    workflow_template_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflow_templates.id", ondelete="RESTRICT"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="queued", nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    external_job_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    workflow_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    binding_snapshot: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    effective_values: Mapped[dict[str, object]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(nullable=True)
    submission_started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    submission_claim_expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finalization_claim_expires_at: Mapped[datetime | None] = mapped_column(
        nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    job: Mapped[TopicJob] = relationship(back_populates="render_attempts")
    assets: Mapped[list["MediaAsset"]] = relationship(
        back_populates="render_attempt", cascade="all, delete-orphan"
    )


class MediaAsset(TimestampMixin, Base):
    __tablename__ = "media_assets"
    __table_args__ = (
        Index("ix_media_assets_job_kind", "job_id", "kind"),
        UniqueConstraint(
            "render_attempt_id", "kind", name="uq_media_assets_attempt_kind"
        ),
    )

    id: Mapped[UUIDPrimaryKey]
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("topic_jobs.id", ondelete="CASCADE"), nullable=False
    )
    render_attempt_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("render_attempts.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    render_attempt: Mapped[RenderAttempt | None] = relationship(back_populates="assets")


class WorkflowTemplate(TimestampMixin, Base):
    __tablename__ = "workflow_templates"
    __table_args__ = (
        Index("ix_workflow_templates_provider", "renderer_provider"),
        Index("ix_workflow_templates_logical_version", "logical_id", "version"),
    )

    id: Mapped[UUIDPrimaryKey]
    logical_id: Mapped[UUID] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    renderer_provider: Mapped[str] = mapped_column(
        String(64), default="comfyui", nullable=False
    )
    workflow_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)

    bindings: Mapped[list["WorkflowParameterBinding"]] = relationship(
        back_populates="workflow_template",
        cascade="all, delete-orphan",
        order_by="WorkflowParameterBinding.semantic_key",
    )


@event.listens_for(WorkflowTemplate, "before_insert")
def initialize_workflow_logical_id(
    _mapper: object, _connection: object, template: WorkflowTemplate
) -> None:
    if template.id is None:
        template.id = uuid4()
    if template.logical_id is None:
        template.logical_id = template.id


class WorkflowParameterBinding(Base):
    __tablename__ = "workflow_parameter_bindings"
    __table_args__ = (
        UniqueConstraint(
            "workflow_template_id",
            "semantic_key",
            name="uq_workflow_bindings_template_key",
        ),
    )

    id: Mapped[UUIDPrimaryKey]
    workflow_template_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflow_templates.id", ondelete="CASCADE"), nullable=False
    )
    semantic_key: Mapped[str] = mapped_column(String(64), nullable=False)
    node_id: Mapped[str] = mapped_column(String(160), nullable=False)
    input_name: Mapped[str] = mapped_column(String(160), nullable=False)
    value_type: Mapped[str] = mapped_column(String(32), nullable=False)
    transform: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    required: Mapped[bool] = mapped_column(default=True, nullable=False)

    workflow_template: Mapped[WorkflowTemplate] = relationship(
        back_populates="bindings"
    )
