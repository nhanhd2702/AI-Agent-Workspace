"""FastAPI routers for Agent Registry & Department Management (F02).

Implements:
- Agent CRUD: GET/POST/PUT/DELETE /api/v1/agents
- Agent Skills: POST/DELETE /api/v1/agents/{id}/skills
- Agent Model Routing: PUT /api/v1/agents/{id}/model-config
- Department CRUD: GET/POST/PUT/DELETE /api/v1/departments
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Optional
import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Agent, AgentSkill, Department, Skill, SubTask, Task, TaskStatus
from app.db.session import get_db

agents_router = APIRouter(prefix="/api/v1/agents", tags=["agents"])
departments_router = APIRouter(prefix="/api/v1/departments", tags=["departments"])

# Export router alias for consistency
router = agents_router


# ============================================================================
# Pydantic Schemas
# ============================================================================

class AgentCreate(BaseModel):
    """Payload to register a new agent in the workspace."""

    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_]+$")
    display_name: str = Field(..., min_length=1, max_length=128, alias="displayName")
    description: Optional[str] = None
    role: str = Field(..., min_length=1, max_length=128)
    avatar: Optional[str] = None
    system_prompt: Optional[str] = Field(None, max_length=4000, alias="systemPrompt")
    department_id: Optional[str] = Field(None, alias="departmentId")
    default_model: Optional[str] = Field(None, alias="defaultModel")
    primary_model: Optional[str] = Field(None, alias="primaryModel")
    fallback_model: Optional[str] = Field(None, alias="fallbackModel")
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=4096, ge=1, le=128000, alias="maxTokens")
    status: Optional[str] = Field(default="idle")
    skill_ids: Optional[list[str]] = Field(default=None, alias="skillIds")


class AgentUpdate(BaseModel):
    """Payload to update an existing agent's configuration."""

    model_config = ConfigDict(populate_by_name=True)

    name: Optional[str] = Field(None, min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_]+$")
    display_name: Optional[str] = Field(None, min_length=1, max_length=128, alias="displayName")
    description: Optional[str] = None
    role: Optional[str] = Field(None, min_length=1, max_length=128)
    avatar: Optional[str] = None
    system_prompt: Optional[str] = Field(None, max_length=4000, alias="systemPrompt")
    department_id: Optional[str] = Field(None, alias="departmentId")
    default_model: Optional[str] = Field(None, alias="defaultModel")
    primary_model: Optional[str] = Field(None, alias="primaryModel")
    fallback_model: Optional[str] = Field(None, alias="fallbackModel")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(None, ge=1, le=128000, alias="maxTokens")
    status: Optional[str] = None


class AgentModelConfigUpdate(BaseModel):
    """Payload to update LLM routing and hyperparameters for an agent."""

    model_config = ConfigDict(populate_by_name=True)

    default_model: Optional[str] = Field(None, alias="defaultModel")
    primary_model: Optional[str] = Field(None, alias="primaryModel")
    fallback_model: Optional[str] = Field(None, alias="fallbackModel")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(None, ge=1, le=128000, alias="maxTokens")


class SkillAttachRequest(BaseModel):
    """Payload to attach a skill to an agent."""

    model_config = ConfigDict(populate_by_name=True)

    skill_id: Optional[str] = Field(None, alias="skillId")
    custom_params: Optional[dict[str, Any]] = Field(default=None, alias="customParams")


class SkillDetachRequest(BaseModel):
    """Payload to detach a skill from an agent."""

    model_config = ConfigDict(populate_by_name=True)

    skill_id: Optional[str] = Field(None, alias="skillId")


class DepartmentCreate(BaseModel):
    """Payload to create a new department."""

    model_config = ConfigDict(populate_by_name=True)

    id: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=128)
    description: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    status: Optional[str] = "active"


class DepartmentUpdate(BaseModel):
    """Payload to update an existing department."""

    model_config = ConfigDict(populate_by_name=True)

    name: Optional[str] = Field(None, min_length=1, max_length=128)
    description: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    status: Optional[str] = None


# ============================================================================
# Helper Serializers
# ============================================================================

def _format_utc_iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).isoformat()
    return dt.astimezone(timezone.utc).isoformat()


def _batch_agent_skill_ids(db: Session, agent_ids: list[str]) -> dict[str, list[str]]:
    if not agent_ids:
        return {}
    rows = (
        db.query(AgentSkill.agent_id, AgentSkill.skill_id)
        .filter(AgentSkill.agent_id.in_(agent_ids))
        .all()
    )
    grouped: dict[str, list[str]] = {aid: [] for aid in agent_ids}
    for aid, sid in rows:
        grouped.setdefault(aid, []).append(sid)
    return grouped


