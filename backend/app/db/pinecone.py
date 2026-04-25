"""Pinecone vector store client.

Stores ONLY vector embeddings + lightweight metadata (user_id, concept_id,
group_id). Raw text content is NEVER stored in Pinecone — it lives in
MongoDB. This separation is what preserves privacy in cross-user searches.

Namespace patterns:
- group_{id}_landscape  — canonical node embeddings
- group_{id}_edges      — landscape edge body embeddings
- user_{id}_concepts    — personal concept note embeddings
- user_{id}_edges       — personal edge body embeddings

Single-namespace queries:
- query(vector, namespace, top_k) — standard similarity search.

Fan-out queries (search across multiple namespaces for a group):
- group_concept_search(group_id, vector, top_k)
    Searches group_{id}_landscape + user_{member}_concepts for every
    member of the group. Returns merged, deduplicated candidate list.
    Used by: concept_search_service, merge_service (meta-curator).

- group_edge_search(group_id, vector, top_k)
    Searches group_{id}_edges + user_{member}_edges for every member.
    Used by: edge_service (dedup), connection_inference pipeline.

Fan-out queries resolve group membership via group_service to build
the namespace list dynamically. Results are passed to
similarity_verifier for Stage 2 LLM confirmation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable

from pinecone import Pinecone

from app.config import settings

logger = logging.getLogger(__name__)

# Must match the embedding model dimension (see app/ai/providers/openai_embeddings.py).
DEFAULT_VECTOR_DIMENSION = 1536


def namespace_user_concepts(user_id: str) -> str:
    return f"user_{user_id}_concepts"


def namespace_user_edges(user_id: str) -> str:
    return f"user_{user_id}_edges"


def namespace_user_docs(user_id: str) -> str:
    """Paper-chunk embeddings (multi-vector per section).

    Ids inside this namespace follow ``doc_{doc_id}::{section_id}::c{idx}``.
    """
    return f"user_{user_id}_docs"


def namespace_group_landscape(group_id: str) -> str:
    return f"group_{group_id}_landscape"


def namespace_group_edges(group_id: str) -> str:
    return f"group_{group_id}_edges"


def pinecone_configured() -> bool:
    return bool(settings.PINECONE_API_KEY.strip() and settings.PINECONE_INDEX.strip())


def _client() -> Pinecone:
    if not pinecone_configured():
        raise RuntimeError(
            "Pinecone is not configured. Set PINECONE_API_KEY and PINECONE_INDEX in the environment."
        )
    return Pinecone(api_key=settings.PINECONE_API_KEY)


def get_index():
    """Return a handle to the configured dense index (sync API)."""
    pc = _client()
    return pc.Index(settings.PINECONE_INDEX)


@dataclass(frozen=True)
class VectorMatch:
    """One similarity hit from Pinecone."""

    id: str
    score: float
    metadata: dict[str, Any]


def merge_matches_by_id(matches: Iterable[VectorMatch], *, top_k: int) -> list[VectorMatch]:
    """Keep the highest score per vector id, then sort by score descending."""
    best: dict[str, VectorMatch] = {}
    for m in matches:
        prev = best.get(m.id)
        if prev is None or m.score > prev.score:
            best[m.id] = m
    ranked = sorted(best.values(), key=lambda x: x.score, reverse=True)
    return ranked[:top_k]


def query_namespace(
    *,
    vector: list[float],
    namespace: str,
    top_k: int,
    include_metadata: bool = True,
) -> list[VectorMatch]:
    index = get_index()
    resp = index.query(
        vector=vector,
        top_k=top_k,
        namespace=namespace,
        include_metadata=include_metadata,
    )
    matches = getattr(resp, "matches", None) or []
    out: list[VectorMatch] = []
    for m in matches:
        meta = getattr(m, "metadata", None) or {}
        if not isinstance(meta, dict):
            meta = dict(meta) if meta else {}
        out.append(
            VectorMatch(
                id=str(getattr(m, "id", "")),
                score=float(getattr(m, "score", 0.0)),
                metadata=meta,
            )
        )
    return out


def query_namespaces_merged(
    *,
    vector: list[float],
    namespaces: list[str],
    top_k: int,
    per_namespace_top_k: int | None = None,
    include_metadata: bool = True,
) -> list[VectorMatch]:
    """Query each namespace with the same vector; merge by id; return global top_k."""
    cap = per_namespace_top_k or max(top_k, 10)
    combined: list[VectorMatch] = []
    for ns in namespaces:
        if not ns:
            continue
        try:
            combined.extend(
                query_namespace(
                    vector=vector,
                    namespace=ns,
                    top_k=cap,
                    include_metadata=include_metadata,
                )
            )
        except Exception:
            logger.exception("Pinecone query failed for namespace %s", ns)
            raise
    return merge_matches_by_id(combined, top_k=top_k)


def upsert_tuples(
    *,
    namespace: str,
    vectors: list[tuple[str, list[float], dict[str, Any]]],
    batch_size: int = 96,
) -> None:
    """Upsert (id, values, metadata) tuples. SDK batches when ``batch_size`` is set."""
    if not vectors:
        return
    index = get_index()
    index.upsert(vectors=vectors, namespace=namespace, batch_size=batch_size)


def delete_ids(*, namespace: str, ids: list[str]) -> None:
    if not ids:
        return
    index = get_index()
    index.delete(ids=ids, namespace=namespace)


def delete_namespace_all(*, namespace: str) -> None:
    """Delete all vectors in a namespace."""
    index = get_index()
    index.delete(delete_all=True, namespace=namespace)
