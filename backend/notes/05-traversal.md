# Traversal Engine

The traversal engine guides a user through the knowledge graph in an optimal learning order, personalized to what they already know.

## Knowledge Space Theory

Based on the framework introduced by Doignon & Falmagne (1985):

- **Knowledge domain Q** — all concept nodes in the traversal graph.
- **Knowledge state K** — the subset of Q that this user has mastered (confirmed via item completion or self-assessment).
- **Outer fringe** — concepts not in K whose prerequisite traversal edges are *all* satisfied (every prerequisite is in K). These are what the user is *ready to learn next*.

## Traversal Algorithm

```
Given: traversal DAG, user's knowledge state K

1. Compute outer_fringe = {c ∈ Q \ K : all prerequisites(c) ⊆ K}
2. Rank outer_fringe by:
   a. Downstream unlock count — how many new concepts become reachable
   b. Item enablement — how many items (hyperedges) become completable
   c. Memory curve urgency — spaced repetition schedule for review
   d. User preference / group priority
3. Present top-N candidates to user
4. User studies concept → completes associated item(s) → K is updated
5. Recompute outer_fringe → repeat until Q is covered
```

Traversal follows edge direction with no revisiting. If the graph contains disconnected components, the engine starts new chains from unvisited roots until the entire graph is covered.

## Foreign Content Resolution (Differential Import)

When a user consumes content from another user (foreign content), the system imports only what is **new** to the user, plus necessary prerequisites:

1. Chunk the foreign content by concept (heading or paragraph boundaries).
2. Embed each chunk.
3. Vector search against the user's existing note embeddings.
4. If similarity > threshold → **KNOWN** (skip — user already covers this).
5. If similarity < threshold → **NEW** (include).
6. For each NEW concept, walk its prerequisites:
   - If a prerequisite is KNOWN, link the new concept to the user's existing note.
   - If a prerequisite is also NEW, include it in the import set.
7. Result: a **minimal subgraph** that fills the gaps in the user's knowledge without re-presenting what they already know.

Complexity: O(n log m) with vector DB indexing, where n = foreign concepts, m = user's notes.

> *[Detailed design deferred]* — Chunking granularity strategy, similarity threshold tuning, handling partial matches (user knows 70% of a concept), and UX for reviewing the import set.
