"""Add per-job voice and workflow selections.

Revision ID: 0016_job_generation_overrides
Revises: 0015_job_tts
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_job_generation_overrides"
down_revision: str | None = "0015_job_tts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("topic_jobs", sa.Column("voice_profile_id", sa.Uuid()))
    op.add_column("topic_jobs", sa.Column("workflow_template_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_topic_jobs_voice_profile_id",
        "topic_jobs",
        "voice_profiles",
        ["voice_profile_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_topic_jobs_workflow_template_id",
        "topic_jobs",
        "workflow_templates",
        ["workflow_template_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_topic_jobs_workflow_template_id", "topic_jobs", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_topic_jobs_voice_profile_id", "topic_jobs", type_="foreignkey"
    )
    op.drop_column("topic_jobs", "workflow_template_id")
    op.drop_column("topic_jobs", "voice_profile_id")
