from celery import Task


def retry_provider_error(
    task: Task,
    error: Exception,
    *,
    retriable: bool,
) -> None:
    max_retries = task.max_retries or 0
    retries = task.request.retries
    if retriable and retries < max_retries:
        countdown = min(60, 2 ** max(0, retries))
        raise task.retry(exc=error, countdown=countdown)
