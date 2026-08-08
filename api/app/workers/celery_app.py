import os

from celery import Celery

celery_app = Celery(
    "ugc_creator",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
)


def ping() -> str:
    """Provide a smoke-test task while the domain task set is built."""

    return "pong"


celery_app.task(name="ugc_creator.ping")(ping)

# Import task modules after the app is configured so Celery registers them.
from app.workers import content_tasks, render_tasks, tts_tasks  # noqa: E402,F401
