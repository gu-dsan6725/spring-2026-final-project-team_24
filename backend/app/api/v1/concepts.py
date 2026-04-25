"""Concept CRUD and search — knowledge nodes (markdown, video, audio).

Endpoints:
- CRUD: create, read, update, delete concepts in personal graph.
- Search: "does this idea exist in my group?" — fan-out similarity
  search across landscape + all member embeddings with two-stage
  verification. Returns canonical matches and convergence signals
  (member counts only — no raw content from other users).
"""

from fastapi import APIRouter

router = APIRouter()


# POST /api/v1/concepts/search
# Body: ConceptSearchRequest (query text or draft content, group_id)
# Returns: ConceptSearchResponse (canonical matches, convergence signals,
#          related-but-distinct flags)
