"""Grader pipeline — evaluate user learning progress and direct next round.

Runs after the user completes a round of items.  Evaluates:
  - Per-concept mastery delta (how much the user improved)
  - Whether the user's stated requirements have been met
  - Recommended next difficulty level
  - Whether the session should continue or stop

All prior rounds are provided as context.  The Grader's summary is
injected as tool-call context into the next Generator round.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.ai.jsonutil import load_llm_json
from app.schemas.item import Difficulty, GraderSummary, RoundResult

logger = logging.getLogger(__name__)

GRADER_SYSTEM_PROMPT = (
    "You are a learning progress evaluator. You will see:\n"
    "1. The foundation concepts with the user's mastery scores.\n"
    "2. All rounds so far: items generated, the user's performance context.\n"
    "3. The user's stated learning requirements.\n\n"
    "Evaluate:\n"
    "- How much the user has progressed on each foundation concept (mastery_delta, "
    "estimated change from -0.2 to +0.3 per concept).\n"
    "- A learning summary (2-3 sentences).\n"
    "- Whether the user's requirements have been met.\n"
    "- Recommended next difficulty: easy, medium, or hard.\n"
    "- A recommendation: continue with harder items, review weak areas, or stop.\n\n"
    "Respond with JSON: {\"mastery_delta\": {\"concept_title\": delta, ...}, "
    "\"learning_summary\": \"...\", \"requirements_met\": true/false, "
    "\"next_difficulty\": \"easy\"|\"medium\"|\"hard\", \"recommendation\": \"...\"}"
)


def _build_grader_user_message(
    rounds: list[RoundResult],
    concept_docs: list[dict[str, Any]],
    user_requirements: str,
) -> str:
    payload: dict[str, Any] = {
        "foundation_concepts": [
            {
                "title": c.get("title", ""),
                "user_mastery": c.get("user_mastery", 0.5),
            }
            for c in concept_docs
        ],
        "rounds": [
            {
                "round_number": r.round_number,
                "items": [
                    {
                        "title": i.title,
                        "type": i.type,
                        "difficulty": i.difficulty,
                        "body_md": i.body_md[:200],
                    }
                    for i in r.items
                ],
                "actor_trajectories": [
                    {
                        "item_title": t.item_title,
                        "confidence": t.confidence,
                        "concepts_used": t.concepts_used,
                    }
                    for t in r.trajectories
                ],
                "reflector_feedback": [
                    {
                        "item_title": f.item_title,
                        "quality_score": f.quality_score,
                        "approved": f.approved,
                    }
                    for f in r.reflector_feedback
                ],
            }
            for r in rounds
        ],
        "user_requirements": user_requirements or "No specific requirements stated.",
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


async def grade(
    rounds: list[RoundResult],
    concept_docs: list[dict[str, Any]],
    user_requirements: str = "",
    *,
    provider: str | None = None,
) -> GraderSummary:
    """Evaluate learning progress across all rounds so far."""
    from app.ai.providers import chat_json_completion

    user_msg = _build_grader_user_message(rounds, concept_docs, user_requirements)

    raw = await chat_json_completion(
        system=GRADER_SYSTEM_PROMPT,
        user=user_msg,
        provider=provider,
    )

    parsed = load_llm_json(raw)
    if not parsed:
        logger.warning("Grader returned unparseable response; using defaults")
        return GraderSummary(
            round_number=len(rounds),
            learning_summary="Unable to evaluate progress.",
            next_difficulty=Difficulty.MEDIUM,
        )

    next_diff_raw = parsed.get("next_difficulty", "medium").lower()
    try:
        next_diff = Difficulty(next_diff_raw)
    except ValueError:
        next_diff = Difficulty.MEDIUM

    return GraderSummary(
        round_number=len(rounds),
        mastery_delta=parsed.get("mastery_delta", {}),
        learning_summary=parsed.get("learning_summary", ""),
        requirements_met=parsed.get("requirements_met", False),
        next_difficulty=next_diff,
        recommendation=parsed.get("recommendation", ""),
    )
