"""Persist asynchronous voice profile previews."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_voice_previews"
down_revision: str | None = "0005_render_profile_workflow_fk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Development reloads historically call Base.metadata.create_all(). If that
    # process observed this model before Alembic ran, adopt the identical table
    # and let Alembic record this revision instead of failing startup.
    if sa.inspect(op.get_bind()).has_table("voice_previews"):
        return
    op.create_table(
        "voice_previews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("voice_profile_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("provider_voice_id", sa.String(length=160), nullable=False),
        sa.Column("provider_model", sa.String(length=160), nullable=True),
        sa.Column("settings_json", sa.JSON(), nullable=False),
        sa.Column("provider_request_id", sa.String(length=160), nullable=True),
        sa.Column("asset_key", sa.String(length=500), nullable=True),
        sa.Column("content_type", sa.String(length=100), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["voice_profile_id"], ["voice_profiles.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "request_fingerprint", name="uq_voice_previews_fingerprint"
        ),
    )
    op.create_index(
        "ix_voice_previews_voice_created",
        "voice_previews",
        ["voice_profile_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_voice_previews_voice_created", table_name="voice_previews")
    op.drop_table("voice_previews")
