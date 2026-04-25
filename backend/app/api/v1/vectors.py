"""Vector index and similarity search (Pinecone + OpenAI embeddings).

These endpoints support the personal-graph workflow: index note summaries
then retrieve nearest concepts before item generation or merge pipelines.
Auth integration is deferred; callers should pass explicit ``user_id``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.ai.pipelines import embedding_pipeline
from app.db import pinecone as pinecone_db
from app.schemas.vectors import (
    BatchIndexConceptsRequest,
    BatchIndexConceptsResponse,
    BatchIndexDocChunksRequest,
    BatchIndexDocChunksResponse,
    ClearNamespaceRequest,
    ClearNamespaceResponse,
    ConceptSearchHit,
    ConceptSearchRequest,
    ConceptSearchResponse,
    DocChunkSearchHit,
    DocChunkSearchRequest,
    DocChunkSearchResponse,
    MultiNamespaceSearchRequest,
    MultiNamespaceSearchResponse,
)

router = APIRouter()


@router.post("/concepts/index", response_model=BatchIndexConceptsResponse)
async def index_concepts(body: BatchIndexConceptsRequest) -> BatchIndexConceptsResponse:
    """Embed and upsert personal concepts into ``user_{user_id}_concepts``."""
    try:
        n = await embedding_pipeline.index_user_concepts(body.user_id, body.entries)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    ns = pinecone_db.namespace_user_concepts(body.user_id)
    return BatchIndexConceptsResponse(indexed=n, namespace=ns)


@router.post("/concepts/search", response_model=ConceptSearchResponse)
async def search_concepts(body: ConceptSearchRequest) -> ConceptSearchResponse:
    """Semantic search within one user's concept namespace."""
    try:
        matches = await embedding_pipeline.search_user_concepts(
            body.user_id,
            body.query,
            top_k=body.top_k,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    ns = pinecone_db.namespace_user_concepts(body.user_id)
    hits = [
        ConceptSearchHit(
            concept_id=m.metadata.get("concept_id", m.id),
            score=m.score,
            metadata=dict(m.metadata),
        )
        for m in matches
    ]
    return ConceptSearchResponse(hits=hits, namespace=ns)


@router.post("/concepts/search-multi", response_model=MultiNamespaceSearchResponse)
async def search_concepts_multi(body: MultiNamespaceSearchRequest) -> MultiNamespaceSearchResponse:
    """Query several namespaces with one query embedding (group fan-out building block)."""
    try:
        matches = await embedding_pipeline.search_concepts_across_namespaces(
            body.query,
            body.namespaces,
            top_k=body.top_k,
            per_namespace_top_k=body.per_namespace_top_k,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    hits = [
        ConceptSearchHit(
            concept_id=m.metadata.get("concept_id", m.id),
            score=m.score,
            metadata=dict(m.metadata),
        )
        for m in matches
    ]
    return MultiNamespaceSearchResponse(hits=hits)


@router.post("/concepts/clear", response_model=ClearNamespaceResponse)
async def clear_concepts_namespace(body: ClearNamespaceRequest) -> ClearNamespaceResponse:
    """Delete all vectors in ``user_{user_id}_concepts``."""
    try:
        ns = await embedding_pipeline.clear_user_concepts_namespace(body.user_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return ClearNamespaceResponse(namespace=ns, cleared=True)


# ---------------------------------------------------------------------------
# Paper / document chunk endpoints (multi-vector per section)
# ---------------------------------------------------------------------------


@router.post("/docs/index", response_model=BatchIndexDocChunksResponse)
async def index_doc_chunks(body: BatchIndexDocChunksRequest) -> BatchIndexDocChunksResponse:
    """Embed and upsert paper sub-chunks into ``user_{user_id}_docs``."""
    try:
        n = await embedding_pipeline.index_user_doc_chunks(body.user_id, body.entries)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    ns = pinecone_db.namespace_user_docs(body.user_id)
    return BatchIndexDocChunksResponse(indexed=n, namespace=ns)


@router.post("/docs/search", response_model=DocChunkSearchResponse)
async def search_doc_chunks(body: DocChunkSearchRequest) -> DocChunkSearchResponse:
    """Semantic search within one user's paper-chunk namespace."""
    try:
        matches = await embedding_pipeline.search_user_doc_chunks(
            body.user_id,
            body.query,
            top_k=body.top_k,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    ns = pinecone_db.namespace_user_docs(body.user_id)
    hits = [
        DocChunkSearchHit(
            vector_id=m.id,
            doc_id=m.metadata.get("doc_id"),
            section_id=m.metadata.get("section_id"),
            chunk_index=m.metadata.get("chunk_index"),
            score=m.score,
            metadata=dict(m.metadata),
        )
        for m in matches
    ]
    return DocChunkSearchResponse(hits=hits, namespace=ns)


@router.post("/docs/clear", response_model=ClearNamespaceResponse)
async def clear_docs_namespace(body: ClearNamespaceRequest) -> ClearNamespaceResponse:
    """Delete all vectors in ``user_{user_id}_docs``."""
    try:
        ns = await embedding_pipeline.clear_user_docs_namespace(body.user_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return ClearNamespaceResponse(namespace=ns, cleared=True)
