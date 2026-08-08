"""Add provider claims and queued workflow binding snapshots.

Revision ID: 0011_provider_claims_snapshots
Revises: 0010_workflow_update_cleanup
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_provider_claims_snapshots"
down_revision: str | None = "0010_workflow_update_cleanup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "render_attempts",
        sa.Column("binding_snapshot", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "render_attempts",
        sa.Column("submission_claim_expires_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_column("render_attempts", "submission_claim_expires_at")
    op.drop_column("render_attempts", "binding_snapshot")
