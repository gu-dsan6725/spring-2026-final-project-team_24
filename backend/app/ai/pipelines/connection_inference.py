# Adapted from: vendor/yubo/app/services/semantic_pairing.py
#               vendor/yubo/app/services/llm_edge_refiner.py
"""Connection inference — auto-generate relationship edges.

Two-stage pipeline:
1. **Cosine similarity** over concept embeddings → top-K candidate pairs.
2. **LLM refinement** (optional) — classify each pair into a relation type
   and generate a human-readable label.

The pipeline operates on plain dicts (concept docs from MongoDB) rather than
ORM models, keeping it decoupled from the storage layer.
"""

from __future__ import annotations

import logging
from typing import Any, TypedDict

import numpy as np

from app.ai.jsonutil import load_llm_json
from app.ai.providers import chat_available, chat_json_completion

logger = logging.getLogger(__name__)

VALID_RELATIONS = frozenset(
    {
        "similarity",
        "insight",
        "application",
        "dependency",
        "prerequisite",
        "contrast",
        "analogy",
        "derivation",
        "reference",
        "extends",
        "custom",
    },
)


class InferredEdge(TypedDict):
    source_id: str
    target_id: str
    relation: str
    label: str
    confidence: float


# ---------------------------------------------------------------------------
# Stage 1: cosine similarity pairing
# ---------------------------------------------------------------------------


def select_semantic_pairs(
    embeddings: list[list[float]],
    threshold: float = 0.75,
    top_k_per_concept: int = 3,
) -> list[tuple[int, int, float]]:
    """Pick unique undirected pairs ``(a, b, score)`` with ``a < b``."""
    if not embeddings:
        return []

    n = len(embeddings)
    mat = np.asarray(embeddings, dtype=np.float64)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    unit = mat / norms
    sim = unit @ unit.T

    seen: set[tuple[int, int]] = set()
    chosen: list[tuple[int, int, float]] = []

    for i in range(n):
        row = sim[i].copy()
        row[i] = -1.0
        order = np.argsort(-row)
        taken = 0
        for j_idx in order:
            j = int(j_idx)
            if j == i:
                continue
            score = float(row[j])
            if score < threshold:
                break
            a, b = (i, j) if i < j else (j, i)
            if (a, b) in seen:
                continue
            seen.add((a, b))
            chosen.append((a, b, float(sim[a, b])))
            taken += 1
            if taken >= top_k_per_concept:
                break

    return chosen


# ---------------------------------------------------------------------------
# Stage 2: LLM edge refinement
# ---------------------------------------------------------------------------


def _snippet(concept: dict[str, Any], max_chars: int = 400) -> str:
    title = concept.get("title", "Untitled")
    body = (concept.get("body", "") or "")[:max_chars]
    return f"{title}\n{body}".strip()


async def refine_pairs_with_llm(
    snippets: list[tuple[str, str]],
    *,
    provider: str | None = None,
) -> list[tuple[str, str]]:
    """Return ``(relation, label)`` per pair, same order as *snippets*.

    Falls back to ``("similarity", "semantic_cosine")`` on any failure.
    """
    fallback = [("similarity", "semantic_cosine")] * len(snippets)
    if not snippets:
        return []

    prov = provider or "openai"
    if not chat_available(prov):
        return fallback

    blocks: list[str] = []
    for k, (a, b) in enumerate(snippets):
        blocks.append(f"--- Pair {k} ---\nText A:\n{a}\n\nText B:\n{b}\n")

    system = (
        "You label conceptual links between text pairs for a knowledge graph. "
        "For each pair, choose relation as EXACTLY one of: "
        "similarity, dependency, prerequisite, contrast, insight, application, "
        "analogy, derivation, reference, extends, custom. "
        "Also give a short English label (max 80 characters). "
        'Return JSON only: {"results": [{"relation": "...", "label": "..."}, ...]}. '
        "The results array MUST have the same length and order as the pairs (0..N-1)."
    )

    try:
        raw = await chat_json_completion(
            system=system,
            user="\n".join(blocks),
            provider=prov,
        )
    except Exception:
        logger.exception("LLM chat provider failed during edge refine")
        return fallback

    data = load_llm_json(raw)
    if data is None:
        return fallback

    results = data.get("results")
    if not isinstance(results, list):
        return fallback

    out: list[tuple[str, str]] = []
    for item in results:
        if isinstance(item, dict):
            rel = str(item.get("relation", "similarity")).strip()
            lbl = str(item.get("label", "semantic_cosine")).strip()[:255]
            if rel not in VALID_RELATIONS:
                rel = "similarity"
            out.append((rel, lbl or "semantic_cosine"))
        else:
            out.append(("similarity", "semantic_cosine"))

    while len(out) < len(snippets):
        out.append(("similarity", "semantic_cosine"))
    return out[: len(snippets)]


# ---------------------------------------------------------------------------
# Combined pipeline
# ---------------------------------------------------------------------------


async def infer_edges(
    concepts: list[dict[str, Any]],
    embeddings: list[list[float]],
    *,
    threshold: float = 0.75,
    top_k: int = 3,
    llm_refine: bool = True,
    provider: str | None = None,
) -> list[InferredEdge]:
    """Full pipeline: cosine pairing → optional LLM refinement → edge dicts."""
    pairs = select_semantic_pairs(embeddings, threshold=threshold, top_k_per_concept=top_k)
    if not pairs:
        return []

    snippets = [
        (_snippet(concepts[a]), _snippet(concepts[b]))
        for a, b, _ in pairs
    ]

    refined: list[tuple[str, str]] | None = None
    if llm_refine:
        try:
            refined = await refine_pairs_with_llm(snippets, provider=provider)
        except Exception:
            logger.exception("LLM edge refine failed; using cosine defaults")

    edges: list[InferredEdge] = []
    for idx, (a, b, score) in enumerate(pairs):
        relation = "similarity"
        label = "semantic_cosine"
        if refined and idx < len(refined):
            r, lbl = refined[idx]
            if r in VALID_RELATIONS:
                relation = r
            label = (lbl or label)[:255]
        edges.append(
            InferredEdge(
                source_id=concepts[a].get("_id", ""),
                target_id=concepts[b].get("_id", ""),
                relation=relation,
                label=label,
                confidence=max(0.0, min(1.0, score)),
            ),
        )
    return edges
