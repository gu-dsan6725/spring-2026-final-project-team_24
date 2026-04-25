"""Feasibility check — domain and difficulty classifier for item generation.

Runs BEFORE item_construction to decide whether generation should proceed.
Uses a lightweight LLM call to classify the domain/complexity.

Three outcomes:
  ABANDON            — high-complexity formal domains (e.g., IMO proofs)
  GENERATE_WITH_REVIEW — standard academic domains (undergrad math, CS)
  GENERATE           — knowledge-recall / application domains
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.ai.jsonutil import load_llm_json
from app.schemas.item import FeasibilityOutcome

logger = logging.getLogger(__name__)

FEASIBILITY_SYSTEM_PROMPT = (
    "You are a domain classifier for an educational item generator. "
    "Given a set of foundation concepts and a requested item type, "
    "classify whether AI generation is appropriate.\n\n"
    "Respond with JSON: {\"outcome\": \"ABANDON\" | \"GENERATE_WITH_REVIEW\" | \"GENERATE\", "
    "\"reason\": \"...\"}\n\n"
    "Rules:\n"
    "- ABANDON: high-complexity formal domains where LLM output is unreliable "
    "(e.g., IMO-level proofs, novel theorem construction, advanced olympiad math). "
    "Message: 'This combination requires expert-authored items.'\n"
    "- GENERATE_WITH_REVIEW: standard academic domains (undergrad math, statistics, "
    "CS, engineering). Items need review before acceptance.\n"
    "- GENERATE: knowledge-recall and application domains (medical, law, history, "
    "language learning, definitions, case studies). Well-suited to LLM generation."
)


async def check(
    concept_docs: list[dict[str, Any]],
    requested_type: str,
    user_requirements: str = "",
    *,
    provider: str | None = None,
) -> tuple[FeasibilityOutcome, str]:
    """Classify whether item generation should proceed.

    Returns ``(outcome, reason)`` tuple.
    """
    from app.ai.providers import chat_json_completion

    user_msg = json.dumps({
        "concepts": [
            {
                "title": c.get("title", ""),
                "content_type": c.get("content_type", "markdown"),
                "content_preview": (c.get("body_md") or c.get("content_md", ""))[:200],
            }
            for c in concept_docs
        ],
        "requested_item_type": requested_type,
        "user_requirements": user_requirements or "none",
    }, ensure_ascii=False, default=str)

    raw = await chat_json_completion(
        system=FEASIBILITY_SYSTEM_PROMPT,
        user=user_msg,
        provider=provider,
    )

    parsed = load_llm_json(raw)
    if not parsed:
        logger.warning("Feasibility check returned unparseable response; defaulting to GENERATE_WITH_REVIEW")
        return FeasibilityOutcome.GENERATE_WITH_REVIEW, "Could not classify domain."

    outcome_raw = parsed.get("outcome", "GENERATE_WITH_REVIEW").upper()
    reason = parsed.get("reason", "")

    try:
        outcome = FeasibilityOutcome(outcome_raw)
    except ValueError:
        logger.warning("Unknown feasibility outcome %r; defaulting to GENERATE_WITH_REVIEW", outcome_raw)
        outcome = FeasibilityOutcome.GENERATE_WITH_REVIEW

    return outcome, reason
