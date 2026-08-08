"""Add render nodes, attempts, and media assets.

Revision ID: 0008_render_execution
Revises: 0007_nullable_voice
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_render_execution"
down_revision: str | None = "0007_nullable_voice"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The development API historically calls metadata.create_all() on reload.
    # If it raced ahead of Alembic, all three tables already exist with the
    # current schema; advancing the revision is safe and avoids duplicate DDL.
    inspector = sa.inspect(op.get_bind())
    if all(
        inspector.has_table(table)
        for table in ("render_nodes", "render_attempts", "media_assets")
    ):
        return
    op.create_table(
        "render_nodes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("health_status", sa.String(32), nullable=False),
        sa.Column("health_message", sa.String(500)),
        sa.Column("health_checked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "render_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("topic_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "render_profile_id",
            sa.Uuid(),
            sa.ForeignKey("render_profiles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "render_node_id",
            sa.Uuid(),
            sa.ForeignKey("render_nodes.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "workflow_template_id",
            sa.Uuid(),
            sa.ForeignKey("workflow_templates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("external_job_id", sa.String(200)),
        sa.Column("client_id", sa.String(200)),
        sa.Column("workflow_snapshot", sa.JSON(), nullable=False),
        sa.Column("effective_values", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_render_attempts_job_created", "render_attempts", ["job_id", "created_at"]
    )
    op.create_index(
        "ix_render_attempts_external_job",
        "render_attempts",
        ["provider", "external_job_id"],
    )
    op.create_table(
        "media_assets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("topic_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "render_attempt_id",
            sa.Uuid(),
            sa.ForeignKey("render_attempts.id", ondelete="CASCADE"),
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("object_key", sa.String(500), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100)),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_media_assets_job_kind", "media_assets", ["job_id", "kind"])


def downgrade() -> None:
    op.drop_table("media_assets")
    op.drop_table("render_attempts")
    op.drop_table("render_nodes")
