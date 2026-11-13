"""Brain API router for document ingestion, management, semantic RAG search, Brand Profile, and Product Catalog (Tasks 4.1 & 4.2)."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
import shutil
import tempfile
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.brain.catalog import CatalogService
from app.brain.ingest import (
    DocumentIngestor,
    DocumentParsingError,
    ScannedPdfError,
    UnsupportedFormatError,
)
from app.brain.retriever import BrainRetriever
from app.config import get_settings
from app.db.models import BrandProfile, Product
from app.db.session import get_db
from app.orchestrator.dispatcher import mask_secrets

router = APIRouter(prefix="/api/v1/brain", tags=["brain"])


class SearchRequest(BaseModel):
    query: str
    collections: list[str] = Field(default_factory=lambda: ["default"])
    top_k: int = Field(default=5, ge=1, le=50)
    min_similarity: float = Field(default=0.7, ge=0.0, le=1.0)


class BrandProfileUpdate(BaseModel):
    brand_name: Optional[str] = None
    tagline: Optional[str] = None
    target_audience: Optional[str] = None
    tone_of_voice: Optional[str] = None
    brand_colors: Optional[list[str]] = None
    fonts: Optional[list[str]] = None
    legal_boundaries: Optional[str] = None
    logo_asset_id: Optional[str] = None
    is_active: Optional[bool] = None
    project_id: Optional[str] = "proj-default"


class ProductUpsertPayload(BaseModel):
    id: Optional[str] = None
    project_id: Optional[str] = "proj-default"
    sku: str
    name: str
    price_vnd: int = Field(default=0, ge=0)
    tier_type: Optional[str] = None
    short_desc: Optional[str] = None
    full_desc: Optional[str] = None
    deliverables: Optional[list[str]] = None
    faqs: Optional[list[dict[str, Any]]] = None
    policies: Optional[list[str]] = None
    is_active: Optional[bool] = True


def _serialize_brand_profile(bp: BrandProfile) -> dict[str, Any]:
    return {
        "id": bp.id,
        "project_id": bp.project_id,
        "brand_name": bp.brand_name,
        "tagline": bp.tagline,
        "target_audience": bp.target_audience,
        "tone_of_voice": bp.tone_of_voice,
        "brand_colors": bp.brand_colors or [],
        "fonts": bp.fonts or [],
        "legal_boundaries": bp.legal_boundaries,
        "logo_asset_id": bp.logo_asset_id,
        "is_active": bp.is_active,
        "created_at": bp.created_at.isoformat() if bp.created_at else None,
        "updated_at": bp.updated_at.isoformat() if bp.updated_at else None,
    }


def _serialize_product(p: Product) -> dict[str, Any]:
    return {
        "id": p.id,
        "project_id": p.project_id,
        "sku": p.sku,
        "name": p.name,
        "price_vnd": p.price_vnd,
        "tier_type": p.tier_type,
        "short_desc": p.short_desc,
        "full_desc": p.full_desc,
        "deliverables": p.deliverables or [],
        "faqs": p.faqs or [],
        "policies": p.policies or [],
        "price_history": p.price_history or [],
        "is_active": p.is_active,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


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
            detail=f"Tá»‡p khÃ´ng tá»“n táº¡i: {target_path}",
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
                    detail="Thiáº¿u tham sá»‘ 'file_path'",
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
                    detail=f"Ä á»‹nh dáº¡ng tá»‡p khÃ´ng Ä‘Æ°á»£c há»— trá»£: {ext}",
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
                detail="Vui lÃ²ng táº£i lÃªn tá»‡p hoáº·c cung cáº¥p file_path",
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
            detail="TÃ i liá»‡u khÃ´ng tá»“n táº¡i",
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

    clean_query = mask_secrets(payload.query)

    hits = retriever.search(
        query=clean_query,
        collections=payload.collections,
        top_k=payload.top_k,
        min_similarity=payload.min_similarity,
    )

    hits_data = [asdict(h) if is_dataclass(h) else h for h in hits]
    return mask_secrets(hits_data)


# --------------------------------------------------------------------------
# Brand Profile Endpoints (Task 4.2)
# --------------------------------------------------------------------------


@router.get("/brand-profile")
async def get_brand_profile(
    request: Request,
    project_id: str = Query("proj-default"),
    db: Session = Depends(get_db),
) -> Any:
    """Returns the current BrandProfile and available starter templates."""
    settings = getattr(request.app.state, "settings", None) or get_settings()
    service = CatalogService(
        chroma_dir=settings.resolved_chroma_dir,
        workspace_root=settings.workspace_dir,
    )
    profile = service.get_brand_profile(db, project_id=project_id)
    templates = service.get_starter_templates()
    return mask_secrets(
        {
            "profile": _serialize_brand_profile(profile),
            "templates": templates,
        }
    )


@router.put("/brand-profile")
async def update_brand_profile(
    request: Request,
    payload: BrandProfileUpdate,
    db: Session = Depends(get_db),
) -> Any:
    """Updates the BrandProfile and syncs guidelines to ChromaDB collection 'brand_profile'."""
    settings = getattr(request.app.state, "settings", None) or get_settings()
    service = CatalogService(
        chroma_dir=settings.resolved_chroma_dir,
        workspace_root=settings.workspace_dir,
    )
    target_project = payload.project_id or "proj-default"
    data = payload.model_dump(exclude_unset=True)
    profile = service.save_brand_profile(db, data, project_id=target_project)
    return mask_secrets(_serialize_brand_profile(profile))


# --------------------------------------------------------------------------
# Product Catalog Endpoints (Task 4.2)
# --------------------------------------------------------------------------


@router.get("/products")
async def list_products(
    request: Request,
    project_id: str = Query("proj-default"),
    active_only: bool = Query(False),
    db: Session = Depends(get_db),
) -> Any:
    """Lists products for a project, optionally filtered by active status."""
    settings = getattr(request.app.state, "settings", None) or get_settings()
    service = CatalogService(
        chroma_dir=settings.resolved_chroma_dir,
        workspace_root=settings.workspace_dir,
    )
    products = service.list_products(db, project_id=project_id, active_only=active_only)
    return mask_secrets([_serialize_product(p) for p in products])


@router.post("/products", status_code=status.HTTP_201_CREATED)
async def upsert_product(
    request: Request,
    payload: ProductUpsertPayload,
    db: Session = Depends(get_db),
) -> Any:
    """Creates or updates a product, logs price changes, and syncs vector index."""
    settings = getattr(request.app.state, "settings", None) or get_settings()
    service = CatalogService(
        chroma_dir=settings.resolved_chroma_dir,
        workspace_root=settings.workspace_dir,
    )
    try:
        data = payload.model_dump(exclude_unset=True)
        prod = service.upsert_product(db, data, project_id=payload.project_id or "proj-default")
        return mask_secrets(_serialize_product(prod))
    except ValueError as exc:
        err_msg = str(exc)
        if "không thuộc dự án" in err_msg:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=err_msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err_msg)


@router.delete("/products/{product_id}")
async def delete_product(
    request: Request,
    product_id: str,
    project_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
) -> Any:
    """Deletes a product from database and ChromaDB vector index."""
    settings = getattr(request.app.state, "settings", None) or get_settings()
    service = CatalogService(
        chroma_dir=settings.resolved_chroma_dir,
        workspace_root=settings.workspace_dir,
    )
    try:
        deleted = service.delete_product(db, product_id, project_id=project_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Sản phẩm không tồn tại",
            )
        return {"status": "deleted", "product_id": product_id}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.get("/products/{product_id}/history")
async def get_product_history(
    request: Request,
    product_id: str,
    project_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
) -> Any:
    """Retrieves chronological price change audit log for a product."""
    settings = getattr(request.app.state, "settings", None) or get_settings()
    service = CatalogService(
        chroma_dir=settings.resolved_chroma_dir,
        workspace_root=settings.workspace_dir,
    )
    try:
        history = service.get_price_history(db, product_id, project_id=project_id)
        return mask_secrets(history)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.post("/products/import-csv")
async def import_products_csv(
    request: Request,
    file: Optional[UploadFile] = File(None),
    csv_content: Optional[str] = Form(None),
    project_id: str = Query("proj-default"),
    db: Session = Depends(get_db),
) -> Any:
    """Bulk imports up to 500 products from CSV file upload or text content."""
    content_str = ""
    if file is not None:
        raw_bytes = await file.read()
        content_str = raw_bytes.decode("utf-8-sig", errors="replace")
    elif csv_content:
        content_str = csv_content
    elif "application/json" in request.headers.get("content-type", ""):
        body = await request.json()
        content_str = body.get("csv_content", "")
    else:
        raise HTTPException(
            status_code=422,
            detail="Vui lÃ²ng táº£i lÃªn tá»‡p CSV hoáº·c cung cáº¥p csv_content",
        )

    if not content_str.strip():
        raise HTTPException(
            status_code=422,
            detail="Ná»™i dung CSV trá»‘ng",
        )

    settings = getattr(request.app.state, "settings", None) or get_settings()
    service = CatalogService(
        chroma_dir=settings.resolved_chroma_dir,
        workspace_root=settings.workspace_dir,
    )
    result = service.import_csv(db, content_str, project_id=project_id)
    return mask_secrets(result)
