"""Project CRUD & Task Summary API endpoints (Task 2.6 / F01 / F06)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import AppSettings, get_settings
from app.db.models import Department, Project, Task, TaskStatus
from app.db.session import get_db
from app.orchestrator.dispatcher import mask_secrets

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    """Payload to create a workspace project."""

    model_config = ConfigDict(populate_by_name=True)

    id: Optional[str] = Field(default=None, min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    default_department_id: Optional[str] = Field(default=None, alias="defaultDepartmentId")


class ProjectUpdate(BaseModel):
    """Payload to update an existing workspace project."""

    model_config = ConfigDict(populate_by_name=True)

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    default_department_id: Optional[str] = Field(default=None, alias="defaultDepartmentId")


def _get_extra_secrets(request: Request) -> list[str]:
    settings: AppSettings = getattr(request.app.state, "settings", None) or get_settings()
    return [settings.local_auth_token] if settings.local_auth_token else []


def _format_utc_iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).isoformat()
    return dt.astimezone(timezone.utc).isoformat()


def _projects_task_summaries(
    db: Session,
    project_ids: list[str],
) -> dict[str, tuple[int, dict[str, int]]]:
    if not project_ids:
        return {}
    rows = (
        db.query(Task.project_id, Task.status, func.count(Task.id))
        .filter(Task.project_id.in_(project_ids))
        .group_by(Task.project_id, Task.status)
        .all()
    )
    totals: dict[str, int] = {pid: 0 for pid in project_ids}
    summaries: dict[str, dict[str, int]] = {pid: {} for pid in project_ids}
    for pid, st, count in rows:
        key = st.value if isinstance(st, TaskStatus) else str(st)
        cnt = int(count)
        summaries[pid][key] = cnt
        totals[pid] += cnt
    return {pid: (totals[pid], summaries[pid]) for pid in project_ids}


def _project_task_summary(db: Session, project_id: str) -> tuple[int, dict[str, int]]:
    return _projects_task_summaries(db, [project_id]).get(project_id, (0, {}))


def _serialize_project(
    project: Project,
    db: Session,
    extra_secrets: Optional[list[str]] = None,
    summary: Optional[tuple[int, dict[str, int]]] = None,
) -> dict[str, Any]:
    task_count, status_summary = (
        summary if summary is not None else _project_task_summary(db, project.id)
    )
    return mask_secrets(
        {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "tags": list(project.tags or []),
            "default_department_id": project.default_department_id,
            "task_count": task_count,
            "status_summary": status_summary,
            "created_at": _format_utc_iso(project.created_at),
            "updated_at": _format_utc_iso(project.updated_at),
        },
        extra_secrets=extra_secrets,
    )


@router.get("", status_code=status.HTTP_200_OK)
def list_projects(
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List all workspace projects with task status summaries."""
    projects = db.query(Project).order_by(Project.created_at.asc()).all()
    summaries = _projects_task_summaries(db, [p.id for p in projects])
    extra_secrets = _get_extra_secrets(request)
    return {
        "status": "success",
        "data": [
            _serialize_project(
                p,
                db,
                extra_secrets=extra_secrets,
                summary=summaries.get(p.id, (0, {})),
            )
            for p in projects
        ],
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Create a new workspace project."""
    clean_name = payload.name.strip()
    if not clean_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Project name cannot be blank",
        )

    if payload.id is not None:
        stripped_id = payload.id.strip()
        if not stripped_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Project id cannot be blank",
            )
        project_id = stripped_id
    else:
        project_id = f"proj-{uuid.uuid4().hex[:10]}"

    if db.get(Project, project_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Project '{project_id}' already exists",
        )

    clean_dept_id = (
        payload.default_department_id.strip() or None
        if payload.default_department_id is not None
        else None
    )
    if clean_dept_id:
        dept = db.get(Department, clean_dept_id)
        if not dept:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Department '{clean_dept_id}' not found",
            )

    extra_secrets = _get_extra_secrets(request)
    masked_desc = (
        mask_secrets(payload.description, extra_secrets=extra_secrets)
        if payload.description is not None
        else None
    )
    masked_tags = (
        mask_secrets(payload.tags, extra_secrets=extra_secrets)
        if payload.tags is not None
        else None
    )

    now = datetime.now(timezone.utc)
    project = Project(
        id=project_id,
        name=str(mask_secrets(clean_name, extra_secrets=extra_secrets)),
        description=masked_desc,
        tags=masked_tags,
        default_department_id=clean_dept_id,
        created_at=now,
        updated_at=now,
    )

    try:
        db.add(project)
        db.commit()
        db.refresh(project)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Conflict creating project '{project_id}'",
        ) from exc
    except Exception:
        db.rollback()
        raise

    return {
        "status": "success",
        "data": _serialize_project(
            project, db, extra_secrets=extra_secrets, summary=(0, {})
        ),
    }


@router.get("/{project_id}", status_code=status.HTTP_200_OK)
def get_project(
    project_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve project details and task summary by ID."""
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found",
        )
    extra_secrets = _get_extra_secrets(request)
    return {
        "status": "success",
        "data": _serialize_project(project, db, extra_secrets=extra_secrets),
    }


@router.put("/{project_id}", status_code=status.HTTP_200_OK)
def update_project(
    project_id: str,
    payload: ProjectUpdate,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Update an existing project's metadata."""
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found",
        )

    extra_secrets = _get_extra_secrets(request)

    if payload.name is not None:
        clean_name = payload.name.strip()
        if not clean_name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Project name cannot be blank",
            )
        project.name = str(mask_secrets(clean_name, extra_secrets=extra_secrets))

    if payload.description is not None:
        project.description = mask_secrets(
            payload.description, extra_secrets=extra_secrets
        )

    if payload.tags is not None:
        project.tags = mask_secrets(payload.tags, extra_secrets=extra_secrets)

    if payload.default_department_id is not None:
        clean_dept_id = payload.default_department_id.strip()
        if clean_dept_id:
            dept = db.get(Department, clean_dept_id)
            if not dept:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Department '{clean_dept_id}' not found",
                )
            project.default_department_id = clean_dept_id
        else:
            project.default_department_id = None

    project.updated_at = datetime.now(timezone.utc)
    try:
        db.commit()
        db.refresh(project)
    except Exception:
        db.rollback()
        raise

    return {
        "status": "success",
        "data": _serialize_project(project, db, extra_secrets=extra_secrets),
    }


@router.delete("/{project_id}", status_code=status.HTTP_200_OK)
def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Delete a non-default project."""
    if project_id == "proj-default":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete the default workspace project",
        )
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found",
        )

    referencing_task = db.query(Task.id).filter(Task.project_id == project_id).first()
    if referencing_task:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete project '{project_id}' while tasks still reference it",
        )

    try:
        db.delete(project)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete project '{project_id}' due to existing references",
        ) from exc
    except Exception:
        db.rollback()
        raise

    return {
        "status": "success",
        "data": {"deleted": True, "project_id": project_id},
    }
