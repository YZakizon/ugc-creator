"""Add stable per-topic content numbers.

Revision ID: 0017_topic_content_numbers
Revises: 0016_job_generation_overrides
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_topic_content_numbers"
down_revision: str | None = "0016_job_generation_overrides"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("topic_jobs", sa.Column("content_number", sa.Integer()))
    op.execute(
        """
        WITH ranked AS (
            SELECT id, ROW_NUMBER() OVER (
                PARTITION BY batch_id ORDER BY created_at, id
            ) AS content_number
            FROM topic_jobs
        )
        UPDATE topic_jobs
        SET content_number = ranked.content_number
        FROM ranked
        WHERE topic_jobs.id = ranked.id
        """
    )
    op.alter_column(
        "topic_jobs",
        "content_number",
        existing_type=sa.Integer(),
        nullable=False,
        server_default="1",
    )
    op.create_unique_constraint(
        "uq_topic_content_number", "topic_jobs", ["batch_id", "content_number"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_topic_content_number", "topic_jobs", type_="unique")
    op.drop_column("topic_jobs", "content_number")
