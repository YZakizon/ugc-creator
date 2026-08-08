from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, selectinload, sessionmaker

from app.core.statuses import JobStatus
from app.db.models import (
    MediaAsset,
    RenderAttempt,
    RenderNode,
    RenderProfile,
    TopicJob,
    WorkflowTemplate,
)
from app.schemas import RenderNodeCreate


def now() -> datetime:
    return datetime.now(UTC)


SUBMISSION_CLAIM_DURATION = timedelta(minutes=5)


class RenderExecutionRepository:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self.factory = factory

    def list_nodes(self) -> list[RenderNode]:
        with self.factory() as session:
            return list(
                session.scalars(
                    select(RenderNode).order_by(RenderNode.created_at.desc())
                ).all()
            )

    def create_node(self, payload: RenderNodeCreate) -> RenderNode:
        with self.factory() as session:
            node = RenderNode(
                name=payload.name.strip(),
                provider="comfyui",
                base_url=payload.base_url.rstrip("/"),
                is_active=payload.is_active,
            )
            session.add(node)
            session.commit()
            session.refresh(node)
            return node

    def get_node(self, node_id: UUID) -> RenderNode | None:
        with self.factory() as session:
            return session.get(RenderNode, node_id)

    def update_node_health(
        self, node_id: UUID, healthy: bool, message: str | None
    ) -> RenderNode:
        with self.factory() as session:
            node = session.get(RenderNode, node_id)
            if node is None:
                raise LookupError("Render node not found")
            node.health_status = "healthy" if healthy else "unavailable"
            node.health_message = message
            node.health_checked_at = now()
            session.commit()
            session.refresh(node)
            return node

    def delete_node(self, node_id: UUID) -> bool:
        with self.factory() as session:
            node = session.get(RenderNode, node_id)
            if node is None:
                return False
            if session.scalar(
                select(RenderAttempt.id)
                .where(RenderAttempt.render_node_id == node_id)
                .limit(1)
            ):
                raise ValueError(
                    "Render node has render attempt history and cannot be deleted"
                )
            session.delete(node)
            session.commit()
            return True

    def queue_attempt(self, job_id: UUID, node_id: UUID) -> RenderAttempt:
        with self.factory() as session:
            job = session.get(TopicJob, job_id)
            if job is None:
                raise LookupError("Job not found")
            if job.render_profile_id is None:
                raise ValueError("Job has no render profile")
            profile = session.get(RenderProfile, job.render_profile_id)
            if profile is None or profile.workflow_template_id is None:
                raise ValueError("Render profile has no workflow template")
            workflow = session.scalar(
                select(WorkflowTemplate)
                .options(selectinload(WorkflowTemplate.bindings))
                .where(WorkflowTemplate.id == profile.workflow_template_id)
            )
            if workflow is None:
                raise ValueError("Render profile workflow template is unavailable")
            node = session.get(RenderNode, node_id)
            if node is None or not node.is_active:
                raise ValueError("Choose an active render node")
            existing = session.scalar(
                select(RenderAttempt)
                .where(
                    RenderAttempt.job_id == job_id,
                    RenderAttempt.status.in_(
                        [
                            "queued",
                            "submitting_render",
                            "rendering",
                            "downloading_output",
                        ]
                    ),
                )
                .order_by(RenderAttempt.created_at.desc())
            )
            if existing is not None:
                return existing
            attempt_id = uuid4()
            attempt = RenderAttempt(
                id=attempt_id,
                job_id=job.id,
                render_profile_id=profile.id,
                render_node_id=node.id,
                workflow_template_id=profile.workflow_template_id,
                provider=node.provider,
                client_id=f"ugc-creator-{attempt_id}",
                status="queued",
                progress=0,
                workflow_snapshot=deepcopy(workflow.workflow_json),
                binding_snapshot=[
                    {
                        "semantic_key": binding.semantic_key,
                        "node_id": binding.node_id,
                        "input_name": binding.input_name,
                        "value_type": binding.value_type,
                        "transform": deepcopy(binding.transform),
                        "required": binding.required,
                    }
                    for binding in workflow.bindings
                ],
                effective_values={},
            )
            job.status = JobStatus.QUEUED.value
            job.error_message = None
            session.add(attempt)
            session.commit()
            session.refresh(attempt)
            return attempt

    def claim_submission(self, attempt_id: UUID) -> tuple[bool, int]:
        claimed_at = now()
        claim_expires_at = claimed_at + SUBMISSION_CLAIM_DURATION
        with self.factory() as session:
            claimed = cast(
                CursorResult[Any],
                session.execute(
                    update(RenderAttempt)
                    .where(
                        RenderAttempt.id == attempt_id,
                        RenderAttempt.external_job_id.is_(None),
                        RenderAttempt.status == "queued",
                    )
                    .values(
                        status="submitting_render",
                        submission_claim_expires_at=claim_expires_at,
                        updated_at=claimed_at,
                    )
                ),
            )
            if claimed.rowcount == 1:
                attempt = session.get(RenderAttempt, attempt_id)
                if attempt is not None:
                    attempt.job.status = JobStatus.SUBMITTING_RENDER.value
                session.commit()
                return True, 0
            session.rollback()
            attempt = session.get(RenderAttempt, attempt_id)
            if attempt is None or attempt.external_job_id:
                return False, 0
            expires_at = attempt.submission_claim_expires_at
            if expires_at is None:
                return False, int(SUBMISSION_CLAIM_DURATION.total_seconds())
            comparable_now = claimed_at
            if expires_at.tzinfo is None:
                comparable_now = claimed_at.replace(tzinfo=None)
            remaining = max(1, int((expires_at - comparable_now).total_seconds()))
            return False, remaining

    def mark_submission_started(self, attempt_id: UUID) -> bool:
        started_at = now()
        with self.factory() as session:
            started = cast(
                CursorResult[Any],
                session.execute(
                    update(RenderAttempt)
                    .where(
                        RenderAttempt.id == attempt_id,
                        RenderAttempt.status == "submitting_render",
                        RenderAttempt.external_job_id.is_(None),
                        RenderAttempt.submission_started_at.is_(None),
                        RenderAttempt.submission_claim_expires_at > started_at,
                    )
                    .values(submission_started_at=started_at, updated_at=started_at)
                ),
            )
            session.commit()
            return started.rowcount == 1

    def get_attempt(self, attempt_id: UUID) -> RenderAttempt | None:
        with self.factory() as session:
            return session.scalar(
                select(RenderAttempt)
                .options(selectinload(RenderAttempt.assets))
                .where(RenderAttempt.id == attempt_id)
            )

    def list_attempts(self, job_id: UUID | None = None) -> list[RenderAttempt]:
        with self.factory() as session:
            query = (
                select(RenderAttempt)
                .options(selectinload(RenderAttempt.assets))
                .order_by(RenderAttempt.created_at.desc())
            )
            if job_id is not None:
                query = query.where(RenderAttempt.job_id == job_id)
            return list(session.scalars(query).unique().all())

    def execution_context(
        self, attempt_id: UUID
    ) -> tuple[RenderAttempt, TopicJob, RenderProfile, RenderNode, WorkflowTemplate]:
        with self.factory() as session:
            attempt = session.get(RenderAttempt, attempt_id)
            if attempt is None:
                raise LookupError("Render attempt not found")
            job = session.get(TopicJob, attempt.job_id)
            profile = session.get(RenderProfile, attempt.render_profile_id)
            node = session.get(RenderNode, attempt.render_node_id)
            workflow = session.scalar(
                select(WorkflowTemplate)
                .options(selectinload(WorkflowTemplate.bindings))
                .where(WorkflowTemplate.id == attempt.workflow_template_id)
            )
            if job is None or profile is None or node is None or workflow is None:
                raise LookupError("Render attempt configuration is unavailable")
            _ = profile.character.name
            return attempt, job, profile, node, workflow

    def save_prepared(
        self, attempt_id: UUID, workflow: dict[str, object], values: dict[str, object]
    ) -> RenderAttempt:
        with self.factory() as session:
            attempt = session.get(RenderAttempt, attempt_id)
            if attempt is None:
                raise LookupError("Render attempt not found")
            attempt.workflow_snapshot = workflow
            attempt.effective_values = values
            attempt.status = "submitting_render"
            attempt.job.status = JobStatus.SUBMITTING_RENDER.value
            session.commit()
            session.refresh(attempt)
            return attempt

    def save_submission(
        self, attempt_id: UUID, external_job_id: str, client_id: str | None
    ) -> bool:
        with self.factory() as session:
            attempt = session.get(RenderAttempt, attempt_id)
            if attempt is None:
                raise LookupError("Render attempt not found")
            if attempt.external_job_id == external_job_id:
                return attempt.status not in {"failed", "cancelled"}
            submitted_at = now()
            saved = cast(
                CursorResult[Any],
                session.execute(
                    update(RenderAttempt)
                    .where(
                        RenderAttempt.id == attempt_id,
                        RenderAttempt.external_job_id.is_(None),
                        RenderAttempt.status.not_in(
                            {"completed", "failed", "cancelled"}
                        ),
                    )
                    .values(
                        external_job_id=external_job_id,
                        client_id=client_id,
                        submitted_at=submitted_at,
                        submission_claim_expires_at=None,
                        status="rendering",
                        progress=max(attempt.progress, 1),
                        updated_at=submitted_at,
                    )
                ),
            )
            if saved.rowcount != 1:
                session.rollback()
                return False
            attempt.job.status = JobStatus.RENDERING.value
            session.commit()
            return True

    def update_progress(
        self, attempt_id: UUID, status: str, progress: int, error: str | None = None
    ) -> bool:
        with self.factory() as session:
            attempt = session.get(RenderAttempt, attempt_id)
            if attempt is None:
                raise LookupError("Render attempt not found")
            allowed_statuses = (
                {"rendering"}
                if status == "rendering"
                else {"queued", "submitting_render", "rendering", "downloading_output"}
            )
            changed = cast(
                CursorResult[Any],
                session.execute(
                    update(RenderAttempt)
                    .where(
                        RenderAttempt.id == attempt_id,
                        RenderAttempt.status.in_(allowed_statuses),
                    )
                    .values(
                        status=status,
                        progress=progress,
                        error_message=error,
                        submission_claim_expires_at=(
                            None
                            if status in {"failed", "completed", "cancelled"}
                            else attempt.submission_claim_expires_at
                        ),
                        finalization_claim_expires_at=(
                            None
                            if status in {"failed", "completed", "cancelled"}
                            else attempt.finalization_claim_expires_at
                        ),
                        updated_at=now(),
                    )
                ),
            )
            if changed.rowcount != 1:
                session.rollback()
                return False
            if status in {"failed", "completed", "cancelled"}:
                attempt.submission_claim_expires_at = None
            attempt.job.status = (
                status
                if status in {item.value for item in JobStatus}
                else JobStatus.RENDERING.value
            )
            attempt.job.error_message = error
            session.commit()
            return True

    def claim_finalization(self, attempt_id: UUID) -> tuple[bool, int]:
        claimed_at = now()
        expires_at = claimed_at + SUBMISSION_CLAIM_DURATION
        with self.factory() as session:
            claimed = cast(
                CursorResult[Any],
                session.execute(
                    update(RenderAttempt)
                    .where(
                        RenderAttempt.id == attempt_id,
                        RenderAttempt.external_job_id.is_not(None),
                        (
                            (RenderAttempt.status == "rendering")
                            | (
                                (RenderAttempt.status == "downloading_output")
                                & (
                                    RenderAttempt.finalization_claim_expires_at
                                    <= claimed_at
                                )
                            )
                        ),
                    )
                    .values(
                        status="downloading_output",
                        progress=95,
                        finalization_claim_expires_at=expires_at,
                        updated_at=claimed_at,
                    )
                ),
            )
            if claimed.rowcount == 1:
                session.commit()
                return True, 0
            session.rollback()
            attempt = session.get(RenderAttempt, attempt_id)
            if attempt is None or attempt.status in {
                "completed",
                "failed",
                "cancelled",
            }:
                return False, 0
            claim_expires_at = attempt.finalization_claim_expires_at
            if claim_expires_at is None:
                return False, int(SUBMISSION_CLAIM_DURATION.total_seconds())
            comparable_now = claimed_at
            if claim_expires_at.tzinfo is None:
                comparable_now = claimed_at.replace(tzinfo=None)
            remaining = max(1, int((claim_expires_at - comparable_now).total_seconds()))
            return False, remaining

    def complete(
        self,
        attempt_id: UUID,
        object_key: str,
        filename: str,
        content_type: str | None,
        size: int,
    ) -> bool:
        with self.factory() as session:
            attempt = session.get(RenderAttempt, attempt_id)
            if attempt is None:
                raise LookupError("Render attempt not found")
            completed_at = now()
            won = cast(
                CursorResult[Any],
                session.execute(
                    update(RenderAttempt)
                    .where(
                        RenderAttempt.id == attempt_id,
                        RenderAttempt.status.not_in(
                            {"completed", "failed", "cancelled"}
                        ),
                    )
                    .values(
                        status="completed",
                        progress=100,
                        completed_at=completed_at,
                        submission_claim_expires_at=None,
                        finalization_claim_expires_at=None,
                        updated_at=completed_at,
                    )
                ),
            )
            if won.rowcount != 1:
                session.rollback()
                return False
            asset = MediaAsset(
                job_id=attempt.job_id,
                render_attempt_id=attempt.id,
                kind="video",
                object_key=object_key,
                filename=filename,
                content_type=content_type,
                size_bytes=size,
            )
            session.add(asset)
            attempt.job.status = JobStatus.COMPLETED.value
            session.commit()
            return True

    def get_asset(self, asset_id: UUID) -> MediaAsset | None:
        with self.factory() as session:
            return session.get(MediaAsset, asset_id)
