"""Brain module for Document Ingestion, ChromaDB Vector RAG, and Semantic Search."""

from app.brain.ingest import (
    BRAIN_MANIFEST_LOCK,
    DocumentIngestor,
    DocumentParsingError,
    IngestResult,
    ScannedPdfError,
    UnsupportedFormatError,
    chunk_text,
    normalize_collection_name,
)
from app.brain.retriever import BrainRetriever, ChunkHit

__all__ = [
    "BRAIN_MANIFEST_LOCK",
    "BrainRetriever",
    "ChunkHit",
    "DocumentIngestor",
    "DocumentParsingError",
    "IngestResult",
    "ScannedPdfError",
    "UnsupportedFormatError",
    "chunk_text",
    "normalize_collection_name",
]
