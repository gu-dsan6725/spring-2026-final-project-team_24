"""Landscape merge engine — canonical node creation and delta updates.

Driven by the Meta-Curator (app.ai.ace.meta_curator). This service
implements the "gated push" from personal graphs to the canonical
landscape.

Pipeline (triggered on every concept/edge write event):
1. Embed the new/updated content via embedding_pipeline.
2. Fan-out Pinecone search: group_{id}_landscape + all member namespaces
   (via app.db.pinecone.group_concept_search).
3. Two-stage verification (via app.ai.providers.similarity_verifier):
   - Stage 1: cosine similarity candidates from Pinecone.
   - Stage 2: local LLM confirms SAME / SIMILAR_BUT_DIFFERENT / UNRELATED.
4. Three-band routing on VERIFIED matches only:
   > 0.85  — delta-update existing canonical node:
             $push new perspective, $addToSet any new edges.
   0.70-0.85 — soft match, flag for discussion recommendation.
   < 0.70  — check other members for first convergence:
             if k members converge → create new canonical node.
             otherwise → stays in personal graph only.
5. Convergence threshold k enforcement (configurable per group).
6. Admin override: force-promote or force-exclude regardless of convergence.

Privacy: the merge service reads member content internally for Stage 2
verification but canonical nodes only expose perspectives (user_id,
note_id, similarity) — never the full content of another user's note.

Dependencies:
- app.ai.providers.similarity_verifier (two-stage check)
- app.ai.ace.meta_curator (orchestration and playbook-guided decisions)
- app.db.pinecone (fan-out search)
- app.db.mongo (canonical node CRUD, delta updates)
- app.events.bus (consumes write events)
"""
