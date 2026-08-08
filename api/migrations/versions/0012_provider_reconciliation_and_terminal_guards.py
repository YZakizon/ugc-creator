"""Add provider reconciliation and terminal-state guards.

Revision ID: 0012_provider_reconciliation
Revises: 0011_provider_claims_snapshots
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_provider_reconciliation"
down_revision: str | None = "0011_provider_claims_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("voice_previews", sa.Column("claim_token", sa.Uuid(), nullable=True))
    op.add_column(
        "voice_previews",
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "render_attempts",
        sa.Column("submission_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "render_attempts",
        sa.Column(
            "finalization_claim_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.execute(
        """
        DELETE FROM media_assets
        WHERE id IN (
            SELECT id
            FROM (
                SELECT id,
                       row_number() OVER (
                           PARTITION BY render_attempt_id, kind
                           ORDER BY created_at, id
                       ) AS duplicate_number
                FROM media_assets
                WHERE render_attempt_id IS NOT NULL
            ) duplicated_assets
            WHERE duplicate_number > 1
        )
        """
    )
    op.create_unique_constraint(
        "uq_media_assets_attempt_kind",
        "media_assets",
        ["render_attempt_id", "kind"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_media_assets_attempt_kind", "media_assets", type_="unique")
    op.drop_column("render_attempts", "finalization_claim_expires_at")
    op.drop_column("render_attempts", "submission_started_at")
    op.drop_column("voice_previews", "claim_expires_at")
    op.drop_column("voice_previews", "claim_token")
