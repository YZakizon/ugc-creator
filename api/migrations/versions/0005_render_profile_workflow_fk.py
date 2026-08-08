"""Protect workflow templates from deletion while profiles use them."""

from collections.abc import Sequence

from alembic import op

revision: str = "0005_render_profile_workflow_fk"
down_revision: str | None = "0004_workflow_templates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_foreign_key(
        "fk_render_profiles_workflow_template_id",
        "render_profiles",
        "workflow_templates",
        ["workflow_template_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_render_profiles_workflow_template_id",
        "render_profiles",
        type_="foreignkey",
    )
