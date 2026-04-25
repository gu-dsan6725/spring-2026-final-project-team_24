"""Request/response models for vector index and similarity search."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ConceptIndexEntry(BaseModel):
    concept_id: str = Field(..., min_length=1, max_length=512)
    text: str = Field(..., min_length=1)
    # Optional: lets the Obsidian client map hits back to vault files without scanning.
    vault_path: str | None = Field(default=None, max_length=2048)
    title: str | None = Field(default=None, max_length=512)


class BatchIndexConceptsRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=256)
    entries: list[ConceptIndexEntry] = Field(..., min_length=1, max_length=500)


class BatchIndexConceptsResponse(BaseModel):
    indexed: int
    namespace: str


class ConceptSearchRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=256)
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=10, ge=1, le=100)


class ConceptSearchHit(BaseModel):
    concept_id: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConceptSearchResponse(BaseModel):
    hits: list[ConceptSearchHit]
    namespace: str


class MultiNamespaceSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    namespaces: list[str] = Field(..., min_length=1, max_length=64)
    top_k: int = Field(default=10, ge=1, le=100)
    per_namespace_top_k: int | None = Field(default=None, ge=1, le=100)


class MultiNamespaceSearchResponse(BaseModel):
    hits: list[ConceptSearchHit]


class ClearNamespaceRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=256)


class ClearNamespaceResponse(BaseModel):
    namespace: str
    cleared: bool = True


# ---------------------------------------------------------------------------
# Document / paper chunk indexing (multi-vector per section)
# ---------------------------------------------------------------------------


class DocChunkIndexEntry(BaseModel):
    """One sub-chunk of a paper section, ready to embed and upsert.

    Vector id at upsert time is ``doc_{doc_id}::{section_id}::c{chunk_index}``.
    Raw chunk text is NOT stored in Pinecone metadata (privacy); callers should
    keep it on disk in the paper's ``.meta/`` sidecar JSON.
    """

    doc_id: str = Field(..., min_length=1, max_length=256)
    section_id: str = Field(..., min_length=1, max_length=128)
    chunk_index: int = Field(..., ge=0)
    text: str = Field(..., min_length=1)
    section_title: str | None = Field(default=None, max_length=512)
    vault_path: str | None = Field(default=None, max_length=2048)


class BatchIndexDocChunksRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=256)
    entries: list[DocChunkIndexEntry] = Field(..., min_length=1, max_length=2000)


class BatchIndexDocChunksResponse(BaseModel):
    indexed: int
    namespace: str


class DocChunkSearchRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=256)
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=10, ge=1, le=100)


class DocChunkSearchHit(BaseModel):
    vector_id: str
    doc_id: str | None = None
    section_id: str | None = None
    chunk_index: int | None = None
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocChunkSearchResponse(BaseModel):
    hits: list[DocChunkSearchHit]
    namespace: str


class IngestPaperRequest(BaseModel):
    """Full paper-ingestion request (extract → split → chunk → embed → optionally export)."""

    user_id: str = Field(..., min_length=1, max_length=256)
    pdf_base64: str = Field(..., min_length=1)
    filename: str = Field(default="paper.pdf", min_length=1, max_length=512)
    # If set, mirror the finished paper folder here (e.g. Obsidian vault path).
    # Falls back to settings.PAPER_EXPORT_DIR when omitted.
    export_path: str | None = Field(default=None, max_length=4096)
    # Force re-ingest even if a prior paper.json with matching doc_id already exists.
    force: bool = False


class IngestPaperSectionSummary(BaseModel):
    section_id: str
    order: int
    title: str
    filename: str
    image_refs: list[str] = Field(default_factory=list)
    chunk_count: int


class IngestPaperResponse(BaseModel):
    doc_id: str
    stem: str
    paper_dir: str
    section_count: int
    chunk_count: int
    sections: list[IngestPaperSectionSummary]
    pinecone_namespace: str | None = None
    pinecone_indexed: int = 0
    exported_to: str | None = None
    already_ingested: bool = False
