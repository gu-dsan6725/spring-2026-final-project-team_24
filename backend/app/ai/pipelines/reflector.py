"""Reflector pipeline — evaluate Actor trajectories against source content.

Compares each Actor's solution trajectory with the original concepts to
identify quality issues:
  - Items trivially solvable without foundation concepts
  - Answers that contradict the source content
  - Items that don't actually test the intended concepts
  - Misalignment with user requirements

Returns per-item feedback used to refine the next Generator round.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.ai.jsonutil import load_llm_json
from app.schemas.item import (
    ActorTrajectory,
    GeneratedItem,
    ReflectorFeedback,
)

logger = logging.getLogger(__name__)

REFLECTOR_SYSTEM_PROMPT = (
    "You are a quality evaluator for AI-generated study items. "
    "You will see:\n"
    "1. The original source concepts the items should test.\n"
    "2. The generated items.\n"
    "3. A simulated student's solution trajectories.\n\n"
    "Evaluate each item on:\n"
    "- Does the item genuinely test the foundation concepts?\n"
    "- Is the provided answer correct and consistent with the source?\n"
    "- Could the item be solved trivially without the concepts?\n"
    "- Does it match the user's stated requirements?\n\n"
    "Respond with a JSON object: {\"evaluations\": [{\"item_title\": ..., "
    "\"quality_score\": 0.0-1.0, \"issues\": [...], \"suggestions\": [...], "
    "\"approved\": true/false}, ...]}"
)


def _build_reflector_user_message(
    items: list[GeneratedItem],
    trajectories: list[ActorTrajectory],
    source_concepts: list[dict[str, Any]],
    user_requirements: str,
) -> str:
    """Assemble the evaluation context for the Reflector."""
    payload: dict[str, Any] = {
        "source_concepts": [
            {"title": c.get("title", ""), "content": c.get("body_md") or c.get("content_md", "")}
            for c in source_concepts
        ],
        "generated_items": [
            {
                "title": item.title,
                "type": item.type,
                "body_md": item.body_md,
                "answer_md": item.answer_md,
                "difficulty": item.difficulty,
            }
            for item in items
        ],
        "actor_trajectories": [
            {
                "item_title": t.item_title,
                "solution_md": t.solution_md,
                "reasoning_steps": t.reasoning_steps,
                "concepts_used": t.concepts_used,
                "confidence": t.confidence,
            }
            for t in trajectories
        ],
    }
    if user_requirements:
        payload["user_requirements"] = user_requirements
    return json.dumps(payload, ensure_ascii=False, default=str)


async def evaluate(
    items: list[GeneratedItem],
    trajectories: list[ActorTrajectory],
    source_concepts: list[dict[str, Any]],
    user_requirements: str = "",
    *,
    provider: str | None = None,
) -> list[ReflectorFeedback]:
    """Evaluate generated items using Actor trajectories.

    Returns one ``ReflectorFeedback`` per item.
    """
    from app.ai.providers import chat_json_completion

    user_msg = _build_reflector_user_message(
        items, trajectories, source_concepts, user_requirements,
    )

    raw = await chat_json_completion(
        system=REFLECTOR_SYSTEM_PROMPT,
        user=user_msg,
        provider=provider,
    )

    parsed = load_llm_json(raw)
    if not parsed:
        logger.warning("Reflector returned unparseable response; approving all items")
        return [
            ReflectorFeedback(item_title=item.title, quality_score=0.5, approved=True)
            for item in items
        ]

    evaluations = parsed.get("evaluations", [])
    feedback: list[ReflectorFeedback] = []

    title_to_eval = {e.get("item_title", ""): e for e in evaluations}

    for item in items:
        ev = title_to_eval.get(item.title, {})
        feedback.append(ReflectorFeedback(
            item_title=item.title,
            quality_score=min(max(ev.get("quality_score", 0.5), 0.0), 1.0),
            issues=ev.get("issues", []),
            suggestions=ev.get("suggestions", []),
            approved=ev.get("approved", True),
        ))

    return feedback


# ---------------------------------------------------------------------------
# Hardening reflector — used for iterative difficulty escalation
# ---------------------------------------------------------------------------

HARDENING_SYSTEM_PROMPT = (
    "You are a difficulty escalation evaluator. Your job is to review "
    "existing study items, how a simulated student solved them, and provide "
    "SPECIFIC, ACTIONABLE directives for making each item substantially harder.\n\n"
    "You will see:\n"
    "1. The current items and their solutions.\n"
    "2. Actor trajectories — how a simulated student solved each item, "
    "including reasoning steps, concepts used, and confidence.\n"
    "3. Additional concepts the user knows that could be woven in.\n"
    "4. The current hardening iteration number.\n\n"
    "Use the actor trajectories to identify WHERE each item was too easy:\n"
    "- If the actor solved it in few trivial steps → add multi-step reasoning\n"
    "- If the actor's confidence was high → add edge cases or constraints\n"
    "- If the actor only used 1 concept → require synthesis across concepts\n"
    "- If the reasoning was straightforward → demand proof or derivation\n\n"
    "For each item, provide:\n"
    "- hardening_directives: a list of concrete changes (e.g. 'combine with "
    "integration by parts', 'add a constraint that...', 'require multi-step "
    "reasoning across X and Y')\n"
    "- extra_concept_titles: which of the provided additional concepts should "
    "be woven into this item to increase depth (pick 1-3 that make sense)\n"
    "- difficulty_boost: a short label for the escalation strategy "
    "(e.g. 'multi-concept synthesis', 'edge-case reasoning', 'proof required')\n\n"
    "Respond with JSON: {\"hardening\": [{\"item_title\": ..., "
    "\"hardening_directives\": [...], \"extra_concept_titles\": [...], "
    "\"difficulty_boost\": \"...\"}]}"
)


def _build_hardening_user_message(
    items: list[GeneratedItem],
    trajectories: list[ActorTrajectory],
    extra_concepts: list[dict[str, Any]],
    iteration: int,
) -> str:
    traj_by_title = {t.item_title: t for t in trajectories}
    payload: dict[str, Any] = {
        "current_items": [
            {
                "title": item.title,
                "type": item.type,
                "body_md": item.body_md,
                "answer_md": item.answer_md,
                "difficulty": item.difficulty,
            }
            for item in items
        ],
        "actor_trajectories": [
            {
                "item_title": item.title,
                "solution_md": traj_by_title[item.title].solution_md if item.title in traj_by_title else "",
                "reasoning_steps": traj_by_title[item.title].reasoning_steps if item.title in traj_by_title else [],
                "concepts_used": traj_by_title[item.title].concepts_used if item.title in traj_by_title else [],
                "confidence": traj_by_title[item.title].confidence if item.title in traj_by_title else 0.0,
            }
            for item in items
        ],
        "additional_user_concepts": [
            {"title": c.get("title", ""), "content_summary": (c.get("body_md") or "")[:200]}
            for c in extra_concepts
        ],
        "hardening_iteration": iteration,
        "instruction": (
            f"This is hardening iteration {iteration}. Analyze HOW the actor "
            "solved each item (see actor_trajectories) and make each item "
            "SIGNIFICANTLY harder by targeting the weak points: if solved "
            "trivially, require multi-step reasoning; if high confidence, add "
            "edge cases; if few concepts used, require synthesis across more. "
            "Also weave in the additional concepts the user knows."
        ),
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


async def hardening_evaluate(
    items: list[GeneratedItem],
    trajectories: list[ActorTrajectory],
    all_user_concepts: list[dict[str, Any]],
    current_concept_titles: set[str],
    iteration: int,
    *,
    provider: str | None = None,
) -> list[dict[str, Any]]:
    """Produce hardening directives for each item.

    *all_user_concepts* is the full set of concepts the user has in their
    knowledge graph.  *current_concept_titles* is the set already in the
    generation context.  We pick a random subset of the remaining concepts
    as candidates for the LLM to weave in.

    Returns a list of dicts, one per item, with keys:
    ``hardening_directives``, ``extra_concept_titles``, ``difficulty_boost``.
    """
    import random
    from app.ai.providers import chat_json_completion

    available = [
        c for c in all_user_concepts
        if c.get("title", "") not in current_concept_titles
    ]
    sample_size = min(len(available), max(3, len(items) * 2))
    extra_concepts = random.sample(available, sample_size) if available else []

    user_msg = _build_hardening_user_message(items, trajectories, extra_concepts, iteration)

    raw = await chat_json_completion(
        system=HARDENING_SYSTEM_PROMPT,
        user=user_msg,
        provider=provider,
    )

    parsed = load_llm_json(raw)
    if not parsed:
        logger.warning("Hardening reflector returned unparseable response")
        return [
            {
                "hardening_directives": ["Make this problem significantly harder"],
                "extra_concept_titles": [],
                "difficulty_boost": "general escalation",
            }
            for _ in items
        ]

    evaluations = parsed.get("hardening", [])
    title_to_eval = {e.get("item_title", ""): e for e in evaluations}

    results: list[dict[str, Any]] = []
    for item in items:
        ev = title_to_eval.get(item.title, {})
        results.append({
            "hardening_directives": ev.get("hardening_directives", ["Make harder"]),
            "extra_concept_titles": ev.get("extra_concept_titles", []),
            "difficulty_boost": ev.get("difficulty_boost", "escalation"),
        })

    return results
