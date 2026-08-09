"""Persist editable content-generation prompt settings."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_content_prompt_settings"
down_revision: str | None = "0013_voice_preview_usage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "content_prompt_settings",
        sa.Column("provider", sa.String(length=64), primary_key=True),
        sa.Column("prompt_template", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("content_prompt_settings")
