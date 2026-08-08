"""Group immutable workflow revisions under one logical workflow.

Revision ID: 0009_workflow_lineage
Revises: 0008_render_execution
"""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision: str = "0009_workflow_lineage"
down_revision: str | None = "0008_render_execution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_templates", sa.Column("logical_id", sa.Uuid(), nullable=True)
    )
    bind = op.get_bind()
    rows = (
        bind.execute(
            sa.text(
                "SELECT id, name, renderer_provider, version, created_at "
                "FROM workflow_templates ORDER BY version, created_at"
            )
        )
        .mappings()
        .all()
    )

    groups: dict[tuple[str, str], UUID] = {}
    latest: dict[UUID, tuple[int, object, UUID]] = {}
    member_to_latest_group: dict[UUID, UUID] = {}
    for row in rows:
        key = (str(row["renderer_provider"]), str(row["name"]).strip().casefold())
        logical_id = groups.setdefault(key, row["id"])
        bind.execute(
            sa.text(
                "UPDATE workflow_templates SET logical_id = :logical_id WHERE id = :id"
            ),
            {"logical_id": logical_id, "id": row["id"]},
        )
        candidate = (int(row["version"]), row["created_at"], row["id"])
        if logical_id not in latest or candidate[:2] > latest[logical_id][:2]:
            latest[logical_id] = candidate
        member_to_latest_group[row["id"]] = logical_id

    for member_id, logical_id in member_to_latest_group.items():
        bind.execute(
            sa.text(
                "UPDATE render_profiles SET workflow_template_id = :latest_id "
                "WHERE workflow_template_id = :member_id"
            ),
            {"latest_id": latest[logical_id][2], "member_id": member_id},
        )

    op.alter_column("workflow_templates", "logical_id", nullable=False)
    op.create_index(
        "ix_workflow_templates_logical_version",
        "workflow_templates",
        ["logical_id", "version"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workflow_templates_logical_version", table_name="workflow_templates"
    )
    op.drop_column("workflow_templates", "logical_id")
