"""Add on-demand video draft metadata and render overrides.

Revision ID: 0020_on_demand_videos
Revises: 0019_render_output_tombstone
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_on_demand_videos"
down_revision: str | None = "0019_render_output_tombstone"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "batches",
        sa.Column(
            "creation_mode",
            sa.String(length=32),
            nullable=False,
            server_default="topic",
        ),
    )
    op.add_column(
        "topic_jobs",
        sa.Column(
            "render_overrides",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.alter_column("batches", "creation_mode", server_default=None)
    op.alter_column("topic_jobs", "render_overrides", server_default=None)


def downgrade() -> None:
    op.drop_column("topic_jobs", "render_overrides")
    op.drop_column("batches", "creation_mode")
