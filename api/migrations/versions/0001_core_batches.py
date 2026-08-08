"""Create the initial batch and topic job tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_core_batches"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    op.create_table(
        "batches",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("default_render_profile_id", uuid_type, nullable=True),
        sa.Column("target_duration_seconds", sa.Integer(), nullable=False),
        sa.Column("auto_fit_duration", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "topic_jobs",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("batch_id", uuid_type, nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("render_profile_id", uuid_type, nullable=True),
        sa.Column("target_duration_seconds", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["batches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_topic_jobs_batch_id_status",
        "topic_jobs",
        ["batch_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_topic_jobs_batch_id_status", table_name="topic_jobs")
    op.drop_table("topic_jobs")
    op.drop_table("batches")
