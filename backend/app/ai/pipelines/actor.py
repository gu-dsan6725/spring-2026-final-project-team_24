"""Actor pipeline — solve generated items with user knowledge context.

Each Actor receives the user's prerequisite knowledge nodes and mastery
scores via tool-calling injection, simulating what *this specific user*
would experience solving the item.  The resulting trajectory (solution,
reasoning steps, concepts used, confidence) is passed to the Reflector.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.schemas.item import ActorTrajectory, GeneratedItem

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOL_GET_USER_CONCEPT = {
    "type": "function",
    "function": {
        "name": "get_user_concept",
        "description": "Retrieve a concept from the user's personal knowledge, including their mastery level.",
        "parameters": {
            "type": "object",
            "properties": {
                "concept_id": {"type": "string"},
            },
            "required": ["concept_id"],
        },
    },
}

TOOL_SOLVE_ITEM = {
    "type": "function",
    "function": {
        "name": "solve_item",
        "description": "Submit your solution to the study item.",
        "parameters": {
            "type": "object",
            "properties": {
                "solution_md": {
                    "type": "string",
                    "description": "Your step-by-step solution in markdown.",
                },
                "reasoning_steps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Key reasoning steps taken to solve the item.",
                },
                "concepts_used": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Concept titles actually used in the solution.",
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence in the solution (0.0 to 1.0).",
                },
            },
            "required": ["solution_md", "reasoning_steps", "concepts_used", "confidence"],
        },
    },
}


ACTOR_SYSTEM_PROMPT = (
    "You are a student simulating a specific user's problem-solving process. "
    "You have access to this user's prerequisite knowledge (retrieved via tools). "
    "Each concept shows the user's mastery score — a low score means you should "
    "struggle with that concept, a high score means you can apply it confidently. "
    "Solve the given problem using ONLY the knowledge available to you. "
    "Be realistic: if the user's mastery is low on a required concept, show "
    "uncertainty or make plausible mistakes. Call solve_item with your solution."
)


# ---------------------------------------------------------------------------
# View builder
# ---------------------------------------------------------------------------

def build_user_concept_view(doc: dict[str, Any]) -> dict[str, Any]:
    """Curate a user's concept for Actor knowledge injection."""
    return {
        "title": doc.get("title", ""),
        "content": doc.get("body_md") or doc.get("content_md", ""),
        "user_mastery": doc.get("user_mastery", 0.5),
        "mastery_note": _mastery_note(doc.get("user_mastery", 0.5)),
    }


def _mastery_note(mastery: float) -> str:
    if mastery < 0.3:
        return "You barely understand this — expect difficulty."
    if mastery < 0.7:
        return "You have partial understanding — can apply basics."
    return "You know this well — can apply confidently."


# ---------------------------------------------------------------------------
# Message assembly
# ---------------------------------------------------------------------------

def _to_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def build_actor_messages(
    item: GeneratedItem,
    user_concepts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Assemble the tool-calling conversation for the Actor."""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": ACTOR_SYSTEM_PROMPT},
    ]

    call_id = 0
    for concept in user_concepts:
        cid = f"call_user_concept_{call_id}"
        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": cid,
                "type": "function",
                "function": {
                    "name": "get_user_concept",
                    "arguments": json.dumps({"concept_id": concept.get("id", str(call_id))}),
                },
            }],
        })
        messages.append({
            "role": "tool",
            "tool_call_id": cid,
            "content": _to_json(build_user_concept_view(concept)),
        })
        call_id += 1

    messages.append({
        "role": "user",
        "content": _to_json({
            "task": "Solve the following study item using your available knowledge.",
            "item": {
                "title": item.title,
                "type": item.type,
                "body_md": item.body_md,
                "difficulty": item.difficulty,
            },
        }),
    })

    return messages


# ---------------------------------------------------------------------------
# Solve entry point
# ---------------------------------------------------------------------------

async def solve(
    item: GeneratedItem,
    user_concepts: list[dict[str, Any]],
    *,
    provider: str | None = None,
) -> ActorTrajectory:
    """Have an Actor solve *item* using the user's knowledge context."""
    from app.ai.providers import chat_tool_completion

    messages = build_actor_messages(item, user_concepts)

    try:
        result = await chat_tool_completion(
            messages=messages,
            tools=[TOOL_SOLVE_ITEM],
            provider=provider,
        )
        args = result.get("arguments", {})
        return ActorTrajectory(
            item_title=item.title,
            solution_md=args.get("solution_md", ""),
            reasoning_steps=args.get("reasoning_steps", []),
            concepts_used=args.get("concepts_used", []),
            confidence=min(max(args.get("confidence", 0.5), 0.0), 1.0),
        )
    except Exception:
        logger.exception("Actor failed to solve item %r", item.title)
        return ActorTrajectory(
            item_title=item.title,
            solution_md="[Actor failed to produce a solution]",
            confidence=0.0,
        )