def _serialize_agent(
    agent: Agent,
    db: Session,
    skill_ids: Optional[list[str]] = None,
) -> dict[str, Any]:
    if skill_ids is None:
        skills = db.query(AgentSkill).filter_by(agent_id=agent.id).all()
        resolved_skill_ids = [s.skill_id for s in skills]
    else:
        resolved_skill_ids = skill_ids
    return {
        "id": agent.id,
        "name": agent.name,
        "display_name": agent.display_name,
        "description": agent.description,
        "role": agent.role,
        "avatar": agent.avatar,
        "system_prompt": agent.system_prompt,
        "department_id": agent.department_id,
        "default_model": agent.default_model,
        "primary_model": agent.default_model,
        "fallback_model": agent.fallback_model,
        "temperature": agent.temperature,
        "max_tokens": agent.max_tokens,
        "status": agent.status,
        "is_system": agent.is_system,
        "skills_count": len(resolved_skill_ids),
        "skill_ids": resolved_skill_ids,
        "created_at": _format_utc_iso(agent.created_at),
        "updated_at": _format_utc_iso(agent.updated_at),
    }


def _serialize_department(
    dept: Department,
    db: Session,
    dept_agents: Optional[list[Agent]] = None,
    skill_ids_by_agent: Optional[dict[str, list[str]]] = None,
) -> dict[str, Any]:
    resolved_agents = (
        dept_agents
        if dept_agents is not None
        else db.query(Agent).filter_by(department_id=dept.id).all()
    )
    resolved_skills_map = (
        skill_ids_by_agent
        if skill_ids_by_agent is not None
        else _batch_agent_skill_ids(db, [agent.id for agent in resolved_agents])
    )
    return {
        "id": dept.id,
        "name": dept.name,
        "description": dept.description,
        "icon": dept.icon,
        "color": dept.color,
        "status": dept.status,
        "agents_count": len(resolved_agents),
        "agents": [
            _serialize_agent(
                agent,
                db,
                skill_ids=resolved_skills_map.get(agent.id, []),
            )
            for agent in resolved_agents
        ],
        "created_at": _format_utc_iso(dept.created_at),
        "updated_at": _format_utc_iso(dept.updated_at),
    }


# ============================================================================
# Agent Endpoints
# ============================================================================

@agents_router.get("", status_code=status.HTTP_200_OK)
def list_agents(
    department_id: Optional[str] = Query(default=None),
    departmentId: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List all agents in the workspace with optional department or status filters."""
    resolved_dept_id = department_id or departmentId
    query = db.query(Agent)
    if resolved_dept_id:
        query = query.filter(Agent.department_id == resolved_dept_id)
    if status_filter:
        query = query.filter(Agent.status == status_filter)

    agents = query.all()
    skills_map = _batch_agent_skill_ids(db, [a.id for a in agents])
    return {
        "status": "success",
        "data": [
            _serialize_agent(agent, db, skill_ids=skills_map.get(agent.id, []))
            for agent in agents
        ],
    }


@agents_router.get("/{agent_id}", status_code=status.HTTP_200_OK)
def get_agent(
    agent_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve detailed agent profile and attached skills by ID."""
    agent = db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found",
        )
    return {
        "status": "success",
        "data": _serialize_agent(agent, db),
    }


