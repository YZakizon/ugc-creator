"""Add ComfyUI workflow templates and semantic parameter bindings."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_workflow_templates"
down_revision: str | None = "0003_job_content"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    json_type = postgresql.JSONB()
    op.create_table(
        "workflow_templates",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("renderer_provider", sa.String(length=64), nullable=False),
        sa.Column("workflow_json", json_type, nullable=False),
        sa.Column("metadata_json", json_type, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_workflow_templates_provider",
        "workflow_templates",
        ["renderer_provider"],
    )
    op.create_table(
        "workflow_parameter_bindings",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("workflow_template_id", uuid_type, nullable=False),
        sa.Column("semantic_key", sa.String(length=64), nullable=False),
        sa.Column("node_id", sa.String(length=160), nullable=False),
        sa.Column("input_name", sa.String(length=160), nullable=False),
        sa.Column("value_type", sa.String(length=32), nullable=False),
        sa.Column("transform", json_type, nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workflow_template_id"],
            ["workflow_templates.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workflow_template_id",
            "semantic_key",
            name="uq_workflow_bindings_template_key",
        ),
    )


def downgrade() -> None:
    op.drop_table("workflow_parameter_bindings")
    op.drop_index("ix_workflow_templates_provider", table_name="workflow_templates")
    op.drop_table("workflow_templates")
