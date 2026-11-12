"""FastAPI router for Artifact serving and rendering (F06.1, F06.2, API 7).

Endpoints:
- GET /api/v1/artifacts/{artifact_id}/render
  Serves self-contained offline HTML or raw content for sandboxed viewing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.artifacts.renderer import sanitize_offline_html
from app.config import AppSettings, get_settings
from app.db.models import Artifact
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/artifacts", tags=["artifacts"])


@router.get("/{artifact_id}/render")
def render_artifact(
    artifact_id: str,
    request: Request,
    format: Optional[str] = Query(None, description="Output format: 'raw' for raw content/HTML, or default JSON envelope"),
    db: Session = Depends(get_db),
) -> Response:
    """Serve an artifact with strict offline HTML sanitization or raw text.
    
    Protected by local auth token middleware.
    Safeguards against directory traversal attacks outside the workspace directory.
    """
    settings: AppSettings = getattr(request.app.state, "settings", None) or get_settings()

    artifact = db.query(Artifact).filter(Artifact.id == artifact_id).first()
    if not artifact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artifact '{artifact_id}' not found",
        )

    # 1. Resolve content from inline metadata or local filesystem
    content: str = ""
    metadata = artifact.artifact_metadata or {}
    if isinstance(metadata, dict) and ("content_inline" in metadata or "content" in metadata):
        content = str(metadata.get("content_inline") or metadata.get("content") or "")
    elif artifact.file_path:
        file_path_obj = Path(artifact.file_path)
        workspace_resolved = settings.workspace_dir.resolve()

        if file_path_obj.is_absolute():
            resolved_path = file_path_obj.resolve()
        else:
            resolved_path = (settings.workspace_dir / file_path_obj).resolve()

        # Path traversal guard: ensure resolved_path is inside workspace_dir
        if not resolved_path.is_relative_to(workspace_resolved):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: artifact path is outside workspace directory",
            )

        if not resolved_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Artifact file not found on disk: {artifact.file_path}",
            )

        try:
            content = resolved_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Unsupported media type: artifact contains non-UTF-8 binary content",
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to read artifact content from disk: {str(exc)}",
            )

    # 2. Determine if artifact is HTML format or SVG/XML active format
    is_html = (
        (artifact.file_type and artifact.file_type.lower() in ["html", "htm"])
        or (artifact.mime_type and "html" in artifact.mime_type.lower())
        or (artifact.name and artifact.name.lower().endswith((".html", ".htm")))
    )

    is_svg_or_xml = (
        (artifact.file_type and artifact.file_type.lower() in ["svg", "xml"])
        or (
            artifact.mime_type
            and any(t in artifact.mime_type.lower() for t in ["image/svg+xml", "application/xml", "text/xml"])
        )
        or (artifact.name and artifact.name.lower().endswith((".svg", ".xml")))
    )

    sanitized_html: Optional[str] = None
    warnings: list[str] = []

    if is_html:
        sanitized_html, warnings = sanitize_offline_html(content)

    # 3. Handle raw format query (?format=raw) with hardened headers
    if format == "raw":
        if is_html and sanitized_html is not None:
            return HTMLResponse(
                content=sanitized_html,
                media_type="text/html; charset=utf-8",
                headers={
                    "Content-Security-Policy": (
                        "sandbox allow-scripts allow-forms; "
                        "default-src 'none'; "
                        "style-src 'unsafe-inline'; "
                        "script-src 'unsafe-inline'; "
                        "img-src data: blob:;"
                    ),
                    "X-Content-Type-Options": "nosniff",
                },
            )

        if is_svg_or_xml:
            media_type = artifact.mime_type or "image/svg+xml"
            safe_name = artifact.name or "artifact.svg"
            return Response(
                content=content,
                media_type=media_type,
                headers={
                    "Content-Security-Policy": "sandbox;",
                    "Content-Disposition": f'attachment; filename="{safe_name}"',
                    "X-Content-Type-Options": "nosniff",
                },
            )

        media_type = artifact.mime_type or "text/plain; charset=utf-8"
        return Response(
            content=content,
            media_type=media_type,
            headers={
                "X-Content-Type-Options": "nosniff",
            },
        )

    # 4. Return standard JSON envelope
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "success",
            "data": {
                "id": artifact.id,
                "task_id": artifact.task_id,
                "subtask_id": artifact.subtask_id,
                "created_by_agent_id": artifact.created_by_agent_id,
                "name": artifact.name,
                "title": artifact.name,
                "file_path": artifact.file_path,
                "file_type": artifact.file_type,
                "mime_type": artifact.mime_type,
                "artifact_type": artifact.file_type,
                "size_bytes": artifact.size_bytes,
                "category": artifact.category,
                "content": content,
                "sanitized_html": sanitized_html,
                "warnings": warnings,
                "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
                "updated_at": artifact.updated_at.isoformat() if artifact.updated_at else None,
            },
        },
    )
