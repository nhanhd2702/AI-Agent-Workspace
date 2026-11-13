"""Brain Document Ingestion Module (Task 4.1).

Parses documents (.pdf, .docx, .txt, .md, .csv), chunks text, detects scanned PDFs,
enforces workspace storage caps, deduplicates via SHA-256, stores chunks in ChromaDB,
and invalidates query cache.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
from typing import Optional
import uuid

import docx
import pypdf

from app.config import get_settings

# Module-level shared re-entrant lock for manifest operations across Ingestor & Retriever
BRAIN_MANIFEST_LOCK = threading.RLock()


def normalize_collection_name(name: str) -> str:
    """Sanitizes and normalizes collection name for ChromaDB (3-512 chars).

    Ensures name starts with alpha (avoids IPv4 regex), contains no consecutive dots,
    and ends with an alphanumeric character.
    """
    clean = name.strip()
    clean = re.sub(r"[^a-zA-Z0-9._-]", "_", clean)
    clean = re.sub(r"\.{2,}", "_", clean)
    if not clean or not clean[0].isalpha():
        clean = f"col_{clean}"
    clean = clean[:512]
    clean = clean.rstrip("._-")
    if len(clean) < 3:
        clean = f"{clean}_col"[:512]
    clean = clean.rstrip("._-")
    if len(clean) < 3:
        clean = "col_default"
    return clean


class ScannedPdfError(Exception):
    """Raised when a PDF contains no extractable text."""


class UnsupportedFormatError(ValueError):
    """Raised when a document format is not supported."""


class DocumentParsingError(ValueError):
    """Raised when a document cannot be parsed or is corrupted."""


@dataclass
class IngestResult:
    """Result summary of a document ingestion operation."""

    doc_id: str
    filename: str
    collection: str
    chunk_count: int
    sha256: str
    deduplicated: bool = False
    total_chars: int = 0


def chunk_text(text: str, chunk_size: int = 2000, overlap: int = 200) -> list[str]:
    """Splits text into ~512 token (~2000 chars) chunks with ~50 token (~200 chars) overlap."""
    clean_text = text.strip()
    if not clean_text:
        return []
    if len(clean_text) <= chunk_size:
        return [clean_text]

    chunks: list[str] = []
    start = 0
    total_len = len(clean_text)

    while start < total_len:
        end = min(start + chunk_size, total_len)
        if end < total_len:
            # Look for paragraph or sentence break near the end of the window
            break_pt = clean_text.rfind("\n", max(start, end - 150), end)
            if break_pt == -1:
                break_pt = clean_text.rfind(" ", max(start, end - 150), end)
            if break_pt > start:
                end = break_pt + 1

        segment = clean_text[start:end].strip()
        if segment:
            chunks.append(segment)

        if end >= total_len:
            break

        start = max(start + 1, end - overlap)

    return chunks


class DocumentIngestor:
    """Parses, chunks, deduplicates, and stores documents in ChromaDB vector store."""

    SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".csv"}

    def __init__(
        self,
        chroma_dir: Optional[Path] = None,
        max_docs: int = 100,
        max_total_mb: float = 50.0,
    ) -> None:
        if chroma_dir is not None:
            self.chroma_dir = Path(chroma_dir).resolve()
        else:
            self.chroma_dir = get_settings().resolved_chroma_dir

        self.chroma_dir.mkdir(parents=True, exist_ok=True)
        self.max_docs = max_docs
        self.max_total_mb = max_total_mb
        self.manifest_path = self.chroma_dir / "brain_manifest.json"

        # Lazy import chromadb to keep module import fast
        import chromadb

        self.chroma_client = chromadb.PersistentClient(path=str(self.chroma_dir))

    def _load_manifest(self) -> dict:
        with BRAIN_MANIFEST_LOCK:
            if not self.manifest_path.exists():
                return {"documents": {}}
            try:
                with open(self.manifest_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {"documents": {}}

    def _save_manifest(self, manifest: dict) -> None:
        with BRAIN_MANIFEST_LOCK:
            temp_path = self.manifest_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
            temp_path.replace(self.manifest_path)

    def _extract_pdf(self, file_path: Path) -> list[tuple[str, int]]:
        """Extracts text page by page from PDF. Raises ScannedPdfError if empty."""
        try:
            reader = pypdf.PdfReader(str(file_path))
            pages_chunks: list[tuple[str, int]] = []
            total_text = ""

            for page_idx, page in enumerate(reader.pages):
                page_text = page.extract_text() or ""
                total_text += page_text
                clean = page_text.strip()
                if clean:
                    sub_chunks = chunk_text(clean, chunk_size=2000, overlap=200)
                    for chunk in sub_chunks:
                        pages_chunks.append((chunk, page_idx + 1))
        except ScannedPdfError:
            raise
        except Exception as exc:
            raise DocumentParsingError(f"Tệp PDF không hợp lệ hoặc bị lỗi: {exc}") from exc

        if not total_text.strip():
            raise ScannedPdfError("PDF dạng ảnh hoặc không chứa văn bản có thể trích xuất")

        return pages_chunks

    def _extract_docx(self, file_path: Path) -> list[tuple[str, Optional[int]]]:
        """Extracts text from .docx paragraphs and tables."""
        try:
            doc = docx.Document(str(file_path))
            paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            table_lines = []
            for table in doc.tables:
                for row in table.rows:
                    cells_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                    if cells_text:
                        table_lines.append(cells_text)
            full_text = "\n\n".join(paragraphs + table_lines)
            chunks = chunk_text(full_text, chunk_size=2000, overlap=200)
            return [(c, None) for c in chunks]
        except Exception as exc:
            raise DocumentParsingError(f"Tệp DOCX không hợp lệ hoặc bị lỗi: {exc}") from exc

    def _extract_csv(self, file_path: Path) -> list[tuple[str, Optional[int]]]:
        """Extracts tabular text from .csv files."""
        try:
            lines = []
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.reader(f)
                for row in reader:
                    line = ", ".join(row).strip()
                    if line:
                        lines.append(line)
            full_text = "\n".join(lines)
            chunks = chunk_text(full_text, chunk_size=2000, overlap=200)
            return [(c, None) for c in chunks]
        except Exception as exc:
            raise DocumentParsingError(f"Tệp CSV không hợp lệ hoặc bị lỗi: {exc}") from exc

    def _extract_text(self, file_path: Path) -> list[tuple[str, Optional[int]]]:
        """Extracts text from .txt and .md files."""
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                full_text = f.read()
            chunks = chunk_text(full_text, chunk_size=2000, overlap=200)
            return [(c, None) for c in chunks]
        except Exception as exc:
            raise DocumentParsingError(f"Không thể đọc tệp văn bản: {exc}") from exc

    def ingest_file(
        self,
        file_path: Path | str,
        collection: str = "default",
        original_filename: Optional[str] = None,
    ) -> IngestResult:
        """Ingests a single file into the vector database.

        Checks SHA-256 for deduplication and validates workspace caps before inserting.
        """
        path = Path(file_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Tệp không tồn tại: {path}")

        ext = path.suffix.lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            raise UnsupportedFormatError(f"Định dạng tệp không được hỗ trợ: {ext}")

        content_bytes = path.read_bytes()
        file_sha256 = hashlib.sha256(content_bytes).hexdigest()
        filename = original_filename or path.name

        manifest = self._load_manifest()
        docs_dict = manifest.setdefault("documents", {})

        # 1. Deduplication check within this collection
        for doc_item in docs_dict.values():
            if doc_item.get("collection") == collection and doc_item.get("sha256") == file_sha256:
                return IngestResult(
                    doc_id=doc_item["doc_id"],
                    filename=doc_item["filename"],
                    collection=collection,
                    chunk_count=doc_item["chunk_count"],
                    sha256=file_sha256,
                    deduplicated=True,
                    total_chars=doc_item.get("total_chars", 0),
                )

        # 2. Check storage caps
        if len(docs_dict) >= self.max_docs:
            raise ValueError(f"Vượt quá giới hạn số lượng tài liệu (tối đa {self.max_docs} tài liệu)")

        current_total_bytes = sum(
            d.get("file_size_bytes", d.get("total_chars", 0)) for d in docs_dict.values()
        )
        if (current_total_bytes + len(content_bytes)) > (self.max_total_mb * 1024 * 1024):
            raise ValueError(f"Vượt quá giới hạn dung lượng ({self.max_total_mb}MB)")

        # 3. Extract text according to format
        if ext == ".pdf":
            chunks_with_pages = self._extract_pdf(path)
        elif ext == ".docx":
            chunks_with_pages = self._extract_docx(path)
        elif ext == ".csv":
            chunks_with_pages = self._extract_csv(path)
        else:  # .txt, .md
            chunks_with_pages = self._extract_text(path)

        if not chunks_with_pages:
            chunks_with_pages = [("", None)]

        doc_id = f"doc_{uuid.uuid4().hex[:12]}"

        # 4. Store in ChromaDB collection
        chroma_col_name = normalize_collection_name(collection)
        col = self.chroma_client.get_or_create_collection(
            name=chroma_col_name,
            metadata={"hnsw:space": "cosine"},
        )

        chunk_ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict] = []

        for idx, (chunk_text_str, page_num) in enumerate(chunks_with_pages):
            chunk_id = f"{doc_id}_{idx}"
            chunk_ids.append(chunk_id)
            documents.append(chunk_text_str)
            meta: dict = {
                "doc_id": doc_id,
                "doc_title": filename,
                "collection": collection,
                "sha256": file_sha256,
                "chunk_index": idx,
            }
            if page_num is not None:
                meta["page"] = int(page_num)
            metadatas.append(meta)

        col.add(ids=chunk_ids, documents=documents, metadatas=metadatas)

        # 5. Record document in manifest
        total_chars = sum(len(c[0]) for c in chunks_with_pages)
        docs_dict[doc_id] = {
            "doc_id": doc_id,
            "filename": filename,
            "collection": collection,
            "chunk_count": len(chunks_with_pages),
            "sha256": file_sha256,
            "total_chars": total_chars,
            "file_size_bytes": len(content_bytes),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save_manifest(manifest)

        # 6. Invalidate search cache
        from app.brain.retriever import BrainRetriever

        BrainRetriever.clear_cache()

        return IngestResult(
            doc_id=doc_id,
            filename=filename,
            collection=collection,
            chunk_count=len(chunks_with_pages),
            sha256=file_sha256,
            deduplicated=False,
            total_chars=total_chars,
        )