@agents_router.post("", status_code=status.HTTP_201_CREATED)
def create_agent(
    payload: AgentCreate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Register a new Agent with unique name validation and optional skill attachment."""
    # 1. Enforce unique name (case-insensitive)
    existing_name = db.query(Agent).filter(func.lower(Agent.name) == payload.name.lower()).first()
    if existing_name:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Agent with name '{payload.name}' already exists",
        )

    # 2. Validate department existence if provided
    if payload.department_id:
        dept = db.get(Department, payload.department_id)
        if not dept:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Department '{payload.department_id}' not found",
            )

    # 3. Validate initial skill_ids if provided (deduplicated preserving order)
    unique_skill_ids: list[str] = []
    if payload.skill_ids:
        unique_skill_ids = list(dict.fromkeys(payload.skill_ids))
        if len(unique_skill_ids) > 20:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Agent cannot have more than 20 skills",
            )
        for skill_id in unique_skill_ids:
            if not db.get(Skill, skill_id):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Skill '{skill_id}' not found",
                )

    # 4. Generate unique ID
    raw_slug = re.sub(r"[^a-zA-Z0-9_-]", "", payload.name.lower())
    candidate_id = f"agent-{raw_slug}" if raw_slug else f"agent-{uuid.uuid4().hex[:8]}"
    if db.get(Agent, candidate_id):
        candidate_id = f"agent-{raw_slug}-{uuid.uuid4().hex[:6]}"

    model_choice = payload.primary_model or payload.default_model or "gemini-2.5-flash"

    agent = Agent(
        id=candidate_id,
        name=payload.name,
        display_name=payload.display_name,
        description=payload.description,
        role=payload.role,
        avatar=payload.avatar,
        system_prompt=payload.system_prompt,
        department_id=payload.department_id,
        default_model=model_choice,
        fallback_model=payload.fallback_model,
        temperature=payload.temperature if payload.temperature is not None else 0.7,
        max_tokens=payload.max_tokens if payload.max_tokens is not None else 4096,
        status=payload.status or "idle",
        is_system=False,
    )

    try:
        db.add(agent)
        db.flush()

        if unique_skill_ids:
            for skill_id in unique_skill_ids:
                askill = AgentSkill(
                    id=f"askill-{uuid.uuid4().hex[:12]}",
                    agent_id=agent.id,
                    skill_id=skill_id,
                    is_active=True,
                )
                db.add(askill)

        db.commit()
        db.refresh(agent)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Integrity conflict creating agent '{payload.name}'",
        ) from exc
    except Exception:
        db.rollback()
        raise

    return {
        "status": "success",
        "data": _serialize_agent(agent, db),
    }


@agents_router.put("/{agent_id}", status_code=status.HTTP_200_OK)
def update_agent(
    agent_id: str,
    payload: AgentUpdate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Update agent metadata, prompt, department, or status."""
    agent = db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found",
        )

    # Safety rule: Cannot rename system agent
    if agent.is_system and payload.name is not None and payload.name.lower() != agent.name.lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot rename system agent",
        )

    # Safety rule: Cannot deactivate system agent
    if agent.is_system and payload.status is not None and payload.status.lower() in ["inactive", "disabled"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate system agent",
        )

    # Validate name uniqueness if changed (case-insensitive)
    if payload.name and payload.name.lower() != agent.name.lower():
        existing = db.query(Agent).filter(func.lower(Agent.name) == payload.name.lower()).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Agent with name '{payload.name}' already exists",
            )
        agent.name = payload.name

    # Validate department if changed
    if payload.department_id is not None:
        if payload.department_id != "":
            dept = db.get(Department, payload.department_id)
            if not dept:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Department '{payload.department_id}' not found",
                )
            agent.department_id = payload.department_id
        else:
            agent.department_id = None

    if payload.display_name is not None:
        agent.display_name = payload.display_name
    if payload.description is not None:
        agent.description = payload.description
    if payload.role is not None:
        agent.role = payload.role
    if payload.avatar is not None:
        agent.avatar = payload.avatar
    if payload.system_prompt is not None:
        agent.system_prompt = payload.system_prompt
    if payload.primary_model or payload.default_model:
        agent.default_model = payload.primary_model or payload.default_model
    if payload.fallback_model is not None:
        agent.fallback_model = payload.fallback_model
    if payload.temperature is not None:
        agent.temperature = payload.temperature
    if payload.max_tokens is not None:
        agent.max_tokens = payload.max_tokens
    if payload.status is not None:
        agent.status = payload.status

    try:
        db.commit()
        db.refresh(agent)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflict updating agent record",
        ) from exc
    except Exception:
        db.rollback()
        raise

    return {
        "status": "success",
        "data": _serialize_agent(agent, db),
    }


