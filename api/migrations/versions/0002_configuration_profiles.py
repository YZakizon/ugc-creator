"""Add characters, voice profiles, and render profiles."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_configuration_profiles"
down_revision: str | None = "0001_core_batches"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    json_type = postgresql.JSONB()
    op.create_table(
        "voice_profiles",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("provider_voice_id", sa.String(length=160), nullable=False),
        sa.Column("provider_model", sa.String(length=160), nullable=True),
        sa.Column("speed", sa.Float(), nullable=False),
        sa.Column("stability", sa.Float(), nullable=True),
        sa.Column("similarity", sa.Float(), nullable=True),
        sa.Column("style_exaggeration", sa.Float(), nullable=True),
        sa.Column("extra_settings", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "characters",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("slug", sa.String(length=180), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("default_voice_profile_id", uuid_type, nullable=True),
        sa.Column("default_prompt", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["default_voice_profile_id"], ["voice_profiles.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "render_profiles",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("character_id", uuid_type, nullable=False),
        sa.Column("voice_profile_id", uuid_type, nullable=False),
        sa.Column("renderer_provider", sa.String(length=64), nullable=False),
        sa.Column("render_node_id", uuid_type, nullable=True),
        sa.Column("workflow_template_id", uuid_type, nullable=True),
        sa.Column("prompt_template", sa.Text(), nullable=False),
        sa.Column("negative_prompt_template", sa.Text(), nullable=True),
        sa.Column("default_parameters", json_type, nullable=False),
        sa.Column("parameter_schema", json_type, nullable=False),
        sa.Column("capabilities", json_type, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["character_id"], ["characters.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["voice_profile_id"], ["voice_profiles.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_render_profiles_active", "render_profiles", ["is_active"])
    op.create_index(
        "ix_render_profiles_provider", "render_profiles", ["renderer_provider"]
    )


def downgrade() -> None:
    op.drop_index("ix_render_profiles_provider", table_name="render_profiles")
    op.drop_index("ix_render_profiles_active", table_name="render_profiles")
    op.drop_table("render_profiles")
    op.drop_table("characters")
    op.drop_table("voice_profiles")
