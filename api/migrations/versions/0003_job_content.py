"""Store structured LLM content on topic jobs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_job_content"
down_revision: str | None = "0002_configuration_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("topic_jobs", sa.Column("speech_script", sa.Text(), nullable=True))
    op.add_column("topic_jobs", sa.Column("hook", sa.Text(), nullable=True))
    op.add_column(
        "topic_jobs",
        sa.Column("instagram_metadata", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "topic_jobs", sa.Column("tiktok_metadata", postgresql.JSONB(), nullable=True)
    )
    op.add_column(
        "topic_jobs", sa.Column("llm_provider", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "topic_jobs", sa.Column("llm_model", sa.String(length=160), nullable=True)
    )
    op.add_column(
        "topic_jobs", sa.Column("prompt_version", sa.String(length=64), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("topic_jobs", "prompt_version")
    op.drop_column("topic_jobs", "llm_model")
    op.drop_column("topic_jobs", "llm_provider")
    op.drop_column("topic_jobs", "tiktok_metadata")
    op.drop_column("topic_jobs", "instagram_metadata")
    op.drop_column("topic_jobs", "hook")
    op.drop_column("topic_jobs", "speech_script")
