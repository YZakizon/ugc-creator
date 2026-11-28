from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, tuple_, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, aliased, selectinload, sessionmaker

from app.core.statuses import ACTIVE_RENDER_JOB_STATUSES, JobStatus
from app.db.models import (
    Batch,
    MediaAsset,
    RenderAttempt,
    RenderNode,
    RenderProfile,
    TopicJob,
    WorkflowTemplate,
)
from app.providers.render.comfyui_controls import inferred_ltx_bindings
from app.providers.render.minimax_controls import configure_minimax_image_size
from app.providers.render.optional_inputs import configure_optional_images
from app.schemas import CreatedVideoRenderRequest, RenderNodeCreate


def now() -> datetime:
    return datetime.now(UTC)


SUBMISSION_CLAIM_DURATION = timedelta(minutes=5)


def active_render_status(session: Session, job_id: UUID) -> str | None:
    return session.scalar(
        select(RenderAttempt.status)
        .where(
            RenderAttempt.job_id == job_id,
            RenderAttempt.status.in_(ACTIVE_RENDER_JOB_STATUSES),
        )
        .order_by(RenderAttempt.created_at, RenderAttempt.id)
        .limit(1)
    )


def _publish_render_status(
    session: Session, job_id: UUID, status: str, error: str | None = None
) -> None:
    statement = (
        update(TopicJob)
        .where(
            TopicJob.id == job_id,
            TopicJob.status != JobStatus.GENERATING_TTS.value,
        )
        .values(status=status)
    )
    if error is not None:
        statement = statement.values(error_message=error)
    session.execute(statement)


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

    def queue_attempt(
        self,
        job_id: UUID,
        node_id: UUID,
        requested: CreatedVideoRenderRequest | None = None,
    ) -> RenderAttempt:
        with self.factory() as session:
            job = session.scalar(
                select(TopicJob).where(TopicJob.id == job_id).with_for_update()
            )
            if job is None:
                raise LookupError("Job not found")
            if requested is not None and job.batch.creation_mode != "created_video":
                raise ValueError("Only created videos support queued render snapshots")
            if job.status in {
                JobStatus.GENERATING_CONTENT.value,
                JobStatus.GENERATING_TTS.value,
                JobStatus.FITTING_DURATION.value,
            }:
                raise ValueError("Wait for audio or script generation to finish")
            if requested is None and not any(
                asset.kind == "audio" for asset in job.media_assets
            ):
                raise ValueError("Generate job speech before rendering")
            profile_id = (
                requested.render_profile_id if requested else job.render_profile_id
            )
            if profile_id is None:
                raise ValueError("Job has no render profile")
            profile = session.get(RenderProfile, profile_id)
            if profile is None or (requested is not None and not profile.is_active):
                raise ValueError("Render profile is unavailable")
            workflow_template_id = (
                requested.workflow_template_id
                if requested
                else job.workflow_template_id
            ) or profile.workflow_template_id
            if workflow_template_id is None:
                raise ValueError("Job has no workflow template")
            workflow = session.scalar(
                select(WorkflowTemplate)
                .options(selectinload(WorkflowTemplate.bindings))
                .where(WorkflowTemplate.id == workflow_template_id)
            )
            if workflow is None:
                raise ValueError("Render profile workflow template is unavailable")
            node = session.get(RenderNode, node_id)
            if node is None or not node.is_active:
                raise ValueError("Choose an active render node")
            if requested is not None and (
                profile.renderer_provider != node.provider
                or workflow.renderer_provider != node.provider
            ):
                raise ValueError(
                    "Choose a workflow and node that match the render engine"
                )
            overrides = (
                requested.render_overrides.compact()
                if requested
                else (job.render_overrides or {})
            )
            snapshot: dict[str, object] = {}
            if requested is not None:
                snapshot = self._created_video_snapshot(
                    job, profile, workflow, overrides, requested
                )
            else:
                existing = session.scalar(
                    select(RenderAttempt)
                    .where(
                        RenderAttempt.job_id == job_id,
                        RenderAttempt.status.in_(ACTIVE_RENDER_JOB_STATUSES),
                    )
                    .order_by(RenderAttempt.created_at.desc())
                )
                if existing is not None:
                    return existing
            attempt_id = uuid4()
            binding_snapshot = [
                {
                    "semantic_key": binding.semantic_key,
                    "node_id": binding.node_id,
                    "input_name": binding.input_name,
                    "value_type": binding.value_type,
                    "transform": deepcopy(binding.transform),
                    "required": binding.required,
                }
                for binding in workflow.bindings
            ]
            workflow_snapshot = deepcopy(workflow.workflow_json)
            if node.provider == "comfyui":
                configure_minimax_image_size(workflow_snapshot, overrides)
                configure_optional_images(
                    workflow_snapshot,
                    workflow.metadata_json,
                    overrides,
                )
                binding_snapshot.extend(
                    inferred_ltx_bindings(workflow_snapshot, binding_snapshot)
                )
            attempt = RenderAttempt(
                id=attempt_id,
                job_id=job.id,
                render_profile_id=profile.id,
                render_node_id=node.id,
                workflow_template_id=workflow_template_id,
                provider=node.provider,
                client_id=f"ugc-creator-{attempt_id}",
                status="queued",
                progress=0,
                workflow_snapshot=workflow_snapshot,
                binding_snapshot=binding_snapshot,
                effective_values={"requested_inputs": snapshot}
                if requested is not None
                else {},
            )
            if job.status not in ACTIVE_RENDER_JOB_STATUSES:
                job.status = JobStatus.QUEUED.value
                job.error_message = None
            session.add(attempt)
            session.commit()
            session.refresh(attempt)
            return attempt

    @staticmethod
    def _created_video_snapshot(
        job: TopicJob,
        profile: RenderProfile,
        workflow: WorkflowTemplate,
        overrides: dict[str, object],
        requested: CreatedVideoRenderRequest,
    ) -> dict[str, object]:
        def media(kind: str, asset_id: UUID) -> dict[str, object]:
            asset = next(
                (
                    item
                    for item in job.media_assets
                    if item.id == asset_id and item.kind in {kind, f"{kind}_archive"}
                ),
                None,
            )
            if asset is None:
                raise ValueError(
                    "Pick source image and audio file before generating video"
                )
            return {
                "id": str(asset.id),
                "filename": asset.filename,
                "object_key": asset.object_key,
                "generation_metadata": deepcopy(asset.generation_metadata),
            }

        topic = requested.title
        script = requested.speech_script or topic
        return {
            "values": {
                **deepcopy(profile.default_parameters),
                "script": script,
                "topic": topic,
                "hook": job.hook or "",
                "video_prompt": profile.prompt_template or script,
                "duration": requested.target_duration_seconds,
                "character_name": profile.character.name,
                **deepcopy(overrides),
            },
            "audio": media("audio", requested.audio_asset_id),
            "source_image": media("source_image", requested.source_image_asset_id),
            "workflow_metadata": deepcopy(workflow.metadata_json),
            "workflow_checksum": workflow.checksum,
        }

    @staticmethod
    def _set_job_render_status(
        session: Session,
        attempt: RenderAttempt,
        fallback: str,
        error: str | None = None,
    ) -> None:
        job = session.scalar(
            select(TopicJob).where(TopicJob.id == attempt.job_id).with_for_update()
        )
        if job is None:
            return
        if job.status == JobStatus.GENERATING_TTS.value:
            return
        remaining = active_render_status(session, job.id)
        job.status = remaining or fallback
        # A replacement speech failure stays visible after a snapshotted render ends.
        if not (job.error_message and "requested_inputs" in attempt.effective_values):
            job.error_message = None if remaining else error

    def recoverable_created_video_heads(self) -> list[tuple[UUID, bool]]:
        checked_at = now()
        stale_before = checked_at - timedelta(seconds=30)
        earlier = aliased(RenderAttempt)
        predecessor = select(earlier.id).where(
            earlier.job_id == RenderAttempt.job_id,
            earlier.status.in_(ACTIVE_RENDER_JOB_STATUSES),
            tuple_(earlier.created_at, earlier.id)
            < tuple_(RenderAttempt.created_at, RenderAttempt.id),
        )
        needs_monitor = RenderAttempt.external_job_id.is_not(None)
        with self.factory() as session:
            rows = session.execute(
                select(RenderAttempt.id, needs_monitor)
                .join(TopicJob, RenderAttempt.job_id == TopicJob.id)
                .join(Batch, TopicJob.batch_id == Batch.id)
                .where(
                    Batch.creation_mode == "created_video",
                    or_(
                        and_(
                            RenderAttempt.status == "queued",
                            RenderAttempt.external_job_id.is_(None),
                        ),
                        and_(
                            RenderAttempt.status == "submitting_render",
                            RenderAttempt.external_job_id.is_(None),
                            or_(
                                RenderAttempt.submission_claim_expires_at.is_(None),
                                RenderAttempt.submission_claim_expires_at <= checked_at,
                            ),
                        ),
                        and_(
                            RenderAttempt.status.in_(
                                {"rendering", "downloading_output"}
                            ),
                            needs_monitor,
                            RenderAttempt.updated_at <= stale_before,
                            or_(
                                RenderAttempt.finalization_claim_expires_at.is_(None),
                                RenderAttempt.finalization_claim_expires_at
                                <= checked_at,
                            ),
                        ),
                    ),
                    ~predecessor.exists(),
                )
                .order_by(RenderAttempt.created_at, RenderAttempt.id)
            ).tuples()
            return [(attempt_id, monitor) for attempt_id, monitor in rows]

    def claim_submission(self, attempt_id: UUID) -> tuple[bool, int]:
        claimed_at = now()
        claim_expires_at = claimed_at + SUBMISSION_CLAIM_DURATION
        with self.factory() as session:
            candidate = session.get(RenderAttempt, attempt_id)
            if candidate is None or candidate.status in {
                "completed",
                "failed",
                "cancelled",
            }:
                return False, 0
            if "requested_inputs" in candidate.effective_values:
                earlier = session.scalar(
                    select(RenderAttempt.id)
                    .where(
                        RenderAttempt.job_id == candidate.job_id,
                        RenderAttempt.status.in_(ACTIVE_RENDER_JOB_STATUSES),
                        tuple_(RenderAttempt.created_at, RenderAttempt.id)
                        < (candidate.created_at, candidate.id),
                    )
                    .limit(1)
                )
                if earlier is not None:
                    return False, 5
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
                    _publish_render_status(
                        session, attempt.job_id, JobStatus.SUBMITTING_RENDER.value
                    )
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

    def delete_failed_attempts(self, job_id: UUID, attempt_id: UUID | None) -> None:
        created_video_job = (
            select(TopicJob.id)
            .join(Batch, Batch.id == TopicJob.batch_id)
            .where(TopicJob.id == job_id, Batch.creation_mode == "created_video")
        )
        statement = update(RenderAttempt).where(
            RenderAttempt.job_id.in_(created_video_job),
            RenderAttempt.status == "failed",
            RenderAttempt.output_deleted_at.is_(None),
        )
        if attempt_id is not None:
            statement = statement.where(RenderAttempt.id == attempt_id)
        with self.factory() as session:
            session.execute(statement.values(output_deleted_at=now()))
            session.commit()

    def execution_context(
        self, attempt_id: UUID
    ) -> tuple[RenderAttempt, TopicJob, RenderProfile, RenderNode, WorkflowTemplate]:
        with self.factory() as session:
            attempt = session.get(RenderAttempt, attempt_id)
            if attempt is None:
                raise LookupError("Render attempt not found")
            job = session.scalar(
                select(TopicJob)
                .options(
                    selectinload(TopicJob.media_assets),
                    selectinload(TopicJob.render_attempts),
                )
                .where(TopicJob.id == attempt.job_id)
            )
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
            attempt = session.scalar(
                select(RenderAttempt)
                .where(RenderAttempt.id == attempt_id)
                .with_for_update()
            )
            if attempt is None:
                raise LookupError("Render attempt not found")
            if attempt.status in {"completed", "failed", "cancelled"}:
                return attempt
            attempt.workflow_snapshot = workflow
            snapshot = attempt.effective_values.get("requested_inputs")
            attempt.effective_values = (
                {**values, "requested_inputs": snapshot}
                if snapshot is not None
                else values
            )
            attempt.status = "submitting_render"
            _publish_render_status(
                session, attempt.job_id, JobStatus.SUBMITTING_RENDER.value
            )
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
            _publish_render_status(session, attempt.job_id, JobStatus.RENDERING.value)
            session.commit()
            return True

    def update_progress(
        self,
        attempt_id: UUID,
        status: str,
        progress: int,
        error: str | None = None,
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
            job_status = (
                status
                if status in {item.value for item in JobStatus}
                else JobStatus.RENDERING.value
            )
            if status in {"failed", "completed", "cancelled"}:
                self._set_job_render_status(session, attempt, job_status, error)
            else:
                _publish_render_status(session, attempt.job_id, job_status, error)
            session.commit()
            return True

    def cancel_attempt(
        self,
        attempt_id: UUID,
        *,
        queued_only: bool = False,
        upstream_cancelled: bool = False,
    ) -> RenderAttempt | None:
        cancelled_at = now()
        with self.factory() as session:
            attempt = session.get(RenderAttempt, attempt_id)
            if attempt is None:
                return None
            if queued_only and attempt.status != "queued":
                raise ValueError("This render has already left the queue")
            if attempt.status in {"completed", "failed", "cancelled"}:
                return attempt
            cancellable = update(RenderAttempt).where(
                RenderAttempt.id == attempt_id,
                RenderAttempt.status.in_(
                    {"queued"} if queued_only else ACTIVE_RENDER_JOB_STATUSES
                ),
            )
            if not upstream_cancelled:
                cancellable = cancellable.where(
                    RenderAttempt.submission_started_at.is_(None),
                    RenderAttempt.external_job_id.is_(None),
                )
            changed = cast(
                CursorResult[Any],
                session.execute(
                    cancellable.values(
                        status="cancelled",
                        error_message="Render cancelled.",
                        submission_claim_expires_at=None,
                        finalization_claim_expires_at=None,
                        updated_at=cancelled_at,
                        completed_at=cancelled_at,
                    )
                ),
            )
            if changed.rowcount != 1:
                session.rollback()
                if queued_only:
                    raise ValueError("This render has already left the queue")
                current = session.get(RenderAttempt, attempt_id)
                if current is not None and current.status in ACTIVE_RENDER_JOB_STATUSES:
                    raise ValueError(
                        "ComfyUI submission is in progress. Try cancelling again."
                    )
                return current
            self._set_job_render_status(
                session, attempt, JobStatus.READY_TO_RENDER.value
            )
            session.commit()
            return session.scalar(
                select(RenderAttempt)
                .options(selectinload(RenderAttempt.assets))
                .where(RenderAttempt.id == attempt_id)
            )

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
                        output_filename=filename,
                        output_deleted_at=None,
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
            self._set_job_render_status(session, attempt, JobStatus.COMPLETED.value)
            session.commit()
            return True

    def get_asset(self, asset_id: UUID) -> MediaAsset | None:
        with self.factory() as session:
            return session.get(MediaAsset, asset_id)

    def delete_video_asset(self, asset_id: UUID) -> bool:
        with self.factory() as session:
            asset = session.scalar(
                select(MediaAsset)
                .options(selectinload(MediaAsset.render_attempt))
                .where(MediaAsset.id == asset_id)
            )
            if asset is None:
                return False
            if asset.kind != "video" or asset.render_attempt is None:
                raise ValueError("Only generated video assets can be deleted")
            if asset.render_attempt.status != "completed":
                raise ValueError("Video cannot be deleted before rendering completes")
            job = session.scalar(
                select(TopicJob).where(TopicJob.id == asset.job_id).with_for_update()
            )
            asset.render_attempt.output_filename = asset.filename
            asset.render_attempt.output_deleted_at = now()
            session.delete(asset)
            session.flush()
            remaining = session.scalar(
                select(MediaAsset.id)
                .where(MediaAsset.job_id == asset.job_id, MediaAsset.kind == "video")
                .limit(1)
            )
            if (
                job is not None
                and remaining is None
                and job.status not in ACTIVE_RENDER_JOB_STATUSES
                and job.status != JobStatus.GENERATING_TTS.value
            ):
                job.status = JobStatus.READY_TO_RENDER.value
                job.error_message = None
            session.commit()
            return True
