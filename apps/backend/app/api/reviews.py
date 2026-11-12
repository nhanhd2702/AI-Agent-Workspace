"""Human-in-the-Loop (HIL) Review Gates API router (Task 2.5 / F01.4 / F03).

Implements:
- POST /api/v1/reviews: Create a pending ReviewGate with 24h UTC expiry.
- GET /api/v1/reviews: List review gates (optional task_id / status filters).
- GET /api/v1/reviews/{review_id}: Retrieve a single review gate.
- PATCH /api/v1/reviews/{review_id}/decide: Decide approve/edit/reject with
  410 Gone expiry check, 400 Bad Request short-feedback check on reject,
  409 Conflict double-decide & terminal-task guards, atomic SQLite claim,
  offloaded LangGraph checkpoint resume, single-transaction FSM + TurnLog
  re-enqueue on reject, secret masking, and WebSocket broadcast.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
import uuid
import weakref

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.config import AppSettings, get_settings
from app.db.models import ReviewGate, Task, TaskStatus, TurnLog
from app.db.session import get_db
from app.db.state_machine import TaskStateMachine
from app.orchestrator.dispatcher import mask_secrets
from app.orchestrator.graph import OrchestratorGraph

router = APIRouter(prefix="/api/v1/reviews", tags=["reviews"])

DEFAULT_EXPIRY_HOURS = 24.0
MIN_EXPIRY_HOURS = 0.0001
MAX_EXPIRY_HOURS = 720.0
MIN_REJECT_FEEDBACK_LENGTH = 5


class CreateReviewRequest(BaseModel):
    """Payload to open a Human-in-the-Loop review gate for a task."""

    model_config = ConfigDict(populate_by_name=True)

    task_id: str = Field(..., min_length=1, alias="taskId")
    gate_type: str = Field(default="hil", min_length=1, max_length=32, alias="gateType")
    checkpoint_id: Optional[str] = Field(default=None, max_length=128, alias="checkpointId")
    summary: Optional[str] = None
    payload: Optional[Any] = None
    expires_in_hours: Optional[float] = Field(default=None, alias="expiresInHours")
    expires_at: Optional[datetime] = Field(default=None, alias="expiresAt")


class DecideReviewRequest(BaseModel):
    """Payload to decide on a pending ReviewGate."""

    model_config = ConfigDict(populate_by_name=True)

    decision: str
    feedback_text: Optional[str] = Field(default=None, alias="feedbackText")
    feedback: Optional[str] = None
    edited_content: Optional[Any] = Field(default=None, alias="editedContent")
    edited_payload: Optional[Any] = Field(default=None, alias="editedPayload")
    actor: str = Field(default="user", min_length=1, max_length=64)


def _get_settings(request: Request) -> AppSettings:
    return getattr(request.app.state, "settings", None) or get_settings()


def _get_extra_secrets(request: Request) -> list[str]:
    settings = _get_settings(request)
    return [settings.local_auth_token] if settings.local_auth_token else []


def _get_checkpoint_db_path(request: Request) -> Path:
    configured = getattr(request.app.state, "checkpoint_db_path", None)
    if configured is not None:
        return Path(configured).resolve()
    return (_get_settings(request).resolved_db_path.parent / "checkpoints.db").resolve()


def _get_task_review_lock(request: Request, task_id: str) -> asyncio.Lock:
    """Return a per-event-loop, per-task asyncio.Lock stored on app.state."""
    locks_by_loop = getattr(request.app.state, "review_locks", None)
    if locks_by_loop is None:
        locks_by_loop = weakref.WeakKeyDictionary()
        request.app.state.review_locks = locks_by_loop

    loop = asyncio.get_running_loop()
    task_locks = locks_by_loop.get(loop)
    if task_locks is None:
        task_locks = {}
        locks_by_loop[loop] = task_locks

    lock = task_locks.get(task_id)
    if lock is None:
        lock = asyncio.Lock()
        task_locks[task_id] = lock
    return lock


def _ensure_utc(dt: datetime) -> datetime:
    """Normalize naive or offset datetimes to timezone-aware UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_utc_iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return _ensure_utc(dt).isoformat()


def _resolve_expires_at(review: ReviewGate) -> datetime:
    if review.expires_at is not None:
        return _ensure_utc(review.expires_at)
    base_created = (
        _ensure_utc(review.created_at)
        if review.created_at is not None
        else datetime.now(timezone.utc)
    )
    return base_created + timedelta(hours=DEFAULT_EXPIRY_HOURS)


