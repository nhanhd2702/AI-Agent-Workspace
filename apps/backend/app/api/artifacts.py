"""FastAPI router for Artifact serving, HTTP 206 Range streaming, and Storyboard editing (Task 3.6).

Endpoints:
- GET /api/v1/artifacts/{artifact_id}/render:
  Serves self-contained offline HTML or raw content for sandboxed viewing.
- GET /api/v1/artifacts/{artifact_id}/stream:
  HTTP 206 Partial Content Range streaming for media files up to 500MB.
- GET /api/v1/files/{target_id}/stream:
  HTTP 206 Partial Content Range streaming by file path or artifact ID.
- GET /api/v1/artifacts/{artifact_id}/storyboard:
  Returns parsed storyboard JSON representation.
- PATCH /api/v1/artifacts/{artifact_id}/storyboard/scenes/{scene_id}:
  Updates scene overlay text, effect, or deletes a scene with live duration & pacing recalculation.
"""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.artifacts.renderer import sanitize_offline_html
from app.artifacts.storyboard import Scene, Storyboard, StoryboardBuilder
from app.config import AppSettings, get_settings
from app.db.models import Artifact
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/artifacts", tags=["artifacts"])
files_router = APIRouter(prefix="/api/v1/files", tags=["files"])


@router.get("", status_code=status.HTTP_200_OK)
def list_artifacts(
    task_id: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List artifacts with optional filtering by task_id and category."""
    query = db.query(Artifact)
    if task_id:
        query = query.filter(Artifact.task_id == task_id)
    if category:
        query = query.filter(Artifact.category == category)
    artifacts = query.order_by(Artifact.created_at.desc()).offset(offset).limit(limit).all()

    return {
        "status": "success",
        "data": [
            {
                "id": a.id,
                "task_id": a.task_id,
                "subtask_id": a.subtask_id,
                "created_by_agent_id": a.created_by_agent_id,
                "name": a.name,
                "title": a.name,
                "file_path": a.file_path,
                "file_type": a.file_type,
                "mime_type": a.mime_type,
                "artifact_type": a.file_type,
                "size_bytes": a.size_bytes,
                "category": a.category,
                "metadata": a.artifact_metadata or {},
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "updated_at": a.updated_at.isoformat() if a.updated_at else None,
            }
            for a in artifacts
        ],
    }

MEDIA_MIME_TYPES: dict[str, str] = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".webm": "video/webm",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".ogv": "video/ogg",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".json": "application/json",
}


def _resolve_media_file(target_id: str, settings: AppSettings, db: Session) -> tuple[Path, str]:
    """Resolve file path and mime type for an artifact ID or workspace relative file path."""
    workspace_resolved = settings.workspace_dir.resolve()

    # 1. Check if target_id matches an Artifact ID in DB
    artifact = db.query(Artifact).filter(Artifact.id == target_id).first()
    if artifact and artifact.file_path:
        file_path_obj = Path(artifact.file_path)
        if file_path_obj.is_absolute():
            resolved = file_path_obj.resolve()
        else:
            resolved = (settings.workspace_dir / file_path_obj).resolve()

        if not resolved.is_relative_to(workspace_resolved):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: artifact path is outside workspace directory",
            )
        if not resolved.is_file():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Artifact file not found on disk: {artifact.file_path}",
            )
        mime = (
            artifact.mime_type
            or MEDIA_MIME_TYPES.get(resolved.suffix.lower())
            or mimetypes.guess_type(str(resolved))[0]
            or "application/octet-stream"
        )
        return resolved, mime

    # 2. Check if target_id is a direct file path relative to workspace_dir
    file_path_obj = Path(target_id)
    if file_path_obj.is_absolute():
        resolved = file_path_obj.resolve()
    else:
        resolved = (settings.workspace_dir / file_path_obj).resolve()

    if not resolved.is_relative_to(workspace_resolved):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: path is outside workspace directory",
        )
    if not resolved.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found: '{target_id}'",
        )

    mime = (
        MEDIA_MIME_TYPES.get(resolved.suffix.lower())
        or mimetypes.guess_type(str(resolved))[0]
        or "application/octet-stream"
    )
    return resolved, mime


def _handle_range_streaming(resolved_path: Path, media_type: str, request: Request) -> Response:
    """Stream media file using HTTP 206 Partial Content or 200 OK chunked streaming.
    
    Reads in 64KB chunks to ensure memory consumption remains minimal even for 500MB files.
    """
    file_size = resolved_path.stat().st_size
    range_header = request.headers.get("range") or request.headers.get("Range")

    chunk_size = 65536  # 64 KB

    if not range_header:
        # Full content streaming (200 OK)
        def file_iterator():
            with open(resolved_path, "rb") as f:
                while chunk := f.read(chunk_size):
                    yield chunk

        return StreamingResponse(
            file_iterator(),
            status_code=status.HTTP_200_OK,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
                "Content-Type": media_type,
            },
            media_type=media_type,
        )

    # Range request parsing (RFC 7233)
    range_str = range_header.strip()
    if not range_str.startswith("bytes="):
        return Response(
            status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    range_spec = range_str[6:].strip()
    if "," in range_spec:
        range_spec = range_spec.split(",")[0].strip()

    try:
        parts = range_spec.split("-")
        if len(parts) != 2:
            return Response(
                status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
                headers={"Content-Range": f"bytes */{file_size}"},
            )
        start_str, end_str = parts[0].strip(), parts[1].strip()

        if not start_str and not end_str:
            return Response(
                status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
                headers={"Content-Range": f"bytes */{file_size}"},
            )

        if not start_str:
            # Suffix range: -suffix
            suffix_len = int(end_str)
            if suffix_len <= 0:
                return Response(
                    status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
                    headers={"Content-Range": f"bytes */{file_size}"},
                )
            start = max(0, file_size - suffix_len)
            end = file_size - 1
        elif not end_str:
            # Open-ended: start-
            start = int(start_str)
            end = file_size - 1
        else:
            # Explicit start-end
            start = int(start_str)
            end = int(end_str)

        if start < 0 or start >= file_size or end < start:
            return Response(
                status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
                headers={"Content-Range": f"bytes */{file_size}"},
            )

        end = min(end, file_size - 1)
        content_length = end - start + 1

    except ValueError:
        return Response(
            status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    def range_iterator():
        with open(resolved_path, "rb") as f:
            f.seek(start)
            remaining = content_length
            while remaining > 0:
                read_bytes = min(chunk_size, remaining)
                data = f.read(read_bytes)
                if not data:
                    break
                remaining -= len(data)
                yield data

    return StreamingResponse(
        range_iterator(),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(content_length),
            "Content-Type": media_type,
        },
        media_type=media_type,
    )


# --- 1. Streaming Endpoints ---


@router.get("/{artifact_id}/stream")
def stream_artifact(
    artifact_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """HTTP 206 Range streaming for media artifacts."""
    settings: AppSettings = getattr(request.app.state, "settings", None) or get_settings()
    resolved_path, media_type = _resolve_media_file(artifact_id, settings, db)
    return _handle_range_streaming(resolved_path, media_type, request)


@files_router.get("/{target_id:path}/stream")
def stream_file_with_path(
    target_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """HTTP 206 Range streaming for workspace files or artifact IDs by path."""
    settings: AppSettings = getattr(request.app.state, "settings", None) or get_settings()
    resolved_path, media_type = _resolve_media_file(target_id, settings, db)
    return _handle_range_streaming(resolved_path, media_type, request)


# --- 2. Render Endpoint ---


@router.get("/{artifact_id}/render")
def render_artifact(
    artifact_id: str,
    request: Request,
    format: Optional[str] = Query(None, description="Output format: 'raw' for raw content/HTML, or default JSON envelope"),
    db: Session = Depends(get_db),
) -> Response:
    """Serve an artifact with strict offline HTML sanitization or raw text."""
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


# --- 3. Storyboard Endpoints ---


def _extract_storyboard_data(artifact: Artifact, settings: AppSettings) -> dict[str, Any]:
    """Extract raw storyboard dictionary from artifact metadata or on-disk JSON/MD."""
    metadata = artifact.artifact_metadata or {}
    if isinstance(metadata, dict):
        if "storyboard" in metadata and isinstance(metadata["storyboard"], dict):
            return metadata["storyboard"]
        if "scenes" in metadata and isinstance(metadata["scenes"], list):
            return metadata

    # Check file on disk
    if artifact.file_path:
        workspace_resolved = settings.workspace_dir.resolve()
        file_path_obj = Path(artifact.file_path)
        resolved = (
            file_path_obj.resolve()
            if file_path_obj.is_absolute()
            else (settings.workspace_dir / file_path_obj).resolve()
        )
        if resolved.is_relative_to(workspace_resolved) and resolved.is_file():
            if resolved.suffix.lower() == ".json":
                try:
                    return json.loads(resolved.read_text(encoding="utf-8"))
                except Exception:
                    pass
            elif resolved.suffix.lower() == ".md":
                sibling_json = resolved.parent / "storyboard.json"
                if sibling_json.is_file():
                    try:
                        return json.loads(sibling_json.read_text(encoding="utf-8"))
                    except Exception:
                        pass

    return {
        "style_name": "Rainmaker Style",
        "styleName": "Rainmaker Style",
        "total_duration": 0.0,
        "totalDuration": 0.0,
        "warnings": [],
        "pacing_warnings": [],
        "scenes": [],
    }


def _normalize_storyboard_dict(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize storyboard dictionary with both camelCase and snake_case attributes."""
    raw_scenes = raw.get("scenes", [])
    scenes: list[dict[str, Any]] = []
    for idx, s in enumerate(raw_scenes):
        sid = str(s.get("scene_id") or s.get("sceneId") or s.get("id") or f"s{idx + 1}")
        start = float(s.get("start", s.get("startSec", 0.0)))
        dur = float(s.get("duration", s.get("durationSec", 3.0)))
        end = float(s.get("end", s.get("endSec", start + dur)))
        overlay = str(s.get("overlay_text", s.get("overlayText", s.get("text", ""))))
        effect = str(s.get("effect", "none"))
        visual_notes = str(s.get("visual_notes", s.get("visualNotes", "")))
        transition = str(s.get("transition", "cut"))

        scenes.append({
            "sceneId": sid,
            "scene_id": sid,
            "start": round(start, 3),
            "end": round(end, 3),
            "startSec": round(start, 3),
            "endSec": round(end, 3),
            "duration": round(dur, 3),
            "durationSec": round(dur, 3),
            "overlayText": overlay,
            "overlay_text": overlay,
            "effect": effect,
            "visualNotes": visual_notes,
            "visual_notes": visual_notes,
            "transition": transition,
        })

    calc_total = float(
        raw.get(
            "total_duration",
            raw.get("totalDuration", sum(s["durationSec"] for s in scenes)),
        )
    )
    warnings = raw.get("warnings", raw.get("pacing_warnings", []))

    return {
        "styleName": raw.get("styleName", raw.get("style_name", "Rainmaker Style")),
        "style_name": raw.get("style_name", raw.get("styleName", "Rainmaker Style")),
        "totalDuration": round(calc_total, 3),
        "total_duration": round(calc_total, 3),
        "sceneCount": len(scenes),
        "scene_count": len(scenes),
        "warnings": list(warnings),
        "pacing_warnings": list(warnings),
        "scenes": scenes,
    }


@router.get("/{artifact_id}/storyboard")
def get_artifact_storyboard(
    artifact_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """Retrieve structured storyboard representation for an artifact."""
    settings: AppSettings = getattr(request.app.state, "settings", None) or get_settings()

    artifact = db.query(Artifact).filter(Artifact.id == artifact_id).first()
    if not artifact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artifact '{artifact_id}' not found",
        )

    sb_raw = _extract_storyboard_data(artifact, settings)
    normalized = _normalize_storyboard_dict(sb_raw)

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "success", "data": normalized},
    )


