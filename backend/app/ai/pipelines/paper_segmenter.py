"""Segment extracted paper markdown into concepts and directed edges via LLM."""

from __future__ import annotations

import json
import logging

from app.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are an expert knowledge-graph builder.  Given the markdown text of an
academic paper or technical document, extract the key concepts and the directed
relationships between them.

Return a **single JSON object** with exactly two keys:

{
  "concepts": [
    {
      "title": "Concept Name",
      "body_md": "A concise definition or explanation (1-3 paragraphs).",
      "content_type": "markdown"
    }
  ],
  "edges": [
    {
      "source_title": "Concept A",
      "target_title": "Concept B",
      "relationship_type": "prerequisite | derivation | application | reference | contrast | analogy",
      "note": "Brief explanation of why this edge exists."
    }
  ]
}

Guidelines:
- Extract 5-20 concepts depending on paper length; prefer quality over quantity.
- Each concept title should be a concise noun phrase.
- body_md should capture the essential definition/technique, not copy whole sections.
- Identify directed edges: prerequisite (A needed before B), derivation (B derived from A),
  application (B applies A), reference, contrast, analogy.
- Only output valid JSON. No markdown fences, no extra text.
"""


async def segment_paper(
    markdown: str,
    *,
    hint: str = "",
    provider: str | None = None,
) -> dict:
    """Send extracted paper markdown to LLM and return concepts + edges.

    Returns a dict with ``concepts`` and ``edges`` lists.
    """
    from app.ai.providers import chat_json_completion

    user_msg = markdown
    if hint:
        user_msg = f"[Hint from user: {hint}]\n\n{user_msg}"

    prov = provider or settings.ITEM_GENERATION_PROVIDER
    raw = await chat_json_completion(system=SYSTEM_PROMPT, user=user_msg, provider=prov)

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Paper segmenter returned invalid JSON: %s", raw[:500])
        return {"concepts": [], "edges": []}

    if "concepts" not in result:
        result["concepts"] = []
    if "edges" not in result:
        result["edges"] = []

    return result
