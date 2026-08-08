"""Allow render profiles to temporarily disconnect their voice profile.

Revision ID: 0007_nullable_voice
Revises: 0006_voice_previews
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_nullable_voice"
down_revision: str | None = "0006_voice_previews"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "render_profiles",
        "voice_profile_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "render_profiles",
        "voice_profile_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
