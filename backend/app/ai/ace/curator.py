"""ACE Curator — personal knowledge pool manager.

Adapted from: vendor/ace/ace/core/curator.py

Manages each user's personal graph through the ACE feedback loop:
- Embed-on-write: when a user creates or updates a concept, trigger
  embedding pipeline and index into Pinecone (user_{id}_concepts).
- Personal dedup detection: flag when a user's new note is similar to
  one they already have ("you already wrote about this — combine?").
- Quality signals: track which concepts have edges, items, and activity
  vs. orphaned/stale notes.
- Per-user playbook maintenance: update the user-tier playbook based on
  Reflector feedback (e.g., "this user prefers formal notation").

Uses app.ai.providers.similarity_verifier for two-stage dedup checks.
Consumes events from app.events.bus (concept_created, concept_updated).
"""
