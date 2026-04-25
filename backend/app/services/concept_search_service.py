"""Concept search service — user-facing "does this idea exist?" flow.

Orchestrates the fetch/search workflow that lets a user check whether
a concept already exists in their group before writing from scratch.

Search flow:
1. Embed the user's query text or draft.
2. Fan-out Pinecone search across ALL group data:
   - group_{id}_landscape (canonical nodes — already group-public)
   - user_{member}_concepts for every member in the group
     (only vector embeddings stored — raw content never exposed)
3. Pass candidates through SimilarityVerifier (two-stage):
   - Stage 1: cosine similarity from Pinecone (already done).
   - Stage 2: local LLM reads query + candidate text, classifies as
     SAME / SIMILAR_BUT_DIFFERENT / UNRELATED.
4. Aggregate verified results:
   - Canonical node matches → return the node (already public).
   - Member note matches → count distinct users only.
     Privacy: no content, no user IDs — just "N members wrote about this."
   - Apply convergence threshold k:
     >= k → "This concept is close to becoming canonical."
     < k  → "Similar ideas exist (soft signal)."
     0    → "No prior art — proceed with new concept."
   - SIMILAR_BUT_DIFFERENT matches → "related but distinct concepts exist"
     (suggest connection edges, not merging).

Privacy invariant:
  This service NEVER returns another member's raw note content or identity.
  Pinecone stores only vectors + metadata (user_id, concept_id).
  Stage 2 LLM verification fetches text internally but the return value
  contains only: IDs, similarity scores, classification labels, and
  distinct-user counts.

Dependencies:
- app.ai.providers.similarity_verifier
- app.db.pinecone (fan-out query across namespaces)
- app.db.mongo (fetch candidate text for Stage 2, internal only)
- app.services.group_service (resolve group membership for namespace list)
"""
