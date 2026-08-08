from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.providers.llm.contracts import LLMProviderError
from app.providers.tts.contracts import TTSProviderError
from app.workers import content_tasks, tts_tasks
from app.workers.retry import retry_provider_error


class RetryScheduled(Exception):
    pass


class FakeRequest:
    def __init__(self, retries: int) -> None:
        self.retries = retries


class FakeTask:
    max_retries = 3

    def __init__(self, retries: int) -> None:
        self.request = FakeRequest(retries)
        self.countdown: int | None = None

    def retry(self, *, exc: Exception, countdown: int) -> RetryScheduled:
        self.countdown = countdown
        return RetryScheduled(str(exc))


def test_retriable_provider_error_schedules_bounded_retry() -> None:
    task = FakeTask(retries=1)

    with pytest.raises(RetryScheduled):
        retry_provider_error(
            task,  # type: ignore[arg-type]
            RuntimeError("temporary"),
            retriable=True,
        )

    assert task.countdown == 2


@pytest.mark.parametrize("retriable,retries", [(False, 0), (True, 3)])
def test_non_retriable_or_exhausted_error_does_not_schedule_retry(
    retriable: bool, retries: int
) -> None:
    task = FakeTask(retries=retries)

    retry_provider_error(
        task,  # type: ignore[arg-type]
        RuntimeError("final"),
        retriable=retriable,
    )

    assert task.countdown is None


def test_content_task_retries_typed_transient_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = LLMProviderError(
        "OpenAI is temporarily unavailable.",
        category="provider_unavailable",
        retriable=True,
    )
    monkeypatch.delenv("UGC_FAKE_PROVIDERS", raising=False)
    monkeypatch.setattr(content_tasks, "create_database_engine", object)
    monkeypatch.setattr(content_tasks, "session_factory", lambda _engine: object())
    monkeypatch.setattr(
        content_tasks,
        "run_content_generation",
        lambda *_args: (_ for _ in ()).throw(error),
    )
    scheduled: list[tuple[Exception, int]] = []

    def schedule_retry(*, exc: Exception, countdown: int) -> RetryScheduled:
        scheduled.append((exc, countdown))
        return RetryScheduled(str(exc))

    monkeypatch.setattr(content_tasks.generate_job_content, "retry", schedule_retry)

    with pytest.raises(RetryScheduled):
        content_tasks.generate_job_content.run(str(uuid4()))

    assert scheduled == [(error, 1)]


def test_tts_task_requeues_transient_failure_before_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview_id = uuid4()
    updates: list[dict[str, object]] = []
    preview = SimpleNamespace(
        id=preview_id,
        status="queued",
        asset_key=None,
        settings_json={},
        text="Preview this speech.",
        provider_voice_id="voice-id",
        provider_model=None,
    )

    class FakeRepository:
        def get_voice_preview(self, _preview_id: object) -> object:
            return preview

        def update_voice_preview(self, _preview_id: object, **values: object) -> object:
            updates.append(values)
            return SimpleNamespace(status=values["status"])

    class FailingProvider:
        async def synthesize(self, _request: object) -> object:
            raise TTSProviderError(
                "ElevenLabs is temporarily unavailable.",
                category="provider_unavailable",
                retriable=True,
                provider_request_id="tts-request",
            )

    monkeypatch.delenv("UGC_FAKE_PROVIDERS", raising=False)
    monkeypatch.setattr(tts_tasks, "create_database_engine", object)
    monkeypatch.setattr(tts_tasks, "session_factory", lambda _engine: object())
    monkeypatch.setattr(
        tts_tasks,
        "SqlAlchemyConfigurationRepository",
        lambda _factory: FakeRepository(),
    )
    monkeypatch.setattr(tts_tasks, "ElevenLabsTTSProvider", FailingProvider)
    scheduled: list[tuple[Exception, int]] = []

    def schedule_retry(*, exc: Exception, countdown: int) -> RetryScheduled:
        scheduled.append((exc, countdown))
        return RetryScheduled(str(exc))

    monkeypatch.setattr(tts_tasks.generate_voice_preview, "retry", schedule_retry)

    with pytest.raises(RetryScheduled):
        tts_tasks.generate_voice_preview.run(str(preview_id))

    assert [update["status"] for update in updates] == ["generating", "queued"]
    assert updates[-1]["provider_request_id"] == "tts-request"
    assert scheduled[0][1] == 1
