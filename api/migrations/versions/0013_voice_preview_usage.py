"""Persist normalized TTS generation and account usage snapshots."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_voice_preview_usage"
down_revision: str | None = "0012_provider_reconciliation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "voice_previews",
        sa.Column("generated_usage_units", sa.Integer(), nullable=True),
    )
    op.add_column(
        "voice_previews", sa.Column("account_used_units", sa.Integer(), nullable=True)
    )
    op.add_column(
        "voice_previews", sa.Column("account_limit_units", sa.Integer(), nullable=True)
    )
    op.add_column(
        "voice_previews",
        sa.Column("account_remaining_units", sa.Integer(), nullable=True),
    )
    op.add_column(
        "voice_previews", sa.Column("usage_resets_at_unix", sa.Integer(), nullable=True)
    )
    op.add_column(
        "voice_previews", sa.Column("usage_unit", sa.String(length=32), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("voice_previews", "usage_unit")
    op.drop_column("voice_previews", "usage_resets_at_unix")
    op.drop_column("voice_previews", "account_remaining_units")
    op.drop_column("voice_previews", "account_limit_units")
    op.drop_column("voice_previews", "account_used_units")
    op.drop_column("voice_previews", "generated_usage_units")
