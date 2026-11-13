"""Brain Retriever Module (Task 4.1).

Performs semantic vector search across ChromaDB collections, filters results by
similarity score (>= min_similarity), maintains a 5-minute TTL cache, and manages
document listing & deletion.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import threading
import time
from typing import Optional

from app.brain.ingest import BRAIN_MANIFEST_LOCK, normalize_collection_name
from app.config import get_settings


@dataclass
class ChunkHit:
    """A matched chunk result from a semantic search."""

    chunk_id: str
    doc_id: str
    doc_title: str
    collection: str
    text: str
    score: float
    page: Optional[int] = None


class BrainRetriever:
    """Queries ChromaDB vector collections with similarity filtering and in-memory TTL cache."""

    _cache: dict[tuple, tuple[float, list[ChunkHit]]] = {}
    _cache_lock = threading.Lock()
    CACHE_TTL_SECONDS = 300.0  # 5 minutes

    def __init__(
        self,
        chroma_dir: Optional[Path] = None,
        default_min_similarity: float = 0.7,
    ) -> None:
        if chroma_dir is not None:
            self.chroma_dir = Path(chroma_dir).resolve()
        else:
            self.chroma_dir = get_settings().resolved_chroma_dir

        self.chroma_dir.mkdir(parents=True, exist_ok=True)
        self.default_min_similarity = default_min_similarity
        self.manifest_path = self.chroma_dir / "brain_manifest.json"

        # Lazy import chromadb
        import chromadb

        self.chroma_client = chromadb.PersistentClient(path=str(self.chroma_dir))

    @classmethod
    def clear_cache(cls) -> None:
        """Flushes all cached query results."""
        with cls._cache_lock:
            cls._cache.clear()

    def search(
        self,
        query: str,
        collections: list[str],
        top_k: int = 5,
        min_similarity: Optional[float] = None,
    ) -> list[ChunkHit]:
        """Performs semantic search across the given ChromaDB collections.

        Filters out any hit with score < min_similarity (or default_min_similarity).
        Results are cached in-memory with a 5-minute TTL scoped to the chroma_dir.
        """
        threshold = (
            min_similarity if min_similarity is not None else self.default_min_similarity
        )
        clean_query = query.strip()
        sorted_collections = tuple(sorted(collections))
        cache_key = (
            str(self.chroma_dir.resolve()),
            clean_query,
            sorted_collections,
            top_k,
            round(threshold, 4),
        )

        # 1. Check TTL cache
        with self._cache_lock:
            if cache_key in self._cache:
                cached_time, cached_hits = self._cache[cache_key]
                if (time.time() - cached_time) < self.CACHE_TTL_SECONDS:
                    return [
                        ChunkHit(
                            chunk_id=h.chunk_id,
                            doc_id=h.doc_id,
                            doc_title=h.doc_title,
                            collection=h.collection,
                            text=h.text,
                            score=h.score,
                            page=h.page,
                        )
                        for h in cached_hits
                    ]

        # 2. Query each requested collection in ChromaDB
        candidate_hits: list[ChunkHit] = []

        for col_name in collections:
            try:
                chroma_col_name = normalize_collection_name(col_name)
                col = self.chroma_client.get_collection(name=chroma_col_name)
            except Exception:
                continue

            count = col.count()
            if count == 0:
                continue

            query_k = min(max(top_k * 2, 5), count)
            try:
                res = col.query(query_texts=[clean_query], n_results=query_k)
            except Exception:
                continue

            if not res or not res.get("ids") or not res["ids"][0]:
                continue

            ids = res["ids"][0]
            docs = res["documents"][0] if res.get("documents") else []
            metadatas = res["metadatas"][0] if res.get("metadatas") else []
            distances = res["distances"][0] if res.get("distances") else []

            for idx, chunk_id in enumerate(ids):
                dist = distances[idx] if idx < len(distances) else 1.0
                score = max(0.0, min(1.0, 1.0 - dist))

                # Strictly filter out hits below threshold
                if score < threshold:
                    continue

                meta = metadatas[idx] or {}
                doc_id = meta.get("doc_id", "")
                doc_title = meta.get("doc_title", "")
                collection = meta.get("collection", col_name)
                page = meta.get("page")
                text = docs[idx] if idx < len(docs) else ""

                candidate_hits.append(
                    ChunkHit(
                        chunk_id=chunk_id,
                        doc_id=doc_id,
                        doc_title=doc_title,
                        collection=collection,
                        text=text,
                        score=round(score, 4),
                        page=int(page) if page is not None else None,
                    )
                )

        # 3. Sort by similarity score descending and take top_k
        candidate_hits.sort(key=lambda h: h.score, reverse=True)
        final_hits = candidate_hits[:top_k]

        # 4. Cache results
        with self._cache_lock:
            self._cache[cache_key] = (time.time(), final_hits)

        return final_hits

    def list_documents(self, collection: Optional[str] = None) -> list[dict]:
        """Lists all ingested documents, optionally filtered by collection."""
        with BRAIN_MANIFEST_LOCK:
            if not self.manifest_path.exists():
                return []

            try:
                with open(self.manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
            except Exception:
                return []

            docs_dict = manifest.get("documents", {})
            if collection:
                return [d for d in docs_dict.values() if d.get("collection") == collection]
            return list(docs_dict.values())

    def delete_document(self, doc_id: str) -> bool:
        """Deletes a document and its chunks from ChromaDB and manifest.

        Invalidates query cache upon deletion.
        """
        with BRAIN_MANIFEST_LOCK:
            if not self.manifest_path.exists():
                return False

            try:
                with open(self.manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
            except Exception:
                return False

            docs_dict = manifest.get("documents", {})
            if doc_id not in docs_dict:
                return False

            doc_item = docs_dict[doc_id]
            col_name = doc_item.get("collection", "default")
            chroma_col_name = normalize_collection_name(col_name)

            # Delete chunks from ChromaDB
            try:
                col = self.chroma_client.get_collection(name=chroma_col_name)
                col.delete(where={"doc_id": doc_id})
            except Exception:
                pass

            # Remove from manifest
            del docs_dict[doc_id]
            temp_path = self.manifest_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
            temp_path.replace(self.manifest_path)

            # Invalidate query cache
            self.clear_cache()
            return True
