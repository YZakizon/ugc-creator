from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.statuses import BatchStatus, JobStatus

UUIDPrimaryKey = Annotated[
    UUID,
    mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4),
]


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


__all__ = ["Base", "BatchStatus", "JobStatus", "TimestampMixin", "UUIDPrimaryKey"]
