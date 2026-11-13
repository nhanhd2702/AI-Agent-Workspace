"""Files API: Library, Upload, 5GB Quota Guard, Temp Cleanup, and Batch ZIP Export (Task 5.3 / F06.5 / F03).

Implements:
- POST /api/v1/files/upload: Multipart file upload with path validation & 5GB quota limit (HTTP 507).
- GET /api/v1/files: File listing with filters (file_type, project_id, search).
- POST /api/v1/files/export: Batch export files into a ZIP archive download.
- DELETE /api/v1/files/{file_id}: Delete physical file and DB record.
- POST /api/v1/files/cleanup: Delete temp files older than N days.
- GET /api/v1/files/storage: Storage quota and workspace utilization summary.
"""

from __future__ import annotations

from datetime import datetime, timezone
import mimetypes
import os
from pathlib import Path
from typing import Any, List, Optional
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.artifacts.exporter import (
    FileExporter,
    InsufficientDiskSpaceError,
    cleanup_old_temp_files,
    organize_file_path,
)
from app.config import AppSettings, get_settings
from app.db.models import Artifact, FileAsset, Project, Task
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/files", tags=["files"])


# --- Schemas ---

class ExportRequest(BaseModel):
    """Payload for batch ZIP export."""
    file_ids: List[str] = Field(..., description="List of FileAsset or Artifact IDs to package")


# --- Utilities ---

def get_workspace_size_bytes(workspace_dir: Path) -> int:
    """Calculate total byte size of all files inside workspace directory."""
    total = 0
    resolved = workspace_dir.resolve()
    if not resolved.exists():
        return 0
    try:
        for root, _, files in os.walk(resolved):
            for f in files:
                try:
                    fp = os.path.join(root, f)
                    total += os.path.getsize(fp)
                except OSError:
                    continue
    except OSError:
        pass
    return total


def detect_file_type(filename: str, mime_type: Optional[str] = None) -> str:
    """Classify file into standard categories: image, video, audio, document, code, other."""
    ext = Path(filename).suffix.lower()
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico"):
        return "image"
    if ext in (".mp4", ".m4v", ".webm", ".mov", ".avi", ".mkv"):
        return "video"
    if ext in (".mp3", ".wav", ".ogg", ".oga", ".m4a", ".flac"):
        return "video"  # grouped under Video & Media
    if ext in (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".csv", ".txt", ".md"):
        return "document"
    if ext in (".html", ".htm", ".css", ".js", ".ts", ".tsx", ".jsx", ".json", ".py", ".sh", ".sql"):
        return "code"
    if mime_type:
        if mime_type.startswith("image/"):
            return "image"
        if mime_type.startswith("video/") or mime_type.startswith("audio/"):
            return "video"
        if "pdf" in mime_type or "document" in mime_type or "text/" in mime_type:
            return "document"
    return "other"


