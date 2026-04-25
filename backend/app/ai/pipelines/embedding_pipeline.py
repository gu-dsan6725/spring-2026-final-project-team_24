"""Embedding pipeline — embeds concepts and edges, indexes into Pinecone."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.ai.providers import openai_embeddings
from app.ai.providers.openai_embeddings import EMBEDDING_DIMENSIONS
from app.db import pinecone as pinecone_db
from app.db.pinecone import VectorMatch
from app.schemas.vectors import ConceptIndexEntry, DocChunkIndexEntry

logger = logging.getLogger(__name__)


def _require_pinecone() -> None:
    if not pinecone_db.pinecone_configured():
        raise RuntimeError(
            "Pinecone is not configured (set PINECONE_API_KEY and PINECONE_INDEX)."
        )


def _require_openai_embeddings() -> None:
    from app.config import settings

    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is required for embedding text.")


async def index_user_concepts(
    user_id: str,
    entries: list[ConceptIndexEntry],
    *,
    batch_size: int = 96,
) -> int:
    """Embed concept texts and upsert into ``user_{id}_concepts``.

    Vector id equals ``concept_id`` (unique per user namespace). Metadata
    holds ids plus optional ``vault_path`` / ``title`` for client mapping —
    never raw note bodies.
    """
    if not entries:
        return 0
    _require_pinecone()
    _require_openai_embeddings()

    texts = [e.text for e in entries]
    vectors = await openai_embeddings.embed_texts(texts)
    if len(vectors) != len(entries):
        raise RuntimeError("Embedding provider returned fewer vectors than inputs")

    ns = pinecone_db.namespace_user_concepts(user_id)
    tuples: list[tuple[str, list[float], dict[str, Any]]] = []
    for entry, vec in zip(entries, vectors):
        concept_id = entry.concept_id
        if len(vec) != EMBEDDING_DIMENSIONS:
            logger.warning(
                "Embedding dim %s for concept %s != expected %s",
                len(vec),
                concept_id,
                EMBEDDING_DIMENSIONS,
            )
        meta: dict[str, Any] = {"concept_id": concept_id, "user_id": user_id}
        if entry.vault_path:
            meta["vault_path"] = entry.vault_path
        if entry.title:
            meta["title"] = entry.title
        tuples.append((concept_id, vec, meta))

    await asyncio.to_thread(
        pinecone_db.upsert_tuples,
        namespace=ns,
        vectors=tuples,
        batch_size=batch_size,
    )
    return len(tuples)


async def search_user_concepts(
    user_id: str,
    query_text: str,
    *,
    top_k: int = 10,
) -> list[VectorMatch]:
    """Embed ``query_text`` and run similarity search in the user's concept namespace."""
    _require_pinecone()
    _require_openai_embeddings()
    if not query_text.strip():
        return []

    ns = pinecone_db.namespace_user_concepts(user_id)
    query_vec = (await openai_embeddings.embed_texts([query_text]))[0]

    return await asyncio.to_thread(
        pinecone_db.query_namespace,
        vector=query_vec,
        namespace=ns,
        top_k=top_k,
        include_metadata=True,
    )


async def search_concepts_across_namespaces(
    query_text: str,
    namespaces: list[str],
    *,
    top_k: int = 10,
    per_namespace_top_k: int | None = None,
) -> list[VectorMatch]:
    """Fan-out semantic search: same query embedding, merge hits across namespaces."""
    _require_pinecone()
    _require_openai_embeddings()
    if not query_text.strip() or not namespaces:
        return []

    query_vec = (await openai_embeddings.embed_texts([query_text]))[0]
    return await asyncio.to_thread(
        pinecone_db.query_namespaces_merged,
        vector=query_vec,
        namespaces=namespaces,
        top_k=top_k,
        per_namespace_top_k=per_namespace_top_k,
        include_metadata=True,
    )


async def delete_user_concept_vectors(user_id: str, concept_ids: list[str]) -> None:
    """Remove vectors by id from the user's concept namespace."""
    if not concept_ids:
        return
    _require_pinecone()
    ns = pinecone_db.namespace_user_concepts(user_id)
    await asyncio.to_thread(
        pinecone_db.delete_ids,
        namespace=ns,
        ids=concept_ids,
    )


