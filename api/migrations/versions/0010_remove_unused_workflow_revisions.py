"""Remove superseded workflow rows that have no render history.

Revision ID: 0010_workflow_update_cleanup
Revises: 0009_workflow_lineage
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010_workflow_update_cleanup"
down_revision: str | None = "0009_workflow_lineage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM workflow_templates AS old
        WHERE EXISTS (
            SELECT 1
            FROM workflow_templates AS newer
            WHERE newer.logical_id = old.logical_id
              AND (
                newer.version > old.version
                OR (newer.version = old.version AND newer.created_at > old.created_at)
              )
        )
        AND NOT EXISTS (
            SELECT 1
            FROM render_attempts
            WHERE render_attempts.workflow_template_id = old.id
        )
        """
    )


def downgrade() -> None:
    # Removed unused revisions cannot be reconstructed.
    pass
