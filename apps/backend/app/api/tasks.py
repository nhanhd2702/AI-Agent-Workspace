"""Task API endpoints for Master Commander NLP input, intent parsing, and history."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session, sessionmaker

from app.config import AppSettings, get_settings
from app.db.models import Agent, Project, SubTask, Task, TaskAuditLog, TaskStatus, TurnLog
from app.db.session import DEFAULT_AGENTS, get_db, init_db
from app.db.state_machine import InvalidStateTransitionError, TaskStateMachine
from app.llm.router import LlmRouter
from app.orchestrator.dispatcher import (
    AgentDispatcher,
    TaskDispatchConflictError,
    mask_secrets,
)
from app.orchestrator.handoff import (
    HandoffContractError,
    HandoffError,
    HandoffLimitError,
    HandoffLoopError,
    HandoffManager,
    HandoffNotFoundError,
)
from app.orchestrator.parser import ParsedIntent, PromptValidationError, TaskParser
from app.orchestrator.planner import DagCycleError, DagPlanner, ExecutionPlan, SubTaskNode

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


class ParseTaskRequest(BaseModel):
    """Payload for natural language task prompt parsing."""

    model_config = ConfigDict(populate_by_name=True)

    project_id: str = Field(default="proj-default", alias="projectId")
    prompt_text: str = Field(..., alias="promptText")
    attachment_ids: list[str] = Field(default_factory=list, alias="attachments")
    mode: str = Field(default="copilot")


class SubTaskNodeInput(BaseModel):
    """Optional custom DAG node override supplied on dispatch."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., min_length=1, max_length=64)
    agent_id: str = Field(..., min_length=1, max_length=64, alias="agentId")
    instruction: str = Field(..., min_length=1)
    depends_on: list[str] = Field(default_factory=list, alias="dependsOn")
    requires_review: bool = Field(default=False, alias="requiresReview")
    metadata: dict[str, Any] = Field(default_factory=dict)


class DispatchTaskRequest(BaseModel):
    """Optional payload for dispatching a task's DAG execution."""

    model_config = ConfigDict(populate_by_name=True)

    mode: Optional[str] = None
    nodes: Optional[list[SubTaskNodeInput]] = None
    timeout_seconds: Optional[float] = Field(default=None, gt=0.0, alias="timeoutSeconds")
    max_parallel: Optional[int] = Field(default=None, ge=1, le=10, alias="maxParallel")


