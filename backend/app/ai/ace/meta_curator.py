"""ACE Meta-Curator — group landscape gatekeeper.

Operates as a "gated push" from personal graphs to the canonical landscape,
analogous to a merge gatekeeper in version control.

Responsibilities:
- Receive candidate concepts from personal graphs.
- Run two-stage similarity verification (embedding + local LLM) against
  the landscape AND all group members' personal embeddings.
- Three-band routing based on verified similarity:
    > 0.85  — delta-update existing canonical node ($push perspective).
    0.70-0.85 — soft match, flag for discussion (no merge).
    < 0.70  — check other members for first convergence; create new
              canonical node if k members agree.
- Enforce convergence threshold k (configurable per group).
- Admin override: force-promote or force-exclude regardless of convergence.
- Synthesize canonical node content when merging multiple perspectives.

Consumes events from the event bus (concept writes, edge writes, forks).
Uses app.ai.providers.similarity_verifier for two-stage verification.
"""
