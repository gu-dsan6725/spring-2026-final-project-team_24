"""Concept CRUD + personal graph operations.

Responsibilities:
- Create/read/update/delete concepts in user's personal graph (MongoDB).
- Trigger embedding on write (event → vector pipeline).
- Content type handling (markdown, video URL, audio reference).
"""