class TaskHandoffRequest(BaseModel):
    """Payload to transfer task execution to another agent via handoff protocol."""

    model_config = ConfigDict(populate_by_name=True)

    from_agent: str = Field(..., alias="fromAgent", min_length=1)
    to_agent: str = Field(..., alias="toAgent", min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    artifact_ids: list[str] = Field(default_factory=list, alias="artifactIds")


class TaskStateTransitionRequest(BaseModel):
    """Payload to transition a Task via TaskStateMachine."""

    model_config = ConfigDict(populate_by_name=True)

    target_state: Optional[str] = Field(default=None, alias="targetState")
    status: Optional[str] = None
    state: Optional[str] = None
    actor: str = Field(default="user", min_length=1, max_length=64)
    reason: Optional[str] = None


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_utc_iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return _ensure_utc(dt).isoformat()


def _get_history_file(request: Request) -> Path:
    """Resolves prompt history file path from app settings."""
    settings: AppSettings = getattr(request.app.state, "settings", None) or get_settings()
    return (settings.workspace_dir / "prompt_history.json").resolve()


def _get_session_factory(request: Request) -> sessionmaker[Session]:
    """Resolve isolated sessionmaker for concurrent async dispatcher execution."""
    factory = getattr(request.app.state, "session_factory", None)
    if factory is not None:
        return factory
    settings: AppSettings = getattr(request.app.state, "settings", None) or get_settings()
    return init_db(settings.resolved_db_path, cache=True)


def _get_extra_secrets(request: Request) -> list[str]:
    settings: AppSettings = getattr(request.app.state, "settings", None) or get_settings()
    return [settings.local_auth_token] if settings.local_auth_token else []


def _serialize_turn(
    turn: TurnLog,
    extra_secrets: Optional[list[str]] = None,
    agent_map: Optional[dict[str, Agent]] = None,
) -> dict[str, Any]:
    agent = agent_map.get(turn.agent_id) if (agent_map and turn.agent_id) else None
    steps: list[dict[str, Any]] = []
    if isinstance(turn.output_payload, dict) and isinstance(
        turn.output_payload.get("steps"), list
    ):
        steps = list(turn.output_payload["steps"])

    return mask_secrets(
        {
            "id": turn.id,
            "log_type": "turn",
            "task_id": turn.task_id,
            "subtask_id": turn.subtask_id,
            "agent_id": turn.agent_id,
            "agent_name": agent.name if agent else None,
            "agent_display_name": agent.display_name if agent else None,
            "turn_number": turn.turn_number,
            "action": turn.action,
            "tool": turn.tool,
            "input_payload": turn.input_payload,
            "output_payload": turn.output_payload,
            "steps": steps,
            "duration_ms": turn.duration_ms,
            "tokens": turn.tokens,
            "status": turn.status,
            "error_message": turn.error_message,
            "created_at": _format_utc_iso(turn.created_at),
        },
        extra_secrets=extra_secrets,
    )


def _serialize_task(
    task: Task,
    db: Session,
    extra_secrets: Optional[list[str]] = None,
    agent_map: Optional[dict[str, Agent]] = None,
    turn_counts: Optional[dict[str, int]] = None,
) -> dict[str, Any]:
    agent: Optional[Agent] = None
    if task.assigned_agent_id:
        if agent_map is not None:
            agent = agent_map.get(task.assigned_agent_id)
        else:
            agent = db.get(Agent, task.assigned_agent_id)

    if turn_counts is not None:
        turn_count = turn_counts.get(task.id, 0)
    else:
        turn_count = db.query(TurnLog).filter(TurnLog.task_id == task.id).count()
    status_val = (
        task.status.value if isinstance(task.status, TaskStatus) else str(task.status)
    )
    agent_name = agent.name if agent else None
    agent_display_name = agent.display_name if agent else None

    return mask_secrets(
        {
            "id": task.id,
            "project_id": task.project_id,
            "title": task.title,
            "description": task.description,
            "status": status_val,
            "priority": task.priority,
            "assigned_agent_id": task.assigned_agent_id,
            "agent_name": agent_name,
            "agentName": agent_name,
            "agent_display_name": agent_display_name,
            "metadata": task.task_metadata,
            "turn_count": turn_count,
            "started_at": _format_utc_iso(task.started_at),
            "completed_at": _format_utc_iso(task.completed_at),
            "created_at": _format_utc_iso(task.created_at),
            "updated_at": _format_utc_iso(task.updated_at),
        },
        extra_secrets=extra_secrets,
    )


def _build_plan_for_task(
    task: Task,
    db: Session,
    payload: Optional[DispatchTaskRequest],
) -> ExecutionPlan:
    meta = dict(task.task_metadata or {})
    mode = (payload.mode if payload and payload.mode else None) or meta.get("mode") or "autopilot"

    if payload and payload.nodes is not None:
        raw_nodes = [
            SubTaskNode(
                id=n.id,
                agent_id=n.agent_id,
                instruction=n.instruction,
                depends_on=list(n.depends_on),
                requires_review=n.requires_review,
                metadata=dict(n.metadata),
            )
            for n in payload.nodes
        ]
        try:
            ordered = DagPlanner.validate_dag(raw_nodes)
            waves = DagPlanner.compute_waves(ordered)
        except (DagCycleError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        return ExecutionPlan(
            task_id=task.id,
            task_type=str(meta.get("task_type") or "general"),
            nodes=ordered,
            waves=waves,
            mode=mode,
        )

    existing_plan = meta.get("plan")
    if isinstance(existing_plan, dict) and existing_plan.get("nodes"):
        nodes = [
            SubTaskNode(
                id=str(n["id"]),
                agent_id=str(n["agent_id"]),
                instruction=str(n["instruction"]),
                depends_on=list(n.get("depends_on") or []),
                requires_review=bool(n.get("requires_review", False)),
                metadata=dict(n.get("metadata") or {}),
            )
            for n in existing_plan["nodes"]
        ]
        waves = list(existing_plan.get("waves") or DagPlanner.compute_waves(nodes))
        resolved_mode = (
            payload.mode
            if (payload is not None and payload.mode)
            else str(existing_plan.get("mode") or mode)
        )
        return ExecutionPlan(
            task_id=task.id,
            task_type=str(existing_plan.get("task_type") or meta.get("task_type") or "general"),
            nodes=nodes,
            waves=waves,
            mode=resolved_mode,
        )

    raw_prompt = task.description or task.title
    intent = ParsedIntent(
        raw_prompt=raw_prompt,
        cleaned_prompt=raw_prompt,
        task_type=str(meta.get("task_type") or "general"),
        intent=str(meta.get("intent") or "general"),
        mentioned_agents=list(meta.get("mentioned_agents") or []),
        urls=list(meta.get("urls") or []),
        attachment_ids=list(meta.get("attachment_ids") or []),
        entities=dict(meta.get("entities") or {}),
        urgency="urgent" if task.priority == "high" else "normal",
    )
    agents = db.query(Agent).all()
    try:
        return DagPlanner.build_plan(
            intent=intent,
            agents=agents,
            task_id=task.id,
            mode=mode,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc


@router.post("/parse", status_code=status.HTTP_200_OK)
def parse_task(
    payload: ParseTaskRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Parse user command into structured ParsedIntent, extract entities, and create Task record."""
    history_file = _get_history_file(request)
    parser = TaskParser(history_file=history_file)

    # 1. Fetch available agents from registry
    try:
        known_agents = [row[0] for row in db.query(Agent.name).all()]
    except Exception:
        known_agents = []

    if not known_agents:
        known_agents = [a["name"] for a in DEFAULT_AGENTS]

    # 2. Parse and validate prompt (do not record history until commit succeeds)
    try:
        parsed = parser.parse(
            prompt_text=payload.prompt_text,
            attachment_ids=payload.attachment_ids,
            known_agents=known_agents,
            record_history=False,
        )
    except PromptValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    # 3. Validate project existence
    project = db.get(Project, payload.project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{payload.project_id}' not found",
        )

    # 4. Resolve assigned agent if tagged
    assigned_agent_id: Optional[str] = None
    if parsed.mentioned_agents:
        first_agent_name = parsed.mentioned_agents[0]
        agent_record = db.query(Agent).filter_by(name=first_agent_name).first()
        if agent_record:
            assigned_agent_id = agent_record.id

    # 5. Create and persist Task in PENDING status
    task_id = f"task-{uuid.uuid4().hex[:12]}"
    raw_prompt = parsed.raw_prompt.strip()
    title = (raw_prompt[:77] + "...") if len(raw_prompt) > 80 else raw_prompt

    task = Task(
        id=task_id,
        project_id=payload.project_id,
        title=title,
        description=raw_prompt,
        status=TaskStatus.PENDING,
        assigned_agent_id=assigned_agent_id,
        priority="high" if parsed.urgency == "urgent" else "normal",
        task_metadata={
            "intent": parsed.intent,
            "task_type": parsed.task_type,
            "entities": parsed.entities,
            "mentioned_agents": parsed.mentioned_agents,
            "urls": parsed.urls,
            "attachment_ids": parsed.attachment_ids,
            "mode": payload.mode,
        },
    )
    try:
        db.add(task)
        db.commit()
        db.refresh(task)
    except Exception:
        db.rollback()
        raise

    # 6. Record prompt history ONLY after DB commit succeeds
    parser.record_prompt(parsed.raw_prompt)

    return {
        "status": "success",
        "data": {
            "task_id": task.id,
            "intent": parsed.intent,
            "task_type": parsed.task_type,
            "mentioned_agents": parsed.mentioned_agents,
            "urls": parsed.urls,
            "attachment_ids": parsed.attachment_ids,
            "entities": parsed.entities,
            "plan": None,
        },
    }


@router.get("", status_code=status.HTTP_200_OK)
def list_tasks(
    request: Request,
    project_id: Optional[str] = Query(default=None),
    projectId: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    assigned_agent_id: Optional[str] = Query(default=None),
    assignedAgentId: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List tasks with optional project, status, and agent filters for Kanban/List board."""
    resolved_project_id = project_id or projectId
    resolved_agent_id = assigned_agent_id or assignedAgentId

    query = db.query(Task)
    if resolved_project_id:
        query = query.filter(Task.project_id == resolved_project_id)
    if status_filter:
        try:
            status_enum = TaskStatus(status_filter.strip().lower())
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid task status '{status_filter}'",
            ) from exc
        query = query.filter(Task.status == status_enum)
    if resolved_agent_id:
        query = query.filter(Task.assigned_agent_id == resolved_agent_id)

    tasks = (
        query.order_by(Task.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    agents = db.query(Agent).all()
    agent_map = {a.id: a for a in agents}
    task_ids = [t.id for t in tasks]
    turn_counts: dict[str, int] = {}
    if task_ids:
        rows = (
            db.query(TurnLog.task_id, func.count(TurnLog.id))
            .filter(TurnLog.task_id.in_(task_ids))
            .group_by(TurnLog.task_id)
            .all()
        )
        turn_counts = {tid: int(cnt) for tid, cnt in rows}
    extra_secrets = _get_extra_secrets(request)

    return {
        "status": "success",
        "data": [
            _serialize_task(
                t,
                db,
                extra_secrets=extra_secrets,
                agent_map=agent_map,
                turn_counts=turn_counts,
            )
            for t in tasks
        ],
    }


@router.get("/history", status_code=status.HTTP_200_OK)
def get_task_history(
    request: Request,
    query: Optional[str] = Query(default=None, description="Filter prompts by substring"),
    limit: int = Query(default=50, ge=1, le=50, description="Max entries to return"),
) -> dict[str, Any]:
    """Retrieve recent prompt history (up to 50) for UI autocomplete."""
    history_file = _get_history_file(request)
    parser = TaskParser(history_file=history_file)
    history = parser.get_history(query=query, limit=limit)
    return {
        "status": "success",
        "data": history,
    }


@router.get("/{task_id}", status_code=status.HTTP_200_OK)
def get_task(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve Task details, subtasks, and execution turn count."""
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' not found",
        )

    subtasks = (
        db.query(SubTask)
        .filter(SubTask.task_id == task_id)
        .order_by(SubTask.order_index.asc())
        .all()
    )
    extra_secrets = _get_extra_secrets(request)

    return {
        "status": "success",
        "data": {
            **_serialize_task(task, db, extra_secrets=extra_secrets),
            "subtasks": [
                {
                    "id": st.id,
                    "agent_id": st.agent_id,
                    "title": st.title,
                    "instruction": st.instruction,
                    "status": st.status,
                    "depends_on": st.depends_on or [],
                    "order_index": st.order_index,
                    "result": mask_secrets(st.result, extra_secrets=extra_secrets),
                }
                for st in subtasks
            ],
        },
    }


@router.patch("/{task_id}/state", status_code=status.HTTP_200_OK)
async def transition_task_state(
    task_id: str,
    payload: TaskStateTransitionRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Transition a Task via TaskStateMachine, returning 409 on invalid FSM transitions."""
    raw_target = payload.target_state or payload.status or payload.state
    if not raw_target or not raw_target.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="target_state is required",
        )

    try:
        target_status = TaskStatus(raw_target.strip().lower())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid target_state '{raw_target}'",
        ) from exc

    existing = db.get(Task, task_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' not found",
        )

    previous_status = (
        existing.status.value
        if isinstance(existing.status, TaskStatus)
        else str(existing.status)
    )
    extra_secrets = _get_extra_secrets(request)
    masked_actor = str(
        mask_secrets((payload.actor or "user").strip() or "user", extra_secrets=extra_secrets)
    )[:64]
    masked_reason = (
        str(mask_secrets(payload.reason.strip(), extra_secrets=extra_secrets))
        if payload.reason and payload.reason.strip()
        else None
    )

    try:
        updated_task = TaskStateMachine.transition(
            session=db,
            task_id=task_id,
            target_state=target_status,
            actor=masked_actor,
            reason=masked_reason,
            commit=False,
        )
        db.commit()
        db.refresh(updated_task)
    except InvalidStateTransitionError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except Exception:
        db.rollback()
        raise

    serialized = _serialize_task(updated_task, db, extra_secrets=extra_secrets)

    ws_manager = getattr(request.app.state, "ws_manager", None)
    if ws_manager is not None:
        try:
            await ws_manager.broadcast(
                task_id=task_id,
                event={
                    "event": "task_status",
                    "type": "task_status",
                    "task_id": task_id,
                    "from_status": previous_status,
                    "status": serialized["status"],
                    "actor": masked_actor,
                    "reason": masked_reason,
                    "data": serialized,
                },
            )
        except Exception:
            pass

    return {
        "status": "success",
        "data": serialized,
    }


@router.get("/{task_id}/logs", status_code=status.HTTP_200_OK)
def get_task_logs(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return chronological secret-masked TurnLog & TaskAuditLog timeline for task_id."""
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' not found",
        )

    extra_secrets = _get_extra_secrets(request)
    agents = db.query(Agent).all()
    agent_map = {a.id: a for a in agents}

    turns = (
        db.query(TurnLog)
        .filter(TurnLog.task_id == task_id)
        .order_by(TurnLog.turn_number.asc(), TurnLog.created_at.asc())
        .all()
    )
    audits = (
        db.query(TaskAuditLog)
        .filter(TaskAuditLog.task_id == task_id)
        .order_by(TaskAuditLog.created_at.asc())
        .all()
    )

    timeline: list[tuple[datetime, int, int, dict[str, Any]]] = []

    for idx, audit in enumerate(audits):
        dt = _ensure_utc(audit.created_at) if audit.created_at else datetime.now(timezone.utc)
        entry = mask_secrets(
            {
                "id": audit.id,
                "log_type": "audit",
                "task_id": audit.task_id,
                "subtask_id": None,
                "agent_id": None,
                "agent_name": None,
                "turn_number": None,
                "action": "state_transition",
                "tool": "fsm",
                "from_status": audit.from_status,
                "to_status": audit.to_status,
                "actor": audit.actor,
                "reason": audit.reason,
                "status": audit.to_status,
                "steps": [],
                "duration_ms": None,
                "tokens": None,
                "created_at": dt.isoformat(),
            },
            extra_secrets=extra_secrets,
        )
        timeline.append((dt, 0, idx, entry))

    for turn in turns:
        dt = _ensure_utc(turn.created_at) if turn.created_at else datetime.now(timezone.utc)
        entry = _serialize_turn(turn, extra_secrets=extra_secrets, agent_map=agent_map)
        timeline.append((dt, 1, int(turn.turn_number or 0), entry))

    timeline.sort(key=lambda item: (item[0], item[1], item[2]))

    return {
        "status": "success",
        "data": [item[3] for item in timeline],
    }


@router.post("/{task_id}/dispatch", status_code=status.HTTP_200_OK)
async def dispatch_task(
    task_id: str,
    request: Request,
    payload: Optional[DispatchTaskRequest] = Body(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Build or load ExecutionPlan for task_id and dispatch waves via AgentDispatcher."""
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' not found",
        )

    if task.status in (
        TaskStatus.RUNNING,
        TaskStatus.WAITING_REVIEW,
        TaskStatus.COMPLETED,
        TaskStatus.CANCELLED,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Task '{task_id}' cannot be dispatched from status '{task.status.value}'",
        )

    plan = _build_plan_for_task(task, db, payload)
    meta = dict(task.task_metadata or {})
    meta["plan"] = plan.to_dict()
    task.task_metadata = meta
    db.commit()

    session_factory = _get_session_factory(request)
    ws_manager = getattr(request.app.state, "ws_manager", None)
    llm_router = getattr(request.app.state, "llm_router", None) or LlmRouter()
    extra_secrets = _get_extra_secrets(request)

    dispatcher = AgentDispatcher(
        max_parallel=(payload.max_parallel if payload and payload.max_parallel else 3),
        timeout_seconds=(payload.timeout_seconds if payload and payload.timeout_seconds else 300.0),
        session_factory=session_factory,
        ws_manager=ws_manager,
        llm_router=llm_router,
        extra_secrets=extra_secrets,
    )
    try:
        result = await dispatcher.dispatch(task_id=task_id, plan=plan)
    except TaskDispatchConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return {
        "status": "success",
        "data": result.to_dict(),
    }


@router.get("/{task_id}/turns", status_code=status.HTTP_200_OK)
def get_task_turns(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List immutable secret-masked TurnLog execution records for task_id."""
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' not found",
        )

    extra_secrets = _get_extra_secrets(request)
    turns = (
        db.query(TurnLog)
        .filter(TurnLog.task_id == task_id)
        .order_by(TurnLog.turn_number.asc(), TurnLog.created_at.asc())
        .all()
    )
    return {
        "status": "success",
        "data": [_serialize_turn(t, extra_secrets=extra_secrets) for t in turns],
    }


@router.post("/{task_id}/handoff", status_code=status.HTTP_200_OK)
async def handoff_task(
    task_id: str,
    payload: TaskHandoffRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Execute validated Agent-to-Agent handoff protocol according to F05.2."""
    extra_secrets = _get_extra_secrets(request)
    manager = HandoffManager(max_depth=5, extra_secrets=extra_secrets)

    try:
        record = manager.execute_handoff(
            db=db,
            task_id=task_id,
            from_agent=payload.from_agent,
            to_agent=payload.to_agent,
            payload=payload.payload,
            artifact_ids=payload.artifact_ids,
        )
    except HandoffNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except HandoffContractError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except (HandoffLoopError, HandoffLimitError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except HandoffError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    # Broadcast handoff event via WebSocket manager if attached
    ws_manager = getattr(request.app.state, "ws_manager", None)
    if ws_manager is not None:
        try:
            await ws_manager.broadcast(
                task_id=task_id,
                event={
                    "event": "handoff",
                    "type": "handoff",
                    "task_id": task_id,
                    "data": record.to_dict(),
                },
            )
        except Exception:
            pass

    return {
        "status": "success",
        "data": record.to_dict(),
    }