async def clear_user_concepts_namespace(user_id: str) -> str:
    """Delete all vectors under ``user_{id}_concepts``."""
    _require_pinecone()
    ns = pinecone_db.namespace_user_concepts(user_id)
    await asyncio.to_thread(
        pinecone_db.delete_namespace_all,
        namespace=ns,
    )
    return ns


# ---------------------------------------------------------------------------
# Paper / document chunk indexing (multi-vector per section)
# ---------------------------------------------------------------------------


def _doc_chunk_vector_id(entry: DocChunkIndexEntry) -> str:
    return f"doc_{entry.doc_id}::{entry.section_id}::c{entry.chunk_index}"


async def embed_doc_chunks(entries: list[DocChunkIndexEntry]) -> list[list[float]]:
    """Embed chunk texts in input order. Does NOT touch Pinecone.

    Callers that want to persist vectors locally (e.g. ``.vectors.npy``) can
    use this directly and upsert via :func:`index_user_doc_chunks` separately.
    """
    if not entries:
        return []
    _require_openai_embeddings()
    texts = [e.text for e in entries]
    vectors = await openai_embeddings.embed_texts(texts)
    if len(vectors) != len(entries):
        raise RuntimeError("Embedding provider returned fewer vectors than inputs")
    return vectors


async def index_user_doc_chunks(
    user_id: str,
    entries: list[DocChunkIndexEntry],
    *,
    vectors: list[list[float]] | None = None,
    batch_size: int = 96,
) -> int:
    """Upsert paper sub-chunk vectors into ``user_{id}_docs``.

    If ``vectors`` is ``None``, the chunks are embedded here. If the caller
    has already embedded (e.g. to also save a local ``.npy`` copy), pass the
    vectors through to avoid paying OpenAI twice.

    Vector id: ``doc_{doc_id}::{section_id}::c{chunk_index}``. Metadata holds
    ids plus optional ``section_title`` / ``vault_path`` — never raw text.
    """
    if not entries:
        return 0
    _require_pinecone()

    if vectors is None:
        vectors = await embed_doc_chunks(entries)
    if len(vectors) != len(entries):
        raise RuntimeError(
            f"Vector count {len(vectors)} != entry count {len(entries)}"
        )

    ns = pinecone_db.namespace_user_docs(user_id)
    tuples: list[tuple[str, list[float], dict[str, Any]]] = []
    for entry, vec in zip(entries, vectors):
        vid = _doc_chunk_vector_id(entry)
        if len(vec) != EMBEDDING_DIMENSIONS:
            logger.warning(
                "Embedding dim %s for %s != expected %s",
                len(vec),
                vid,
                EMBEDDING_DIMENSIONS,
            )
        meta: dict[str, Any] = {
            "doc_id": entry.doc_id,
            "section_id": entry.section_id,
            "chunk_index": entry.chunk_index,
            "user_id": user_id,
        }
        if entry.section_title:
            meta["section_title"] = entry.section_title
        if entry.vault_path:
            meta["vault_path"] = entry.vault_path
        tuples.append((vid, list(vec), meta))

    await asyncio.to_thread(
        pinecone_db.upsert_tuples,
        namespace=ns,
        vectors=tuples,
        batch_size=batch_size,
    )
    return len(tuples)


async def search_user_doc_chunks(
    user_id: str,
    query_text: str,
    *,
    top_k: int = 10,
) -> list[VectorMatch]:
    """Embed ``query_text`` and run similarity search in ``user_{id}_docs``."""
    _require_pinecone()
    _require_openai_embeddings()
    if not query_text.strip():
        return []

    ns = pinecone_db.namespace_user_docs(user_id)
    query_vec = (await openai_embeddings.embed_texts([query_text]))[0]
    return await asyncio.to_thread(
        pinecone_db.query_namespace,
        vector=query_vec,
        namespace=ns,
        top_k=top_k,
        include_metadata=True,
    )


async def delete_user_doc_vectors(user_id: str, vector_ids: list[str]) -> None:
    if not vector_ids:
        return
    _require_pinecone()
    ns = pinecone_db.namespace_user_docs(user_id)
    await asyncio.to_thread(
        pinecone_db.delete_ids,
        namespace=ns,
        ids=vector_ids,
    )


async def clear_user_docs_namespace(user_id: str) -> str:
    """Delete all vectors under ``user_{id}_docs``."""
    _require_pinecone()
    ns = pinecone_db.namespace_user_docs(user_id)
    await asyncio.to_thread(
        pinecone_db.delete_namespace_all,
        namespace=ns,
    )
    return ns
