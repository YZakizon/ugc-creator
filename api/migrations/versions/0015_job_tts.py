"""Add paid-call-safe job TTS state.

Revision ID: 0015_job_tts
Revises: 0014_content_prompt_settings
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_job_tts"
down_revision: str | None = "0014_content_prompt_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("topic_jobs", sa.Column("tts_provider", sa.String(64)))
    op.add_column("topic_jobs", sa.Column("tts_voice_id", sa.String(160)))
    op.add_column("topic_jobs", sa.Column("tts_model", sa.String(160)))
    op.add_column("topic_jobs", sa.Column("tts_settings", sa.JSON()))
    op.add_column("topic_jobs", sa.Column("tts_provider_request_id", sa.String(160)))
    op.add_column("topic_jobs", sa.Column("tts_claim_token", sa.Uuid()))
    op.add_column("topic_jobs", sa.Column("tts_claim_expires_at", sa.DateTime()))
    op.add_column("topic_jobs", sa.Column("tts_generated_at", sa.DateTime()))


def downgrade() -> None:
    for column in (
        "tts_generated_at",
        "tts_claim_expires_at",
        "tts_claim_token",
        "tts_provider_request_id",
        "tts_settings",
        "tts_model",
        "tts_voice_id",
        "tts_provider",
    ):
        op.drop_column("topic_jobs", column)