def _format_datetime(dt: Optional[datetime]) -> Optional[str]:
    """Serialize datetime as ISO-8601 string with UTC indicator."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat()


# --- Endpoints ---

@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    project_id: Optional[str] = Form(None),
    task_slug: Optional[str] = Form(None),
    task_id: Optional[str] = Form(None),
    category: str = Form("upload"),
    db: Session = Depends(get_db),
    settings: AppSettings = Depends(get_settings),
):
    """Upload a file to the workspace library with 5GB quota limit and path organization."""
    active_settings = getattr(request.app.state, "settings", None) or settings

    raw_filename = file.filename or "uploaded_file.bin"
    # Reject or sanitize path traversal
    clean_filename = Path(raw_filename).name
    if not clean_filename or clean_filename in (".", ".."):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid filename: '{raw_filename}'",
        )

    # Read uploaded content
    content = await file.read()
    file_size = len(content)

    # 5GB Quota Guard check
    max_workspace_bytes = getattr(
        active_settings, "max_workspace_bytes", 5 * 1024 * 1024 * 1024
    )
    current_workspace_bytes = get_workspace_size_bytes(active_settings.workspace_dir)

    if (current_workspace_bytes + file_size) > max_workspace_bytes:
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail=(
                f"Workspace storage quota exceeded (5GB limit). "
                f"Current usage: {current_workspace_bytes} bytes, upload size: {file_size} bytes, "
                f"max quota: {max_workspace_bytes} bytes."
            ),
        )

    # Organize destination path: workspace/{project}/{YYYY-MM}/{task_slug}/{filename}
    target_project = project_id or "default"
    target_task_slug = task_slug or (task_id if task_id else "general")

    dest_path = organize_file_path(
        workspace=active_settings.workspace_dir,
        project=target_project,
        task_slug=target_task_slug,
        filename=clean_filename,
    )

    # Write file content to disk
    dest_path.write_bytes(content)

    # Resolve relative path for storage
    try:
        rel_path = str(dest_path.relative_to(active_settings.workspace_dir.resolve())).replace("\\", "/")
    except ValueError:
        rel_path = str(dest_path).replace("\\", "/")

    detected_type = detect_file_type(clean_filename, file.content_type)
    mime = file.content_type or mimetypes.guess_type(clean_filename)[0] or "application/octet-stream"

    file_asset = FileAsset(
        id=f"file-{uuid.uuid4().hex[:12]}",
        project_id=project_id,
        task_id=task_id,
        name=clean_filename,
        file_path=rel_path,
        file_type=detected_type,
        mime_type=mime,
        size_bytes=file_size,
        category=category,
        file_metadata={"original_name": raw_filename},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(file_asset)
    db.commit()
    db.refresh(file_asset)

    return {
        "status": "success",
        "data": {
            "id": file_asset.id,
            "project_id": file_asset.project_id,
            "task_id": file_asset.task_id,
            "name": file_asset.name,
            "file_path": file_asset.file_path,
            "file_type": file_asset.file_type,
            "mime_type": file_asset.mime_type,
            "size_bytes": file_asset.size_bytes,
            "category": file_asset.category,
            "created_at": _format_datetime(file_asset.created_at),
        },
    }


@router.get("", status_code=status.HTTP_200_OK)
def list_files(
    file_type: Optional[str] = Query(None, description="Filter by file type (image, video, document, code)"),
    project_id: Optional[str] = Query(None, description="Filter by project ID"),
    search: Optional[str] = Query(None, description="Search term in filename"),
    db: Session = Depends(get_db),
    settings: AppSettings = Depends(get_settings),
):
    """List all files in workspace library (both FileAssets and Artifacts) with filtering."""
    # 1. Query FileAssets
    q_fa = db.query(FileAsset)
    if project_id:
        q_fa = q_fa.filter(FileAsset.project_id == project_id)
    if search:
        search_pat = f"%{search.strip()}%"
        q_fa = q_fa.filter(FileAsset.name.ilike(search_pat))

    file_assets = q_fa.all()

    # 2. Query Artifacts to show generated artifacts in Library
    q_art = db.query(Artifact)
    if search:
        search_pat = f"%{search.strip()}%"
        q_art = q_art.filter(Artifact.name.ilike(search_pat))

    artifacts = q_art.all()

    # Map both into unified representation
    items: list[dict[str, Any]] = []

    for fa in file_assets:
        resolved_type = fa.file_type or detect_file_type(fa.name, fa.mime_type)
        items.append({
            "id": fa.id,
            "project_id": fa.project_id,
            "task_id": fa.task_id,
            "name": fa.name,
            "file_path": fa.file_path,
            "file_type": resolved_type,
            "mime_type": fa.mime_type,
            "size_bytes": fa.size_bytes,
            "category": fa.category or "upload",
            "created_at": _format_datetime(fa.created_at),
        })

    for art in artifacts:
        # Check project if project_id filter is requested
        art_project_id = None
        if art.task and art.task.project_id:
            art_project_id = art.task.project_id

        if project_id and art_project_id != project_id:
            continue

        resolved_type = art.file_type or detect_file_type(art.name, art.mime_type)
        items.append({
            "id": art.id,
            "project_id": art_project_id,
            "task_id": art.task_id,
            "name": art.name,
            "file_path": art.file_path,
            "file_type": resolved_type,
            "mime_type": art.mime_type,
            "size_bytes": art.size_bytes,
            "category": art.category or "output",
            "created_at": _format_datetime(art.created_at),
        })

    # Filter by file_type if requested
    if file_type and file_type != "all":
        ft_lower = file_type.lower()
        if ft_lower in ("image", "images", "hinh-anh", "hình ảnh"):
            items = [i for i in items if i["file_type"] == "image"]
        elif ft_lower in ("video", "audio", "media", "video & media"):
            items = [i for i in items if i["file_type"] in ("video", "audio", "media")]
        elif ft_lower in ("document", "documents", "tai-lieu", "tài liệu"):
            items = [i for i in items if i["file_type"] in ("document", "text")]
        elif ft_lower in ("code", "html", "code & html"):
            items = [i for i in items if i["file_type"] in ("code", "html")]
        else:
            items = [i for i in items if i["file_type"] == ft_lower]

    # Sort descending by created_at
    items.sort(key=lambda x: x["created_at"] or "", reverse=True)

    return {"status": "success", "data": items}


@router.post("/export", status_code=status.HTTP_200_OK)
def export_files_zip(
    request: Request,
    payload: ExportRequest,
    db: Session = Depends(get_db),
    settings: AppSettings = Depends(get_settings),
):
    """Batch package selected file IDs into a single downloadable ZIP archive."""
    active_settings = getattr(request.app.state, "settings", None) or settings

    if not payload.file_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No file IDs provided for export",
        )

    resolved_paths: list[Path] = []
    workspace_resolved = active_settings.workspace_dir.resolve()

    for fid in payload.file_ids:
        # Check FileAsset
        file_asset = db.query(FileAsset).filter(FileAsset.id == fid).first()
        target_path: Optional[Path] = None

        if file_asset and file_asset.file_path:
            p = Path(file_asset.file_path)
            target_path = p if p.is_absolute() else (active_settings.workspace_dir / p)
        else:
            # Check Artifact
            artifact = db.query(Artifact).filter(Artifact.id == fid).first()
            if artifact and artifact.file_path:
                p = Path(artifact.file_path)
                target_path = p if p.is_absolute() else (active_settings.workspace_dir / p)

        if target_path:
            resolved = target_path.resolve()
            if resolved.is_file() and resolved.is_relative_to(workspace_resolved):
                resolved_paths.append(resolved)

    if not resolved_paths:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="None of the requested files were found on disk",
        )

    # Create temporary zip archive in workspace/temp/
    temp_dir = active_settings.workspace_dir / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    zip_dest = temp_dir / f"bundle_{uuid.uuid4().hex[:8]}.zip"

    try:
        FileExporter.export_zip(resolved_paths, zip_dest)
        zip_bytes = zip_dest.read_bytes()
    except InsufficientDiskSpaceError as exc:
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail=str(exc),
        )
    finally:
        # Clean up temporary zip file after reading bytes into memory
        if zip_dest.exists():
            try:
                zip_dest.unlink()
            except OSError:
                pass

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": "attachment; filename=bundle.zip",
            "Content-Type": "application/zip",
        },
    )


@router.delete("/{file_id}", status_code=status.HTTP_200_OK)
def delete_file(
    file_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: AppSettings = Depends(get_settings),
):
    """Delete a file from disk and database."""
    active_settings = getattr(request.app.state, "settings", None) or settings

    file_asset = db.query(FileAsset).filter(FileAsset.id == file_id).first()
    target_record = None

    if file_asset:
        target_record = file_asset
    else:
        artifact = db.query(Artifact).filter(Artifact.id == file_id).first()
        if artifact:
            target_record = artifact

    if not target_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File with ID '{file_id}' not found",
        )

    # Delete physical file on disk if exists and within workspace
    if target_record.file_path:
        p = Path(target_record.file_path)
        workspace_resolved = active_settings.workspace_dir.resolve()
        resolved = p if p.is_absolute() else (active_settings.workspace_dir / p).resolve()
        if resolved.exists() and resolved.is_file() and resolved.is_relative_to(workspace_resolved):
            try:
                resolved.unlink()
            except OSError:
                pass

    db.delete(target_record)
    db.commit()

    return {
        "status": "success",
        "data": {"deleted": True, "id": file_id},
    }


@router.post("/cleanup", status_code=status.HTTP_200_OK)
def cleanup_temp(
    request: Request,
    days: int = Query(7, ge=1, description="Threshold age in days for temp pruning"),
    settings: AppSettings = Depends(get_settings),
):
    """Prune files older than N days from workspace temp/, frames/, and cache/ folders."""
    active_settings = getattr(request.app.state, "settings", None) or settings
    res = cleanup_old_temp_files(workspace=active_settings.workspace_dir, days=days)
    return {
        "status": "success",
        "data": res,
    }


@router.get("/storage", status_code=status.HTTP_200_OK)
def get_storage_summary(
    request: Request,
    settings: AppSettings = Depends(get_settings),
):
    """Get current storage usage vs 5GB workspace quota limit."""
    active_settings = getattr(request.app.state, "settings", None) or settings

    used_bytes = get_workspace_size_bytes(active_settings.workspace_dir)
    max_bytes = getattr(active_settings, "max_workspace_bytes", 5 * 1024 * 1024 * 1024)

    percentage = round((used_bytes / max_bytes) * 100, 2) if max_bytes > 0 else 0.0
    used_mb = round(used_bytes / (1024 * 1024), 2)
    max_gb = round(max_bytes / (1024 * 1024 * 1024), 2)

    return {
        "status": "success",
        "data": {
            "used_bytes": used_bytes,
            "max_bytes": max_bytes,
            "percentage": percentage,
            "used_mb": used_mb,
            "max_gb": max_gb,
        },
    }