@router.patch("/{artifact_id}/storyboard/scenes/{scene_id}")
def update_artifact_storyboard_scene(
    artifact_id: str,
    scene_id: str,
    payload: dict[str, Any],
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """Update scene overlay text/effect or delete scene with live duration & pacing recalculation."""
    settings: AppSettings = getattr(request.app.state, "settings", None) or get_settings()

    artifact = db.query(Artifact).filter(Artifact.id == artifact_id).first()
    if not artifact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artifact '{artifact_id}' not found",
        )

    sb_raw = _extract_storyboard_data(artifact, settings)
    scenes_list = list(sb_raw.get("scenes", []))

    # Locate scene
    target_idx = -1
    for i, s in enumerate(scenes_list):
        if str(s.get("scene_id") or s.get("sceneId") or s.get("id")) == str(scene_id):
            target_idx = i
            break

    if target_idx == -1:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scene '{scene_id}' not found in storyboard",
        )

    action = payload.get("action")
    is_deleted = payload.get("deleted") is True or action == "delete"

    if is_deleted:
        scenes_list.pop(target_idx)
    else:
        target_scene = dict(scenes_list[target_idx])
        if "overlayText" in payload or "overlay_text" in payload:
            val = str(payload.get("overlayText") if "overlayText" in payload else payload.get("overlay_text", ""))
            target_scene["overlayText"] = val
            target_scene["overlay_text"] = val
        if "effect" in payload:
            target_scene["effect"] = str(payload["effect"])
        if "visualNotes" in payload or "visual_notes" in payload:
            notes = str(payload.get("visualNotes") if "visualNotes" in payload else payload.get("visual_notes", ""))
            target_scene["visualNotes"] = notes
            target_scene["visual_notes"] = notes
        if "duration" in payload or "durationSec" in payload:
            dur = float(payload.get("durationSec") or payload.get("duration", 3.0))
            target_scene["duration"] = dur
            target_scene["durationSec"] = dur
            if "start" in target_scene:
                target_scene["end"] = float(target_scene["start"]) + dur

        scenes_list[target_idx] = target_scene

    # Convert to domain Scene objects to re-lint pacing and recalculate duration
    domain_scenes: list[Scene] = []
    current_time = 0.0
    for s in scenes_list:
        s_dur = float(s.get("durationSec") or s.get("duration", 3.0))
        s_start = float(s.get("start", current_time))
        s_end = float(s.get("end", s_start + s_dur))
        domain_scenes.append(
            Scene(
                scene_id=str(s.get("scene_id") or s.get("sceneId") or s.get("id")),
                start=s_start,
                end=s_end,
                effect=str(s.get("effect", "none")),
                overlay_text=str(s.get("overlay_text") or s.get("overlayText") or ""),
                visual_notes=str(s.get("visual_notes") or s.get("visualNotes") or ""),
                transition=str(s.get("transition", "cut")),
            )
        )
        current_time = s_end

    new_warnings = StoryboardBuilder.lint_pacing(domain_scenes)
    new_total = sum(s.duration for s in domain_scenes)

    sb_raw["scenes"] = [s.to_dict() for s in domain_scenes]
    sb_raw["warnings"] = new_warnings
    sb_raw["pacing_warnings"] = new_warnings
    sb_raw["total_duration"] = new_total
    sb_raw["totalDuration"] = new_total

    # Update artifact metadata in DB
    meta = dict(artifact.artifact_metadata or {})
    meta["storyboard"] = sb_raw
    artifact.artifact_metadata = meta

    # Write to disk if JSON exists or markdown file exists
    if artifact.file_path:
        workspace_resolved = settings.workspace_dir.resolve()
        file_path_obj = Path(artifact.file_path)
        resolved = (
            file_path_obj.resolve()
            if file_path_obj.is_absolute()
            else (settings.workspace_dir / file_path_obj).resolve()
        )
        if resolved.is_relative_to(workspace_resolved):
            if resolved.suffix.lower() == ".json" and resolved.is_file():
                resolved.write_text(json.dumps(sb_raw, indent=2, ensure_ascii=False), encoding="utf-8")
            elif resolved.suffix.lower() == ".md":
                sibling_json = resolved.parent / "storyboard.json"
                if sibling_json.is_file():
                    sibling_json.write_text(json.dumps(sb_raw, indent=2, ensure_ascii=False), encoding="utf-8")
                new_md = StoryboardBuilder.to_markdown(domain_scenes, new_warnings, total_duration=new_total)
                resolved.write_text(new_md, encoding="utf-8")

    db.commit()

    normalized = _normalize_storyboard_dict(sb_raw)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "success", "data": normalized},
    )