@agents_router.delete("/{agent_id}", status_code=status.HTTP_200_OK)
def delete_agent(
    agent_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Delete an agent from workspace with system agent and active task safety guards."""
    agent = db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found",
        )

    # Rule 1: Cannot delete system agent
    if agent.is_system:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete system agent",
        )

    # Rule 2: Cannot delete agent with active running or waiting_review tasks or subtasks
    busy_tasks = (
        db.query(Task.id)
        .filter(
            Task.assigned_agent_id == agent_id,
            Task.status.in_([TaskStatus.RUNNING, TaskStatus.WAITING_REVIEW]),
        )
        .all()
    )
    busy_subtasks = (
        db.query(SubTask.id)
        .filter(
            SubTask.agent_id == agent_id,
            SubTask.status.in_(["running", "waiting_review"]),
        )
        .all()
    )

    if busy_tasks or busy_subtasks:
        busy_ids = [t[0] for t in busy_tasks] + [st[0] for st in busy_subtasks]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete agent with active tasks: {busy_ids}",
        )

    try:
        db.delete(agent)
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "status": "success",
        "data": {
            "deleted": True,
            "agent_id": agent_id,
        },
    }


# ============================================================================
# Agent Model Configuration Endpoint
# ============================================================================

@agents_router.put("/{agent_id}/model-config", status_code=status.HTTP_200_OK)
def update_agent_model_config(
    agent_id: str,
    payload: AgentModelConfigUpdate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Update primary/fallback LLM models and temperature/token hyperparameters."""
    agent = db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found",
        )

    if payload.primary_model or payload.default_model:
        agent.default_model = payload.primary_model or payload.default_model
    if payload.fallback_model is not None:
        agent.fallback_model = payload.fallback_model
    if payload.temperature is not None:
        agent.temperature = payload.temperature
    if payload.max_tokens is not None:
        agent.max_tokens = payload.max_tokens

    try:
        db.commit()
        db.refresh(agent)
    except Exception:
        db.rollback()
        raise

    return {
        "status": "success",
        "data": _serialize_agent(agent, db),
    }


# ============================================================================
# Agent Skills Endpoints (Attach & Detach)
# ============================================================================

