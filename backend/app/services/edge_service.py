# Lexical overlap logic adapted from: vendor/yubo/app/services/lexical_edges.py
"""Edge CRUD and auto-generation for relationship and traversal edges.

Responsibilities:
- Relationship edges: typed, directional, with markdown body.
- Traversal edges: DAG-only prerequisite links with cycle detection.
- Trigger dedup check on write (event → vector pipeline).
- Lexical overlap edges: cheap token-bag Jaccard similarity (no embeddings).
"""

from __future__ import annotations

import re
from typing import Any

_TOKEN_RE = re.compile(r"[\w']+", re.UNICODE)


# ---------------------------------------------------------------------------
# Lexical overlap edge generation
# ---------------------------------------------------------------------------


def _token_set(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "") if len(t) > 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _pair_key(id_a: str, id_b: str) -> tuple[str, str]:
    return (id_a, id_b) if id_a <= id_b else (id_b, id_a)


def build_lexical_overlap_edges(
    concepts: list[dict[str, Any]],
    *,
    top_k_per_concept: int = 3,
    min_jaccard: float = 0.15,
    existing_pairs: set[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Cheap cross-links from token overlap (no embeddings needed).

    Each concept dict must have ``"_id"``, ``"title"``, and optionally ``"body"``.
    Returns edge dicts ready for MongoDB insertion.
    """
    if len(concepts) < 2:
        return []

    bags = [
        _token_set(f"{c.get('title', '')}\n{c.get('body', '')}")
        for c in concepts
    ]

    local_seen: set[tuple[str, str]] = set(existing_pairs or set())
    out: list[dict[str, Any]] = []

    for i, ci in enumerate(concepts):
        scores: list[tuple[int, float]] = []
        for j in range(len(concepts)):
            if i == j:
                continue
            s = _jaccard(bags[i], bags[j])
            if s < min_jaccard:
                continue
            scores.append((j, s))
        scores.sort(key=lambda x: -x[1])

        taken = 0
        for j, score in scores:
            if taken >= top_k_per_concept:
                break
            cj = concepts[j]
            pk = _pair_key(str(ci["_id"]), str(cj["_id"]))
            if pk in local_seen:
                continue
            local_seen.add(pk)
            out.append(
                {
                    "source_id": str(ci["_id"]),
                    "target_id": str(cj["_id"]),
                    "source": "ai",
                    "relation": "similarity",
                    "label": "lexical_overlap",
                    "confidence": min(1.0, max(0.0, score)),
                },
            )
            taken += 1

    return out
