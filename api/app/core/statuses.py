from enum import StrEnum


class BatchStatus(StrEnum):
    DRAFT = "draft"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobStatus(StrEnum):
    DRAFT = "draft"
    GENERATING_CONTENT = "generating_content"
    CONTENT_READY = "content_ready"
    GENERATING_TTS = "generating_tts"
    TTS_READY = "tts_ready"
    FITTING_DURATION = "fitting_duration"
    READY_TO_RENDER = "ready_to_render"
    QUEUED = "queued"
    SUBMITTING_RENDER = "submitting_render"
    RENDERING = "rendering"
    DOWNLOADING_OUTPUT = "downloading_output"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
