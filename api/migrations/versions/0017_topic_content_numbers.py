"""Add stable per-topic content numbers.

Revision ID: 0017_topic_content_numbers
Revises: 0016_job_generation_overrides
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "0017_topic_content_numbers"
down_revision: str | None = "0016_job_generation_overrides"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "batches",
        sa.Column(
            "next_content_number",
            sa.Integer(),
            nullable=False,
            server_default="2",
        ),
    )
    op.add_column("topic_jobs", sa.Column("content_number", sa.Integer()))
    connection = op.get_bind()
    legacy_rows = connection.execute(
        sa.text(
            """
            SELECT
                b.id AS batch_id,
                b.status AS batch_status,
                b.default_render_profile_id,
                b.target_duration_seconds,
                b.auto_fit_duration,
                b.created_at AS batch_created_at,
                b.updated_at AS batch_updated_at,
                j.id AS job_id,
                j.topic
            FROM batches AS b
            JOIN topic_jobs AS j ON j.batch_id = b.id
            ORDER BY b.created_at, b.id, j.created_at, j.id
            """
        )
    ).mappings()
    jobs_by_batch: dict[object, list[dict[str, object]]] = {}
    for row in legacy_rows:
        jobs_by_batch.setdefault(row["batch_id"], []).append(dict(row))

    for batch_id, jobs in jobs_by_batch.items():
        first = jobs[0]
        first_name = (
            str(first["topic"]).splitlines()[0].strip()[:160] or "Untitled topic"
        )
        connection.execute(
            sa.text("UPDATE batches SET name = :name WHERE id = :batch_id"),
            {"name": first_name, "batch_id": batch_id},
        )
        connection.execute(
            sa.text("UPDATE topic_jobs SET content_number = 1 WHERE id = :job_id"),
            {"job_id": first["job_id"]},
        )
        for job in jobs[1:]:
            new_batch_id = uuid4()
            topic_name = (
                str(job["topic"]).splitlines()[0].strip()[:160] or "Untitled topic"
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO batches (
                        id, name, status, default_render_profile_id,
                        target_duration_seconds, auto_fit_duration,
                        created_at, updated_at
                    ) VALUES (
                        :id, :name, :status, :default_render_profile_id,
                        :target_duration_seconds, :auto_fit_duration,
                        :created_at, :updated_at
                    )
                    """
                ),
                {
                    "id": new_batch_id,
                    "name": topic_name,
                    "status": job["batch_status"],
                    "default_render_profile_id": job["default_render_profile_id"],
                    "target_duration_seconds": job["target_duration_seconds"],
                    "auto_fit_duration": job["auto_fit_duration"],
                    "created_at": job["batch_created_at"],
                    "updated_at": job["batch_updated_at"],
                },
            )
            connection.execute(
                sa.text(
                    """
                    UPDATE topic_jobs
                    SET batch_id = :batch_id, content_number = 1
                    WHERE id = :job_id
                    """
                ),
                {"batch_id": new_batch_id, "job_id": job["job_id"]},
            )

    op.execute("UPDATE topic_jobs SET content_number = 1 WHERE content_number IS NULL")
    op.alter_column(
        "topic_jobs",
        "content_number",
        existing_type=sa.Integer(),
        nullable=False,
        server_default="1",
    )
    op.create_unique_constraint(
        "uq_topic_content_number", "topic_jobs", ["batch_id", "content_number"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_topic_content_number", "topic_jobs", type_="unique")
    op.drop_column("topic_jobs", "content_number")
    op.drop_column("batches", "next_content_number")
