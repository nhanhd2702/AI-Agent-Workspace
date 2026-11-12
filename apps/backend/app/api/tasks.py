"""Task API endpoints for Master Commander NLP input, intent parsing, and history."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.config import AppSettings, get_settings
from app.db.models import Agent, Task, TaskStatus
from app.db.session import DEFAULT_AGENTS, get_db
from app.orchestrator.parser import PromptValidationError, TaskParser

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


class ParseTaskRequest(BaseModel):
    """Payload for natural language task prompt parsing."""

    model_config = ConfigDict(populate_by_name=True)

    project_id: str = Field(default="proj-default", alias="projectId")
    prompt_text: str = Field(..., alias="promptText")
    attachment_ids: list[str] = Field(default_factory=list, alias="attachments")
    mode: str = Field(default="copilot")


def _get_history_file(request: Request) -> Path:
    """Resolves prompt history file path from app settings."""
    settings: AppSettings = getattr(request.app.state, "settings", None) or get_settings()
    return (settings.workspace_dir / "prompt_history.json").resolve()


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

    # 2. Parse and validate prompt
    try:
        parsed = parser.parse(
            prompt_text=payload.prompt_text,
            attachment_ids=payload.attachment_ids,
            known_agents=known_agents,
            record_history=True,
        )
    except PromptValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    # 3. Resolve assigned agent if tagged
    assigned_agent_id: Optional[str] = None
    if parsed.mentioned_agents:
        first_agent_name = parsed.mentioned_agents[0]
        agent_record = db.query(Agent).filter_by(name=first_agent_name).first()
        if agent_record:
            assigned_agent_id = agent_record.id

    # 4. Create and persist Task in PENDING status
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
    db.add(task)
    db.commit()
    db.refresh(task)

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
