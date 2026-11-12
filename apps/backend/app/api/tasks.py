"""Task API endpoints for Master Commander NLP input, intent parsing, and history."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, sessionmaker

from app.config import AppSettings, get_settings
from app.db.models import Agent, Project, SubTask, Task, TaskStatus, TurnLog
from app.db.session import DEFAULT_AGENTS, get_db, init_db
from app.llm.router import LlmRouter
from app.orchestrator.dispatcher import AgentDispatcher, mask_secrets
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


def _serialize_turn(turn: TurnLog) -> dict[str, Any]:
    return mask_secrets(
        {
            "id": turn.id,
            "task_id": turn.task_id,
            "subtask_id": turn.subtask_id,
            "agent_id": turn.agent_id,
            "turn_number": turn.turn_number,
            "action": turn.action,
            "tool": turn.tool,
            "input_payload": turn.input_payload,
            "output_payload": turn.output_payload,
            "duration_ms": turn.duration_ms,
            "tokens": turn.tokens,
            "status": turn.status,
            "error_message": turn.error_message,
            "created_at": turn.created_at.isoformat() if turn.created_at else None,
        }
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
        return ExecutionPlan(
            task_id=task.id,
            task_type=str(existing_plan.get("task_type") or meta.get("task_type") or "general"),
            nodes=nodes,
            waves=waves,
            mode=str(existing_plan.get("mode") or mode),
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
    turn_count = db.query(TurnLog).filter(TurnLog.task_id == task_id).count()

    return {
        "status": "success",
        "data": {
            "id": task.id,
            "project_id": task.project_id,
            "title": task.title,
            "description": task.description,
            "status": task.status.value if isinstance(task.status, TaskStatus) else str(task.status),
            "priority": task.priority,
            "assigned_agent_id": task.assigned_agent_id,
            "metadata": task.task_metadata,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "updated_at": task.updated_at.isoformat() if task.updated_at else None,
            "turn_count": turn_count,
            "subtasks": [
                {
                    "id": st.id,
                    "agent_id": st.agent_id,
                    "title": st.title,
                    "instruction": st.instruction,
                    "status": st.status,
                    "depends_on": st.depends_on or [],
                    "order_index": st.order_index,
                    "result": mask_secrets(st.result),
                }
                for st in subtasks
            ],
        },
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
        TaskStatus.COMPLETED,
        TaskStatus.CANCELLED,
        TaskStatus.WAITING_REVIEW,
    ):
        raise HTTPException(
            status_code=422,
            detail=f"Task '{task_id}' is in status '{task.status.value}' and cannot be dispatched",
        )

    plan = _build_plan_for_task(task, db, payload)
    meta = dict(task.task_metadata or {})
    meta["plan"] = plan.to_dict()
    task.task_metadata = meta
    db.commit()

    session_factory = _get_session_factory(request)
    ws_manager = getattr(request.app.state, "ws_manager", None)
    llm_router = getattr(request.app.state, "llm_router", None) or LlmRouter()

    dispatcher = AgentDispatcher(
        max_parallel=(payload.max_parallel if payload and payload.max_parallel else 3),
        timeout_seconds=(payload.timeout_seconds if payload and payload.timeout_seconds else 300.0),
        session_factory=session_factory,
        ws_manager=ws_manager,
        llm_router=llm_router,
    )
    result = await dispatcher.dispatch(task_id=task_id, plan=plan)

    return {
        "status": "success",
        "data": result.to_dict(),
    }


@router.get("/{task_id}/turns", status_code=status.HTTP_200_OK)
def get_task_turns(
    task_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List immutable secret-masked TurnLog execution records for task_id."""
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_id}' not found",
        )

    turns = (
        db.query(TurnLog)
        .filter(TurnLog.task_id == task_id)
        .order_by(TurnLog.turn_number.asc(), TurnLog.created_at.asc())
        .all()
    )
    return {
        "status": "success",
        "data": [_serialize_turn(t) for t in turns],
    }