@agents_router.post("/{agent_id}/skills", status_code=status.HTTP_200_OK)
def attach_skill_to_agent(
    agent_id: str,
    payload: Optional[SkillAttachRequest] = Body(default=None),
    skill_id: Optional[str] = Query(default=None),
    skillId: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Attach a skill to an agent idempotently with 0..20 skills limit enforcement."""
    resolved_skill_id = (payload.skill_id if payload else None) or skill_id or skillId
    if not resolved_skill_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="skill_id is required in JSON body or query parameter",
        )

    # 1. Validate agent
    agent = db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found",
        )

    # 2. Validate skill
    skill = db.get(Skill, resolved_skill_id)
    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill '{resolved_skill_id}' not found",
        )

    # 3. Check if already attached (Idempotent 200 OK)
    existing_link = (
        db.query(AgentSkill)
        .filter_by(agent_id=agent_id, skill_id=resolved_skill_id)
        .first()
    )
    if existing_link:
        return {
            "status": "success",
            "data": {
                "agent_id": agent_id,
                "skill_id": resolved_skill_id,
                "attached": True,
                "already_attached": True,
            },
        }

    # 4. Check 0..20 skills limit
    current_skill_count = db.query(AgentSkill).filter_by(agent_id=agent_id).count()
    if current_skill_count >= 20:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Agent cannot have more than 20 skills (currently has {current_skill_count})",
        )

    # 5. Create AgentSkill binding
    link_id = f"askill-{uuid.uuid4().hex[:12]}"
    custom_params = payload.custom_params if payload else None
    agent_skill = AgentSkill(
        id=link_id,
        agent_id=agent_id,
        skill_id=resolved_skill_id,
        custom_params=custom_params,
        is_active=True,
    )

    try:
        db.add(agent_skill)
        db.commit()
    except IntegrityError:
        db.rollback()
        # Race-condition idempotency fallback
        return {
            "status": "success",
            "data": {
                "agent_id": agent_id,
                "skill_id": resolved_skill_id,
                "attached": True,
                "already_attached": True,
            },
        }
    except Exception:
        db.rollback()
        raise

    return {
        "status": "success",
        "data": {
            "agent_id": agent_id,
            "skill_id": resolved_skill_id,
            "attached": True,
        },
    }


def _detach_agent_skill(agent_id: str, skill_id: str, db: Session) -> dict[str, Any]:
    """Helper to remove skill attachment safely."""
    agent = db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found",
        )

    link = (
        db.query(AgentSkill)
        .filter_by(agent_id=agent_id, skill_id=skill_id)
        .first()
    )
    if link:
        try:
            db.delete(link)
            db.commit()
        except Exception:
            db.rollback()
            raise

    return {
        "status": "success",
        "data": {
            "agent_id": agent_id,
            "skill_id": skill_id,
            "detached": True,
        },
    }


@agents_router.delete("/{agent_id}/skills/{skill_id}", status_code=status.HTTP_200_OK)
def detach_skill_from_agent_path(
    agent_id: str,
    skill_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Detach skill using URL path parameter."""
    return _detach_agent_skill(agent_id=agent_id, skill_id=skill_id, db=db)


@agents_router.delete("/{agent_id}/skills", status_code=status.HTTP_200_OK)
def detach_skill_from_agent_body_or_query(
    agent_id: str,
    payload: Optional[SkillDetachRequest] = Body(default=None),
    skill_id: Optional[str] = Query(default=None),
    skillId: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Detach skill using query parameter or JSON request body for full brief compatibility."""
    resolved_skill_id = (payload.skill_id if payload else None) or skill_id or skillId
    if not resolved_skill_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="skill_id is required in JSON body or query parameter",
        )
    return _detach_agent_skill(agent_id=agent_id, skill_id=resolved_skill_id, db=db)


# ============================================================================
# Department Endpoints
# ============================================================================

@departments_router.get("", status_code=status.HTTP_200_OK)
def list_departments(
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List all functional departments and current member counts."""
    departments = db.query(Department).all()
    dept_ids = [d.id for d in departments]
    all_agents = (
        db.query(Agent).filter(Agent.department_id.in_(dept_ids)).all()
        if dept_ids
        else []
    )
    agents_by_dept: dict[str, list[Agent]] = {did: [] for did in dept_ids}
    for agent in all_agents:
        if agent.department_id:
            agents_by_dept.setdefault(agent.department_id, []).append(agent)

    skills_by_agent = _batch_agent_skill_ids(db, [a.id for a in all_agents])

    return {
        "status": "success",
        "data": [
            _serialize_department(
                dept,
                db,
                dept_agents=agents_by_dept.get(dept.id, []),
                skill_ids_by_agent=skills_by_agent,
            )
            for dept in departments
        ],
    }


@departments_router.get("/{department_id}", status_code=status.HTTP_200_OK)
def get_department(
    department_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve department details by ID."""
    dept = db.get(Department, department_id)
    if not dept:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Department '{department_id}' not found",
        )
    return {
        "status": "success",
        "data": _serialize_department(dept, db),
    }


@departments_router.post("", status_code=status.HTTP_201_CREATED)
def create_department(
    payload: DepartmentCreate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Create a new department with unique name check."""
    # Case-insensitive duplicate department check (Unicode-aware)
    existing_depts = db.query(Department).all()
    if any(d.name.strip().lower() == payload.name.strip().lower() for d in existing_depts):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Department with name '{payload.name}' already exists",
        )

    dept_id = payload.id or f"dept-{uuid.uuid4().hex[:8]}"
    department = Department(
        id=dept_id,
        name=payload.name,
        description=payload.description,
        icon=payload.icon,
        color=payload.color,
        status=payload.status or "active",
    )

    try:
        db.add(department)
        db.commit()
        db.refresh(department)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Conflict creating department '{payload.name}'",
        ) from exc
    except Exception:
        db.rollback()
        raise

    return {
        "status": "success",
        "data": _serialize_department(department, db),
    }


@departments_router.put("/{department_id}", status_code=status.HTTP_200_OK)
def update_department(
    department_id: str,
    payload: DepartmentUpdate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Update department properties."""
    dept = db.get(Department, department_id)
    if not dept:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Department '{department_id}' not found",
        )

    if payload.name and payload.name.strip().lower() != dept.name.strip().lower():
        existing_depts = db.query(Department).filter(Department.id != department_id).all()
        if any(d.name.strip().lower() == payload.name.strip().lower() for d in existing_depts):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Department with name '{payload.name}' already exists",
            )
        dept.name = payload.name

    if payload.description is not None:
        dept.description = payload.description
    if payload.icon is not None:
        dept.icon = payload.icon
    if payload.color is not None:
        dept.color = payload.color
    if payload.status is not None:
        dept.status = payload.status

    try:
        db.commit()
        db.refresh(dept)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflict updating department",
        ) from exc
    except Exception:
        db.rollback()
        raise

    return {
        "status": "success",
        "data": _serialize_department(dept, db),
    }


@departments_router.delete("/{department_id}", status_code=status.HTTP_200_OK)
def delete_department(
    department_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Delete a department, blocked with HTTP 400 if it still contains agents."""
    dept = db.get(Department, department_id)
    if not dept:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Department '{department_id}' not found",
        )

    # Safety rule: block deletion if department still contains agents
    agent_count = db.query(Agent).filter_by(department_id=department_id).count()
    if agent_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete department containing {agent_count} agent(s). Reassign agents first.",
        )

    try:
        db.delete(dept)
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "status": "success",
        "data": {
            "deleted": True,
            "department_id": department_id,
        },
    }