def _get_review_meta(task: Optional[Task], review_id: str) -> dict[str, Any]:
    if task is None or not isinstance(task.task_metadata, dict):
        return {}
    reviews_map = task.task_metadata.get("reviews")
    if isinstance(reviews_map, dict):
        entry = reviews_map.get(review_id)
        if isinstance(entry, dict):
            return entry
    return {}


def _serialize_review(
    review: ReviewGate,
    task: Optional[Task] = None,
    extra_secrets: Optional[list[str]] = None,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    meta = _get_review_meta(task, review.id)
    effective_expires = _resolve_expires_at(review)
    data: dict[str, Any] = {
        "id": review.id,
        "task_id": review.task_id,
        "checkpoint_id": review.checkpoint_id,
        "gate_type": review.gate_type,
        "status": review.status,
        "decision": review.decision,
        "feedback_text": review.feedback_text,
        "actor": review.actor,
        "summary": meta.get("summary"),
        "payload": meta.get("payload"),
        "edited_content": meta.get("edited_content"),
        "expires_at": effective_expires.isoformat(),
        "decided_at": _format_utc_iso(review.decided_at),
        "created_at": _format_utc_iso(review.created_at),
    }
    if extra:
        data.update(extra)
    return mask_secrets(data, extra_secrets=extra_secrets)


def _resume_graph_if_interrupted(
    checkpoint_db_path: Path,
    task_id: str,
    checkpoint_id: Optional[str],
    resume_payload: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """Resume an interrupted LangGraph checkpoint if checkpoints.db has an active interrupt."""
    if not checkpoint_db_path.exists():
        return None

    candidates: list[str] = []
    for candidate in (checkpoint_id, task_id):
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    with OrchestratorGraph(checkpoint_db_path=checkpoint_db_path) as graph:
        for tid in candidates:
            if graph.is_interrupted(tid):
                resumed_state = graph.resume(thread_id=tid, decision=resume_payload)
                return {"thread_id": tid, "state": resumed_state}
    return None


def _revert_processing_claim(db: Session, review_id: str) -> None:
    """Revert a two-phase 'processing' claim back to 'pending' safely."""
    try:
        db.rollback()
        db.execute(
            update(ReviewGate)
            .where(
                ReviewGate.id == review_id,
                ReviewGate.status == "processing",
            )
            .values(status="pending")
        )
        db.commit()
    except Exception:
        db.rollback()


async def _broadcast_review_event(
    request: Request,
    task_id: str,
    event_payload: dict[str, Any],
) -> None:
    ws_manager = getattr(request.app.state, "ws_manager", None)
    if ws_manager is None:
        return
    try:
        await ws_manager.broadcast(task_id=task_id, event=event_payload)
    except Exception:
        pass


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_review_gate(
    payload: CreateReviewRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Create a pending Human-in-the-Loop review gate for an existing Task."""
    task_lock = _get_task_review_lock(request, payload.task_id)
    async with task_lock:
        db.expire_all()
        task = db.get(Task, payload.task_id)
        if task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task '{payload.task_id}' not found",
            )

        current_status = (
            TaskStatus(task.status) if isinstance(task.status, str) else task.status
        )
        if current_status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot create review gate for task in terminal status '{current_status.value}'",
            )

        now_utc = datetime.now(timezone.utc)
        existing_pending = (
            db.query(ReviewGate)
            .filter(
                ReviewGate.task_id == task.id,
                ReviewGate.status.in_(["pending", "processing"]),
            )
            .all()
        )
        for existing in existing_pending:
            if existing.status == "pending" and _resolve_expires_at(existing) <= now_utc:
                existing.status = "expired"
            else:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Task '{task.id}' already has an active pending review gate '{existing.id}'",
                )

        if payload.expires_at is not None:
            expires_at = _ensure_utc(payload.expires_at)
        else:
            raw_hours = (
                payload.expires_in_hours
                if payload.expires_in_hours is not None
                else DEFAULT_EXPIRY_HOURS
            )
            clamped_hours = max(MIN_EXPIRY_HOURS, min(float(raw_hours), MAX_EXPIRY_HOURS))
            expires_at = now_utc + timedelta(hours=clamped_hours)

        extra_secrets = _get_extra_secrets(request)
        review_id = f"rev-{uuid.uuid4().hex[:12]}"
        masked_summary = (
            mask_secrets(payload.summary, extra_secrets=extra_secrets)
            if payload.summary is not None
            else None
        )
        masked_payload = (
            mask_secrets(payload.payload, extra_secrets=extra_secrets)
            if payload.payload is not None
            else None
        )

        review = ReviewGate(
            id=review_id,
            task_id=task.id,
            checkpoint_id=payload.checkpoint_id or task.id,
            gate_type=payload.gate_type.strip(),
            status="pending",
            expires_at=expires_at,
            created_at=now_utc,
        )

        meta = dict(task.task_metadata or {})
        reviews_meta = dict(meta.get("reviews") or {})
        reviews_meta[review_id] = {
            "summary": masked_summary,
            "payload": masked_payload,
        }
        meta["reviews"] = reviews_meta
        task.task_metadata = meta
        flag_modified(task, "task_metadata")

        try:
            db.add(review)
            if current_status != TaskStatus.WAITING_REVIEW:
                if current_status != TaskStatus.RUNNING:
                    TaskStateMachine.transition(
                        session=db,
                        task_id=task.id,
                        target_state=TaskStatus.RUNNING,
                        actor="system",
                        reason=f"prepare_review_gate:{review_id}",
                        commit=False,
                    )
                TaskStateMachine.transition(
                    session=db,
                    task_id=task.id,
                    target_state=TaskStatus.WAITING_REVIEW,
                    actor="system",
                    reason=f"review_gate_created:{review_id}",
                    commit=False,
                )
            db.commit()
            db.refresh(review)
            db.refresh(task)
        except Exception:
            db.rollback()
            raise

        serialized = _serialize_review(review, task=task, extra_secrets=extra_secrets)

    await _broadcast_review_event(
        request,
        task.id,
        {
            "event": "review_requested",
            "type": "review_requested",
            "task_id": task.id,
            "review_id": review.id,
            "data": serialized,
        },
    )
    return {"status": "success", "data": serialized}


@router.get("", status_code=status.HTTP_200_OK)
def list_review_gates(
    request: Request,
    task_id: Optional[str] = Query(default=None),
    review_status: Optional[str] = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List HIL review gates with optional filtering by task_id and status."""
    query = db.query(ReviewGate)
    if task_id:
        query = query.filter(ReviewGate.task_id == task_id)
    if review_status:
        query = query.filter(ReviewGate.status == review_status)

    reviews = query.order_by(ReviewGate.created_at.desc()).all()
    extra_secrets = _get_extra_secrets(request)
    task_cache: dict[str, Optional[Task]] = {}
    items: list[dict[str, Any]] = []
    for rev in reviews:
        if rev.task_id not in task_cache:
            task_cache[rev.task_id] = db.get(Task, rev.task_id)
        items.append(
            _serialize_review(
                rev, task=task_cache[rev.task_id], extra_secrets=extra_secrets
            )
        )
    return {"status": "success", "data": items}


@router.get("/{review_id}", status_code=status.HTTP_200_OK)
def get_review_gate(
    review_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve a single ReviewGate by ID."""
    review = db.get(ReviewGate, review_id)
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ReviewGate '{review_id}' not found",
        )
    task = db.get(Task, review.task_id)
    extra_secrets = _get_extra_secrets(request)
    return {
        "status": "success",
        "data": _serialize_review(review, task=task, extra_secrets=extra_secrets),
    }


@router.patch("/{review_id}/decide", status_code=status.HTTP_200_OK)
async def decide_review_gate(
    review_id: str,
    payload: DecideReviewRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Submit a human decision ('approve', 'edit', or 'reject') on a pending ReviewGate."""
    initial_review = db.get(ReviewGate, review_id)
    if initial_review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ReviewGate '{review_id}' not found",
        )

    task_lock = _get_task_review_lock(request, initial_review.task_id)
    async with task_lock:
        db.expire_all()
        review = db.get(ReviewGate, review_id)
        if review is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"ReviewGate '{review_id}' not found",
            )

        task = db.get(Task, review.task_id)
        if task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task '{review.task_id}' for ReviewGate '{review_id}' not found",
            )

        if review.status == "expired":
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail=f"ReviewGate '{review_id}' has expired",
            )

        if review.status != "pending" or review.decided_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"ReviewGate '{review_id}' has already been decided or claimed with status '{review.status}'",
            )

        now_utc = datetime.now(timezone.utc)
        effective_expires_at = _resolve_expires_at(review)
        if effective_expires_at <= now_utc:
            try:
                review.status = "expired"
                db.commit()
            except Exception:
                db.rollback()
                raise
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail=f"ReviewGate '{review_id}' expired at {effective_expires_at.isoformat()}",
            )

        current_task_status = (
            TaskStatus(task.status) if isinstance(task.status, str) else task.status
        )
        if current_task_status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot decide review for task in terminal status '{current_task_status.value}'",
            )
        if current_task_status not in (TaskStatus.WAITING_REVIEW, TaskStatus.RUNNING):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Task '{task.id}' in status '{current_task_status.value}' cannot accept a review decision",
            )

        normalized_decision = (payload.decision or "").strip().lower()
        if normalized_decision not in ("approve", "edit", "reject"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="decision must be one of: 'approve', 'edit', 'reject'",
            )

        raw_feedback = (
            payload.feedback_text
            if payload.feedback_text is not None
            else payload.feedback
        )
        if normalized_decision == "reject":
            if (
                not raw_feedback
                or len(raw_feedback.strip()) < MIN_REJECT_FEEDBACK_LENGTH
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Rejection requires feedback_text with at least "
                        f"{MIN_REJECT_FEEDBACK_LENGTH} non-whitespace characters"
                    ),
                )

        extra_secrets = _get_extra_secrets(request)
        masked_actor = str(
            mask_secrets(payload.actor.strip(), extra_secrets=extra_secrets)
        )[:64]
        masked_feedback = (
            mask_secrets(raw_feedback.strip(), extra_secrets=extra_secrets)
            if raw_feedback is not None and raw_feedback.strip()
            else None
        )
        raw_edited = (
            payload.edited_content
            if payload.edited_content is not None
            else payload.edited_payload
        )
        masked_edited = (
            mask_secrets(raw_edited, extra_secrets=extra_secrets)
            if raw_edited is not None
            else None
        )

        # Atomic conditional claim prevents TOCTOU races across concurrent requests
        try:
            claim_result = db.execute(
                update(ReviewGate)
                .where(
                    ReviewGate.id == review_id,
                    ReviewGate.status == "pending",
                    ReviewGate.decided_at.is_(None),
                )
                .values(status="processing")
            )
            if claim_result.rowcount != 1:
                db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"ReviewGate '{review_id}' is already being processed or decided",
                )
            db.commit()
        except HTTPException:
            raise
        except Exception:
            db.rollback()
            raise

        cp_db_path = _get_checkpoint_db_path(request)
        checkpoint_id = review.checkpoint_id
        task_id = task.id

        if normalized_decision in ("approve", "edit"):
            resume_payload: dict[str, Any] = {
                "approved": True,
                "decision": normalized_decision,
                "feedback": masked_feedback,
                "edited_content": masked_edited,
                "review_id": review.id,
                "actor": masked_actor,
            }
        else:
            resume_payload = {
                "approved": False,
                "decision": "reject",
                "feedback": masked_feedback,
                "review_id": review.id,
                "actor": masked_actor,
            }

        # Offload blocking SQLite/LangGraph resume off the asyncio event loop
        try:
            resume_outcome = await asyncio.to_thread(
                _resume_graph_if_interrupted,
                cp_db_path,
                task_id,
                checkpoint_id,
                resume_payload,
            )
        except Exception:
            _revert_processing_claim(db, review_id)
            raise

        graph_resumed = False
        graph_status: Optional[str] = None
        if resume_outcome is not None:
            graph_resumed = True
            resumed_state = resume_outcome["state"]
            if isinstance(resumed_state, dict):
                if "__interrupt__" in resumed_state:
                    graph_status = "waiting_review"
                else:
                    graph_status = str(
                        resumed_state.get("status")
                        or ("rejected" if normalized_decision == "reject" else "completed")
                    )

        # Reload fresh state and perform all DB updates + FSM transitions in ONE atomic commit
        db.expire_all()
        review = db.get(ReviewGate, review_id)
        task = db.get(Task, task_id)
        if review is None or task is None:
            _revert_processing_claim(db, review_id)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"ReviewGate '{review_id}' or Task '{task_id}' disappeared during processing",
            )

        next_turn_number: Optional[int] = None
        re_enqueued = False
        meta = dict(task.task_metadata or {})
        reviews_meta = dict(meta.get("reviews") or {})
        review_entry = dict(reviews_meta.get(review.id) or {})

        try:
            if current_task_status == TaskStatus.RUNNING:
                TaskStateMachine.transition(
                    session=db,
                    task_id=task.id,
                    target_state=TaskStatus.WAITING_REVIEW,
                    actor="system",
                    reason=f"enter_review_gate:{review.id}",
                    commit=False,
                )

            if normalized_decision in ("approve", "edit"):
                review.status = (
                    "approved" if normalized_decision == "approve" else "edited"
                )
                review.decision = normalized_decision
                review.feedback_text = masked_feedback
                review.actor = masked_actor
                review.decided_at = now_utc

                if masked_edited is not None:
                    review_entry["edited_content"] = masked_edited
                review_entry["decision"] = normalized_decision
                review_entry["decided_at"] = now_utc.isoformat()
                reviews_meta[review.id] = review_entry
                meta["reviews"] = reviews_meta
                meta["latest_review_decision"] = normalized_decision
                task.task_metadata = meta
                flag_modified(task, "task_metadata")

                TaskStateMachine.transition(
                    session=db,
                    task_id=task.id,
                    target_state=TaskStatus.APPROVED,
                    actor=masked_actor,
                    reason=f"review_{normalized_decision}:{review.id}",
                    commit=False,
                )
                if graph_resumed:
                    if graph_status == "waiting_review":
                        TaskStateMachine.transition(
                            session=db,
                            task_id=task.id,
                            target_state=TaskStatus.RUNNING,
                            actor="system",
                            reason="resumed_next_wave",
                            commit=False,
                        )
                        TaskStateMachine.transition(
                            session=db,
                            task_id=task.id,
                            target_state=TaskStatus.WAITING_REVIEW,
                            actor="system",
                            reason="next_hil_gate",
                            commit=False,
                        )
                    elif graph_status == "completed":
                        TaskStateMachine.transition(
                            session=db,
                            task_id=task.id,
                            target_state=TaskStatus.COMPLETED,
                            actor="system",
                            reason="langgraph_resumed_completed",
                            commit=False,
                        )
            else:
                review.status = "rejected"
                review.decision = "reject"
                review.feedback_text = masked_feedback
                review.actor = masked_actor
                review.decided_at = now_utc

                max_turn = (
                    db.query(func.max(TurnLog.turn_number))
                    .filter(TurnLog.task_id == task.id)
                    .scalar()
                )
                next_turn_number = (int(max_turn) if max_turn is not None else 0) + 1
                re_enqueued = True

                review_entry["decision"] = "reject"
                review_entry["feedback_text"] = masked_feedback
                review_entry["decided_at"] = now_utc.isoformat()
                reviews_meta[review.id] = review_entry
                meta["reviews"] = reviews_meta
                meta["latest_review_decision"] = "reject"
                meta["turn_number"] = next_turn_number
                meta["re_enqueued"] = True
                meta["last_rejection_feedback"] = masked_feedback
                task.task_metadata = meta
                flag_modified(task, "task_metadata")

                turn_log = TurnLog(
                    id=f"turn-{uuid.uuid4().hex[:12]}",
                    task_id=task.id,
                    subtask_id=None,
                    agent_id=task.assigned_agent_id,
                    turn_number=next_turn_number,
                    action="review_rejected",
                    tool="hil_review_gate",
                    input_payload={
                        "review_id": review.id,
                        "gate_type": review.gate_type,
                        "decision": "reject",
                        "feedback_text": masked_feedback,
                        "actor": masked_actor,
                    },
                    output_payload={
                        "re_enqueued": True,
                        "turn_number": next_turn_number,
                    },
                    duration_ms=0,
                    tokens=0,
                    status="rejected",
                    created_at=now_utc,
                )
                db.add(turn_log)

                TaskStateMachine.transition(
                    session=db,
                    task_id=task.id,
                    target_state=TaskStatus.REJECTED,
                    actor=masked_actor,
                    reason=masked_feedback,
                    commit=False,
                )
                TaskStateMachine.transition(
                    session=db,
                    task_id=task.id,
                    target_state=TaskStatus.RUNNING,
                    actor="system",
                    reason=f"re_enqueued_turn_{next_turn_number}",
                    commit=False,
                )

            db.commit()
            db.refresh(review)
            db.refresh(task)
        except Exception:
            _revert_processing_claim(db, review_id)
            raise

        resolved_task_status = (
            task.status.value if isinstance(task.status, TaskStatus) else str(task.status)
        )
        serialized = _serialize_review(
            review,
            task=task,
            extra_secrets=extra_secrets,
            extra={
                "task_status": resolved_task_status,
                "graph_resumed": graph_resumed,
                "graph_status": graph_status,
                "turn_number": next_turn_number,
                "re_enqueued": re_enqueued,
            },
        )

    await _broadcast_review_event(
        request,
        task_id,
        {
            "event": "review_decided",
            "type": "review_decided",
            "task_id": task_id,
            "review_id": review.id,
            "decision": normalized_decision,
            "status": review.status,
            "task_status": resolved_task_status,
            "turn_number": next_turn_number,
            "re_enqueued": re_enqueued,
            "data": serialized,
        },
    )

    return {"status": "success", "data": serialized}
