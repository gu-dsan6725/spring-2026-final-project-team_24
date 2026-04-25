"""Item pool — search-first retrieval and reference item selection.

This is the FIRST step in the item pipeline, before any generation
happens. The user selects concepts + edges + optional example items
and the pool answers: "do suitable items already exist?"

Search-first flow (called by item_service):
1. User's selected foundation concepts are embedded.
2. Pinecone query against existing items in the group's item pool,
   searching by foundation concept overlap.
3. If matching items are found → return them directly. No generation
   needed. The user gets existing items immediately.
4. If no suitable matches → proceed to feasibility_check →
   item_construction (generation).

Ranking:
- Exact match on all selected concepts > partial overlap > related
  via traversal edges.
- Filter by item type (problem, definition, flashcard, code challenge)
  to match the user's requested type.

Reference selection (for generation):
When generation IS triggered, this module also selects a curated set
of N existing items as few-shot examples for the tool-calling context
in item_construction. These are injected via build_example_item_view()
as synthetic tool-call results.

Also serves the user-facing item search endpoint (app.api.v1.items).
"""
