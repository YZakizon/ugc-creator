"""Add media generation metadata.

Revision ID: 0018_media_generation_metadata
Revises: 0017_topic_content_numbers
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_media_generation_metadata"
down_revision: str | None = "0017_topic_content_numbers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "media_assets", sa.Column("generation_metadata", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("media_assets", "generation_metadata")
