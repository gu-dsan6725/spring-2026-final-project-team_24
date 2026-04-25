"""Concept schemas — create, update, read, list, search.

Search schemas for the "does this idea exist?" flow:

ConceptSearchRequest:
  - query: str — free-text query or draft content to search for.
  - group_id: str — group to search within.
  - top_k: int = 10 — max candidates from Stage 1 vector search.

ConceptSearchResponse:
  - canonical_matches: list — canonical nodes that match (public).
  - convergence_signals: list — each with:
      similar_member_count: int — how many distinct members have this idea.
      meets_threshold: bool — whether count >= group's convergence k.
      (NO content, NO user IDs — count only.)
  - related_but_different: list — concepts the LLM classified as
      SIMILAR_BUT_DIFFERENT (potential connection edge suggestions).
"""
