"""Brain API router for document ingestion, management, and semantic RAG search (Task 4.1)."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
import shutil
import tempfile
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel, Field

from app.brain.ingest import (
    DocumentIngestor,
    DocumentParsingError,
    ScannedPdfError,
    UnsupportedFormatError,
)
from app.brain.retriever import BrainRetriever
from app.config import get_settings
from app.orchestrator.dispatcher import mask_secrets

router = APIRouter(prefix="/api/v1/brain", tags=["brain"])


class SearchRequest(BaseModel):
    query: str
    collections: list[str] = Field(default_factory=lambda: ["default"])
    top_k: int = Field(default=5, ge=1, le=50)
    min_similarity: float = Field(default=0.7, ge=0.0, le=1.0)


def _resolve_and_validate_path(file_path_str: str, workspace_dir: Path) -> Path:
    """Validates that file_path strictly resides within workspace_dir and exists as a regular file."""
    workspace_resolved = workspace_dir.resolve()
    target_path = Path(file_path_str)
    resolved_path = (
        target_path.resolve()
        if target_path.is_absolute()
        else (workspace_resolved / target_path).resolve()
    )
    try:
        if not resolved_path.is_relative_to(workspace_resolved):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Từ chối truy cập: tệp nằm ngoài thư mục workspace",
            )
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Từ chối truy cập: tệp nằm ngoài thư mục workspace",
        )
    if not resolved_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tệp không tồn tại: {target_path}",
        )
    return resolved_path


@router.post("/documents")
async def ingest_document(
    request: Request,
    file: Optional[UploadFile] = File(None),
    file_path: Optional[str] = Form(None),
    collection: Optional[str] = Form(None),
    query_collection: Optional[str] = Query(None, alias="collection"),
) -> Any:
    """Ingests a document from multipart file upload or local file path."""
    content_type = request.headers.get("content-type", "")
    target_collection = collection or query_collection or "default"
    temp_file_to_clean: Optional[Path] = None
    target_path: Optional[Path] = None
    orig_name: Optional[str] = None

    settings = getattr(request.app.state, "settings", None) or get_settings()
    workspace_dir = settings.workspace_dir

    try:
        if "application/json" in content_type:
            body = await request.json()
            req_file_path = body.get("file_path")
            if not req_file_path:
                raise HTTPException(
                    status_code=422,
                    detail="Thiếu tham số 'file_path'",
                )
            target_path = _resolve_and_validate_path(req_file_path, workspace_dir)
            target_collection = body.get("collection") or target_collection
            orig_name = target_path.name
        elif file is not None and file.filename:
            # Sanitize filename to prevent directory traversal
            clean_filename = Path(file.filename).name
            orig_name = clean_filename
            ext = Path(clean_filename).suffix

            if ext.lower() not in DocumentIngestor.SUPPORTED_EXTENSIONS:
                raise HTTPException(
                    status_code=422,
                    detail=f"Định dạng tệp không được hỗ trợ: {ext}",
                )

            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                shutil.copyfileobj(file.file, tmp)
                temp_file_to_clean = Path(tmp.name)
            target_path = temp_file_to_clean
        elif file_path:
            target_path = _resolve_and_validate_path(file_path, workspace_dir)
            orig_name = target_path.name
        else:
            raise HTTPException(
                status_code=422,
                detail="Vui lòng tải lên tệp hoặc cung cấp file_path",
            )

        chroma_dir = settings.resolved_chroma_dir
        ingestor = DocumentIngestor(chroma_dir=chroma_dir)

        result = ingestor.ingest_file(
            target_path,
            collection=target_collection,
            original_filename=orig_name,
        )

        res_dict = asdict(result) if is_dataclass(result) else result
        return mask_secrets(res_dict)

    except (ScannedPdfError, DocumentParsingError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except UnsupportedFormatError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    finally:
        if temp_file_to_clean and temp_file_to_clean.exists():
            try:
                temp_file_to_clean.unlink(missing_ok=True)
            except Exception:
                pass


@router.get("/documents")
async def list_documents(
    request: Request,
    collection: Optional[str] = Query(None),
) -> Any:
    """Lists ingested documents, optionally filtered by collection."""
    settings = getattr(request.app.state, "settings", None) or get_settings()
    chroma_dir = settings.resolved_chroma_dir
    retriever = BrainRetriever(chroma_dir=chroma_dir)
    docs = retriever.list_documents(collection=collection)
    return mask_secrets(docs)


@router.delete("/documents/{doc_id}")
async def delete_document(
    request: Request,
    doc_id: str,
) -> Any:
    """Deletes an ingested document and its vector chunks."""
    settings = getattr(request.app.state, "settings", None) or get_settings()
    chroma_dir = settings.resolved_chroma_dir
    retriever = BrainRetriever(chroma_dir=chroma_dir)
    deleted = retriever.delete_document(doc_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tài liệu không tồn tại",
        )
    return {"status": "deleted", "doc_id": doc_id}


@router.post("/search")
async def search_documents(
    request: Request,
    payload: SearchRequest,
) -> Any:
    """Performs semantic vector search across specified collections."""
    settings = getattr(request.app.state, "settings", None) or get_settings()
    chroma_dir = settings.resolved_chroma_dir
    retriever = BrainRetriever(chroma_dir=chroma_dir)

    # Sanitize input query if it contains secret tokens
    clean_query = mask_secrets(payload.query)

    hits = retriever.search(
        query=clean_query,
        collections=payload.collections,
        top_k=payload.top_k,
        min_similarity=payload.min_similarity,
    )

    hits_data = [asdict(h) if is_dataclass(h) else h for h in hits]
    return mask_secrets(hits_data)
