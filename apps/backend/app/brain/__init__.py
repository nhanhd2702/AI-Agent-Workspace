"""Brain module for Document Ingestion, ChromaDB Vector RAG, and Semantic Search."""

from app.brain.catalog import CatalogService, STARTER_BRAND_TEMPLATES
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
    "CatalogService",
    "ChunkHit",
    "DocumentIngestor",
    "DocumentParsingError",
    "IngestResult",
    "STARTER_BRAND_TEMPLATES",
    "ScannedPdfError",
    "UnsupportedFormatError",
    "chunk_text",
    "normalize_collection_name",
]
