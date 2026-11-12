"""Task Finite State Machine (FSM) and lifecycle management.

Complies strictly with BA Specification F01.4:
Valid transitions:
- pending -> running -> waiting_review -> approved -> delivered -> completed
- Side-branches: rejected -> running, paused -> running/cancelled/failed, failed -> running/cancelled
- Terminal states: completed, cancelled (no further transitions permitted)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import Task, TaskAuditLog, TaskStatus


class InvalidStateTransitionError(Exception):
    """Raised when an illegal Task lifecycle transition is attempted."""

    def __init__(
        self,
        from_state: TaskStatus | str,
        to_state: TaskStatus | str,
        message: Optional[str] = None,
    ) -> None:
        self.from_state = from_state
        self.to_state = to_state
        msg = message or f"Illegal state transition from '{from_state}' to '{to_state}'"
        super().__init__(msg)


ALLOWED_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {
        TaskStatus.RUNNING,
        TaskStatus.CANCELLED,
        TaskStatus.PAUSED,
    },
    TaskStatus.RUNNING: {
        TaskStatus.WAITING_REVIEW,
        TaskStatus.APPROVED,
        TaskStatus.DELIVERED,
        TaskStatus.COMPLETED,
        TaskStatus.PAUSED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.WAITING_REVIEW: {
        TaskStatus.APPROVED,
        TaskStatus.REJECTED,
        TaskStatus.RUNNING,
        TaskStatus.PAUSED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.APPROVED: {
        TaskStatus.DELIVERED,
        TaskStatus.RUNNING,
        TaskStatus.COMPLETED,
        TaskStatus.PAUSED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.REJECTED: {
        TaskStatus.RUNNING,
        TaskStatus.PAUSED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.DELIVERED: {
        TaskStatus.COMPLETED,
        TaskStatus.RUNNING,
        TaskStatus.PAUSED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.PAUSED: {
        TaskStatus.RUNNING,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.FAILED: {
        TaskStatus.RUNNING,
        TaskStatus.CANCELLED,
    },
    TaskStatus.CANCELLED: set(),
    TaskStatus.COMPLETED: set(),
}


class TaskStateMachine:
    """Manages Task lifecycle state transitions, enforcing FSM constraints and writing audit logs."""

    @staticmethod
    def transition(
        session: Session,
        task_id: str,
        target_state: TaskStatus | str,
        actor: str,
        reason: Optional[str] = None,
    ) -> Task:
        """Transitions a task to a target state, validating against ALLOWED_TRANSITIONS and logging an audit record.

        Args:
            session: Active SQLAlchemy session
            task_id: Unique task identifier
            target_state: Destination TaskStatus enum or string value
            actor: Identity of initiator ("user", "commander", "system", agent slug)
            reason: Optional justification or feedback explaining the transition

        Returns:
            Updated and refreshed Task instance

        Raises:
            ValueError: If task_id does not exist
            InvalidStateTransitionError: If the transition violates F01.4 FSM rules
        """
        task = session.get(Task, task_id)
        if task is None:
            raise ValueError(f"Task with id '{task_id}' not found")

        # Normalize enum representation
        current_status = (
            TaskStatus(task.status) if isinstance(task.status, str) else task.status
        )
        new_status = (
            TaskStatus(target_state) if isinstance(target_state, str) else target_state
        )

        allowed = ALLOWED_TRANSITIONS.get(current_status, set())
        if new_status not in allowed:
            raise InvalidStateTransitionError(
                from_state=current_status,
                to_state=new_status,
                message=(
                    f"Cannot transition task '{task_id}' from {current_status.value} to {new_status.value}. "
                    f"Allowed next states: {[s.value for s in allowed]}"
                ),
            )

        now = datetime.now(timezone.utc)
        task.status = new_status
        task.updated_at = now

        # Update lifecycle timestamps
        if new_status == TaskStatus.RUNNING and task.started_at is None:
            task.started_at = now
        elif new_status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            task.completed_at = now

        # Record immutable audit log
        audit = TaskAuditLog(
            id=str(uuid.uuid4()),
            task_id=task.id,
            from_status=current_status.value,
            to_status=new_status.value,
            actor=actor,
            reason=reason,
            created_at=now,
        )
        session.add(audit)
        session.commit()
        session.refresh(task)
        return task
