"""Preserve render output filenames after media deletion.

Revision ID: 0019_render_output_tombstone
Revises: 0018_media_generation_metadata
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_render_output_tombstone"
down_revision: str | None = "0018_media_generation_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "render_attempts", sa.Column("output_filename", sa.String(255), nullable=True)
    )
    op.add_column(
        "render_attempts", sa.Column("output_deleted_at", sa.DateTime(), nullable=True)
    )
    op.execute(
        """
        UPDATE render_attempts
        SET output_filename = media_assets.filename
        FROM media_assets
        WHERE media_assets.render_attempt_id = render_attempts.id
          AND media_assets.kind = 'video'
        """
    )


def downgrade() -> None:
    op.drop_column("render_attempts", "output_deleted_at")
    op.drop_column("render_attempts", "output_filename")
