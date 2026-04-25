# Merging & Landscape Canonical Nodes

When multiple users in a group write about the same concept (e.g., "Bayes Theorem" in different words), the group landscape merges them into a single **canonical node**. Merging is driven by ACE's Curator via delta updates — not batch recomputation.

## Event-Driven Merge Pipeline

Every user write (new concept, concept update, new edge) triggers a vector search as a side effect:

1. User writes a concept note → stored in MongoDB (personal graph) → embedded → indexed in Pinecone (`user_{id}_concepts` namespace).
2. **Pinecone search** against the group landscape namespace (`group_{id}_landscape`) for similar canonical nodes.
3. Three outcomes based on similarity:

| Similarity | Action |
|---|---|
| **> 0.85** (merge threshold) | ACE Curator delta-updates the existing canonical node: `$push` new perspective, `$addToSet` any new edges. No rewrite. |
| **0.70–0.85** (soft match) | No merge. Flag for **discussion recommendation** (future feature): "User A and User C both wrote about stability but have different takes — suggest they compare notes?" |
| **< 0.70** | Different concept. Search other members' personal notes in the group. If a member's note matches (> 0.85), this is **first convergence** — ACE Generator creates a new canonical node from the two perspectives. If no match, note stays in personal graph only. |

4. For edge writes: Pinecone search against `user_{id}_edges` (personal dedup — "you already have a similar connection") and `group_{id}_edges` (landscape — "this edge exists from another member, add your perspective?").

## Canonical Node Structure (MongoDB Document)

```json
{
  "canonical_id": "cn_bayes_theorem",
  "merged_title": "Bayes Theorem",
  "perspectives": [
    {"user_id": "u_alice", "note_id": "n_042", "similarity": 0.93},
    {"user_id": "u_bob",   "note_id": "n_108", "similarity": 0.88}
  ],
  "edges_out": ["cn_naive_bayes", "cn_medical_diagnosis"],
  "edges_in": ["cn_probability_axioms"],
  "item_ids": ["item_023", "item_045"],
  "created_at": "2026-03-10",
  "last_updated": "2026-03-27"
}
```

When User C writes a similar note → delta update: `$push` to `perspectives`, `$addToSet` to `edges_out` if C's note introduces a new connection. The document grows incrementally — early perspectives are never lost.

## Convergence Threshold

The minimum-members threshold `k` for creating a canonical node is configurable per group:

| Setting | Effect |
|---|---|
| `k = 2` | Loose — any two members agreeing surfaces it. Good for small groups. |
| `k = 3` | Moderate — needs broader agreement. Good for medium classes. |
| `k = majority` | Strict — only consensus topics enter the landscape. |
| Admin override | Professor can force-promote or force-exclude specific notes regardless of convergence. |

A single user's rare/niche note never enters the landscape — it stays in their personal graph until convergence happens or an admin promotes it. This prevents rare ideas from polluting the group's shared topic structure.

## Design Principles

- Merging is **visual and navigational only** — personal graphs are never modified.
- In the landscape, users see one node. Clicking it reveals the perspectives panel — each user's original take, side by side.
- Edges from all perspectives are combined: if User A says "Bayes → Naive Bayes" and User B says "Bayes → Medical Diagnosis," both edges appear on the canonical node.
- All updates are **incremental deltas**, not full recomputation — preserving the history of how the canonical node evolved.
