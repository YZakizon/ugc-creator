from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.core.statuses import BatchStatus, JobStatus


class BatchCreate(BaseModel):
    name: str = Field(default="Untitled batch", min_length=1, max_length=160)
    topics: list[str] = Field(min_length=1, max_length=100)
    default_render_profile_id: UUID | None = None
    target_duration_seconds: int = Field(default=30, ge=5, le=180)
    auto_fit_duration: bool = True

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Batch name cannot be empty")
        return cleaned

    @field_validator("topics")
    @classmethod
    def clean_topics(cls, value: list[str]) -> list[str]:
        topics = [topic.strip() for topic in value if topic.strip()]
        if not topics:
            raise ValueError("At least one topic is required")
        return topics


class JobRead(BaseModel):
    id: UUID
    batch_id: UUID
    topic: str
    status: JobStatus
    render_profile_id: UUID | None
    target_duration_seconds: int
    error_message: str | None
    speech_script: str | None
    hook: str | None
    instagram_metadata: dict[str, object] | None
    tiktok_metadata: dict[str, object] | None
    llm_provider: str | None
    llm_model: str | None
    prompt_version: str | None
    created_at: datetime
    updated_at: datetime


class BatchRead(BaseModel):
    id: UUID
    name: str
    status: BatchStatus
    default_render_profile_id: UUID | None
    target_duration_seconds: int
    auto_fit_duration: bool
    job_count: int
    created_at: datetime
    updated_at: datetime
    jobs: list[JobRead] = Field(default_factory=list)


class BatchList(BaseModel):
    items: list[BatchRead]
    total: int
    limit: int
    offset: int


class DashboardSummary(BaseModel):
    in_progress: int
    ready_to_render: int
    completed_videos: int
    render_profiles: int
    recent_jobs: list[JobRead]


class CharacterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    slug: str | None = Field(default=None, max_length=180)
    description: str | None = None
    default_voice_profile_id: UUID | None = None
    default_prompt: str | None = None
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def clean_character_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Character name cannot be empty")
        return cleaned


class CharacterRead(BaseModel):
    id: UUID
    name: str
    slug: str
    description: str | None
    default_voice_profile_id: UUID | None
    default_prompt: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class VoiceProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    provider: str = Field(min_length=1, max_length=64)
    provider_voice_id: str = Field(min_length=1, max_length=160)
    provider_model: str | None = Field(default=None, max_length=160)
    speed: float = Field(default=1.0, gt=0, le=2)
    stability: float | None = Field(default=0.5, ge=0, le=1)
    similarity: float | None = Field(default=0.75, ge=0, le=1)
    style_exaggeration: float | None = Field(default=0.5, ge=0, le=1)
    extra_settings: dict[str, object] = Field(default_factory=dict)


class VoiceProfileUpdate(VoiceProfileCreate):
    pass


class VoiceProfileRead(BaseModel):
    id: UUID
    name: str
    provider: str
    provider_voice_id: str
    provider_model: str | None
    speed: float
    stability: float | None
    similarity: float | None
    style_exaggeration: float | None
    extra_settings: dict[str, object]
    created_at: datetime
    updated_at: datetime


class RenderProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    character_id: UUID
    voice_profile_id: UUID
    renderer_provider: str = Field(min_length=1, max_length=64)
    render_node_id: UUID | None = None
    workflow_template_id: UUID | None = None
    prompt_template: str = ""
    negative_prompt_template: str | None = None
    default_parameters: dict[str, object] = Field(default_factory=dict)
    parameter_schema: dict[str, object] = Field(default_factory=dict)
    capabilities: dict[str, object] = Field(default_factory=dict)
    is_active: bool = True


class RenderProfileSetupCreate(BaseModel):
    profile_name: str = Field(min_length=1, max_length=160)
    character_name: str = Field(min_length=1, max_length=160)
    voice_profile_id: UUID
    renderer_provider: str = Field(default="comfyui", min_length=1, max_length=64)
    workflow_template_id: UUID | None = None


class RenderProfileUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    character_name: str | None = Field(default=None, min_length=1, max_length=160)
    voice_profile_id: UUID | None = None
    workflow_template_id: UUID | None = None


class RenderProfileRead(BaseModel):
    id: UUID
    name: str
    character_id: UUID
    voice_profile_id: UUID | None
    renderer_provider: str
    render_node_id: UUID | None
    workflow_template_id: UUID | None
    prompt_template: str
    negative_prompt_template: str | None
    default_parameters: dict[str, object]
    parameter_schema: dict[str, object]
    capabilities: dict[str, object]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CharacterList(BaseModel):
    items: list[CharacterRead]
    total: int


class VoiceProfileList(BaseModel):
    items: list[VoiceProfileRead]
    total: int


class VoicePreviewCreate(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


class VoicePreviewRead(BaseModel):
    id: UUID
    voice_profile_id: UUID
    text: str
    status: Literal["queued", "generating", "completed", "failed"]
    provider: str
    provider_request_id: str | None
    content_type: str | None
    filename: str | None
    error_message: str | None
    download_url: str | None
    created_at: datetime
    updated_at: datetime


class RenderProfileList(BaseModel):
    items: list[RenderProfileRead]
    total: int


WorkflowValueType = Literal[
    "string",
    "template",
    "integer",
    "number",
    "boolean",
]


class WorkflowParameterBindingCreate(BaseModel):
    semantic_key: str = Field(min_length=1, max_length=64)
    node_id: str = Field(min_length=1, max_length=160)
    input_name: str = Field(min_length=1, max_length=160)
    value_type: WorkflowValueType
    transform: dict[str, object] = Field(default_factory=dict)
    required: bool = True


class WorkflowParameterBindingRead(WorkflowParameterBindingCreate):
    id: UUID


class WorkflowTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = None
    renderer_provider: Literal["comfyui"] = "comfyui"
    workflow_json: dict[str, object]
    metadata_json: dict[str, object] = Field(default_factory=dict)
    version: int = Field(default=1, ge=1)
    bindings: list[WorkflowParameterBindingCreate] = Field(default_factory=list)


class WorkflowTemplateRead(BaseModel):
    id: UUID
    name: str
    description: str | None
    renderer_provider: str
    workflow_json: dict[str, object]
    metadata_json: dict[str, object]
    version: int
    checksum: str
    bindings: list[WorkflowParameterBindingRead]
    created_at: datetime
    updated_at: datetime


class WorkflowTemplateList(BaseModel):
    items: list[WorkflowTemplateRead]
    total: int


class WorkflowMediaUpload(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1, max_length=35_000_000)
    input_type: Literal["image", "audio"]


class WorkflowMediaUploadRead(BaseModel):
    asset_key: str
    filename: str
    input_type: Literal["image", "audio"]
