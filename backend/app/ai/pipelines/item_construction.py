"""Item construction pipeline — tool-calling generation with history context.

Uses OpenAI/Groq tool-calling as a **structured context injection**
mechanism: each user-selected concept, edge, and example item is injected
as a synthetic tool-call result, and the LLM produces items via a
``generate_item`` tool call.  This produces higher quality than naive prompt
concatenation because the model treats each tool result as grounded,
bounded context.

Pipeline position:
  1. feasibility_check  -> should we attempt generation?
  2. item_pool          -> search for existing items first (deferred).
  3. **item_construction (this module)** -> tool-calling generation.
  4. item_evaluation    -> validate candidates before pool entry.

In the full loop, prior round results (items + grader reviews) are
accumulated as additional tool-call context so the Generator has full
history when producing harder items.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.schemas.item import GeneratedItem

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions — schemas for synthetic tool-call injection.
# ---------------------------------------------------------------------------

TOOL_GET_CONCEPT = {
    "type": "function",
    "function": {
        "name": "get_concept",
        "description": "Retrieve a concept from the user's knowledge graph.",
        "parameters": {
            "type": "object",
            "properties": {
                "concept_id": {"type": "string"},
            },
            "required": ["concept_id"],
        },
    },
}

TOOL_GET_EDGE = {
    "type": "function",
    "function": {
        "name": "get_edge",
        "description": "Retrieve a relationship edge between two concepts.",
        "parameters": {
            "type": "object",
            "properties": {
                "edge_id": {"type": "string"},
            },
            "required": ["edge_id"],
        },
    },
}

TOOL_GET_EXAMPLE_ITEM = {
    "type": "function",
    "function": {
        "name": "get_example_item",
        "description": "Retrieve an existing item from the item pool as a reference example.",
        "parameters": {
            "type": "object",
            "properties": {
                "item_id": {"type": "string"},
            },
            "required": ["item_id"],
        },
    },
}

TOOL_GET_PRIOR_ROUND = {
    "type": "function",
    "function": {
        "name": "get_prior_round",
        "description": "Retrieve results from a prior generation round including items and grader review.",
        "parameters": {
            "type": "object",
            "properties": {
                "round_number": {"type": "integer"},
            },
            "required": ["round_number"],
        },
    },
}

TOOL_GET_REFLECTOR_FEEDBACK = {
    "type": "function",
    "function": {
        "name": "get_reflector_feedback",
        "description": "Retrieve quality feedback from the Reflector on previously generated items.",
        "parameters": {
            "type": "object",
            "properties": {
                "round_number": {"type": "integer"},
            },
            "required": ["round_number"],
        },
    },
}

TOOL_GENERATE_ITEM = {
    "type": "function",
    "function": {
        "name": "generate_item",
        "description": "Generate a study item that tests the given foundation concepts.",
        "parameters": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["problem", "definition", "flashcard", "code_challenge"],
                },
                "title": {"type": "string"},
                "body_md": {
                    "type": "string",
                    "description": "The question or prompt in markdown.",
                },
                "answer_md": {
                    "type": "string",
                    "description": "The solution in markdown.",
                },
                "foundation_concept_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "IDs of concepts this item tests.",
                },
                "difficulty": {
                    "type": "string",
                    "enum": ["easy", "medium", "hard", "very_hard", "expert"],
                },
                "explanation_md": {
                    "type": "string",
                    "description": "Step-by-step explanation of the solution.",
                },
            },
            "required": [
                "type",
                "title",
                "body_md",
                "answer_md",
                "foundation_concept_ids",
                "difficulty",
            ],
        },
    },
}

ALL_TOOLS = [
    TOOL_GET_CONCEPT,
    TOOL_GET_EDGE,
    TOOL_GET_EXAMPLE_ITEM,
    TOOL_GET_PRIOR_ROUND,
    TOOL_GET_REFLECTOR_FEEDBACK,
    TOOL_GENERATE_ITEM,
]


def _system_prompt(n_items: int, user_requirements: str) -> str:
    base = (
        "You are an item generator for a knowledge-sharing platform. "
        "You have retrieved the user's selected concepts, edges, and example "
        "items via tool calls. Each concept includes a user_mastery score "
        "(0.0 = no exposure, 1.0 = fully mastered) indicating how well the "
        "user currently understands it — use this to calibrate item difficulty. "
        f"Generate {n_items} distinct study item(s) by calling the generate_item "
        "tool once per item. Each item must genuinely test the foundation "
        "concepts provided, not just mention them. Make each item different "
        "in angle or approach."
    )
    if user_requirements:
        base += (
            f"\n\nUser requirements: {user_requirements}\n"
            "Respect these requirements when crafting items."
        )
    return base


# Keep backward compat
SYSTEM_PROMPT = _system_prompt(1, "")


# ---------------------------------------------------------------------------
# View builders — transform raw docs into curated JSON for tool injection.
# ---------------------------------------------------------------------------

def build_concept_view(
    doc: dict[str, Any],
    mastery: float | None = None,
    connected_titles: list[str] | None = None,
) -> dict[str, Any]:
    """Curate a concept document for tool-call injection."""
    view: dict[str, Any] = {
        "title": doc.get("title", ""),
        "content": doc.get("body_md") or doc.get("content_md", ""),
        "content_type": doc.get("content_type", "markdown"),
    }
    if connected_titles:
        view["connected_concepts"] = connected_titles
    if mastery is not None:
        view["user_mastery"] = round(mastery, 2)
        if mastery < 0.3:
            view["mastery_note"] = "Low understanding — user is still learning this."
        elif mastery < 0.7:
            view["mastery_note"] = "Partial understanding — some items completed."
        else:
            view["mastery_note"] = "Strong understanding — user has mastered most related items."
    view["relationship_to_request"] = "foundation concept (user selected)"
    return view


def build_edge_view(doc: dict[str, Any]) -> dict[str, Any]:
    """Curate an edge document for tool-call injection."""
    return {
        "source": doc.get("source_title") or doc.get("source_id", ""),
        "target": doc.get("target_title") or doc.get("target_id", ""),
        "relationship_type": doc.get("relationship_type", ""),
        "explanation": doc.get("body_md", ""),
        "relationship_to_request": "connects selected foundation concepts",
    }


def build_example_item_view(doc: dict[str, Any]) -> dict[str, Any]:
    """Curate an existing item for few-shot reference injection."""
    view: dict[str, Any] = {
        "type": doc.get("type", ""),
        "title": doc.get("title", ""),
        "body_md": doc.get("body_md", ""),
        "answer_md": doc.get("answer_md", ""),
        "difficulty": doc.get("difficulty", ""),
        "foundation_concepts": doc.get("foundation_concept_titles", []),
    }
    # Pre-analysis notes produced by the sample-item analyzer
    # (``app.ai.pipelines.sample_analyzer``). When present they tell
    # the Generator what the sample actually exercises and what makes
    # it pedagogically effective — emulate intent, not surface form.
    notes = (doc.get("analysis_notes") or "").strip()
    if notes:
        view["analysis_notes"] = notes
    return view


def build_prior_round_view(round_result: dict[str, Any]) -> dict[str, Any]:
    """Curate a prior round for history injection."""
    items_summary = []
    for item in round_result.get("items", []):
        items_summary.append({
            "title": item.get("title", ""),
            "type": item.get("type", ""),
            "difficulty": item.get("difficulty", ""),
            "body_md": item.get("body_md", "")[:300],
        })

    view: dict[str, Any] = {
        "round_number": round_result.get("round_number", 0),
        "items_produced": items_summary,
        "grader_summary": round_result.get("grader_summary"),
    }

    # Include actor trajectories when present (hardening rounds)
    # so the generator sees HOW each item was solved and can target easy parts.
    trajectories = round_result.get("actor_trajectories", [])
    if trajectories:
        view["actor_trajectories"] = [
            {
                "item_title": t.get("item_title", ""),
                "reasoning_steps": t.get("reasoning_steps", []),
                "concepts_used": t.get("concepts_used", []),
                "confidence": t.get("confidence", 0.0),
            }
            for t in trajectories
        ]

    return view


def build_reflector_feedback_view(round_result: dict[str, Any]) -> dict[str, Any]:
    """Curate reflector feedback for injection into the next generation round."""
    feedback = []
    for fb in round_result.get("reflector_feedback", []):
        feedback.append({
            "item_title": fb.get("item_title", ""),
            "quality_score": fb.get("quality_score", 0),
            "issues": fb.get("issues", []),
            "suggestions": fb.get("suggestions", []),
            "approved": fb.get("approved", False),
        })
    return {
        "round_number": round_result.get("round_number", 0),
        "feedback": feedback,
    }


# ---------------------------------------------------------------------------
# Message assembly
# ---------------------------------------------------------------------------

def _to_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _inject_tool_result(
    messages: list[dict], call_id: int, tool_name: str, arg_key: str,
    arg_value: Any, content: dict,
) -> int:
    """Append a synthetic assistant→tool message pair. Returns next call_id."""
    cid = f"call_{tool_name}_{call_id}"
    messages.append({
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": cid,
            "type": "function",
            "function": {
                "name": tool_name,
                "arguments": json.dumps({arg_key: arg_value}, default=str),
            },
        }],
    })
    messages.append({
        "role": "tool",
        "tool_call_id": cid,
        "content": _to_json(content),
    })
    return call_id + 1


def build_messages(
    concepts: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    example_items: list[dict[str, Any]],
    request: dict[str, Any],
    *,
    history: list[dict[str, Any]] | None = None,
    n_items: int = 1,
    user_requirements: str = "",
    context_images: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Assemble the tool-calling conversation for item generation.

    Each concept/edge/example/prior-round is injected as a synthetic
    assistant tool_call followed by a tool-role result.  The final user
    message carries the generation request with user preferences.

    When *context_images* is provided, image blocks are prepended to the
    final user message as a content array (OpenAI multi-part format).
    """
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _system_prompt(n_items, user_requirements)},
    ]
    call_id = 0

    for concept in concepts:
        call_id = _inject_tool_result(
            messages, call_id, "get_concept",
            "concept_id", concept.get("_id", call_id), concept,
        )

    for edge in edges:
        call_id = _inject_tool_result(
            messages, call_id, "get_edge",
            "edge_id", edge.get("_id", call_id), edge,
        )

    for item in example_items:
        call_id = _inject_tool_result(
            messages, call_id, "get_example_item",
            "item_id", item.get("_id", call_id), item,
        )

    for rnd in (history or []):
        rnum = rnd.get("round_number", 0)
        call_id = _inject_tool_result(
            messages, call_id, "get_prior_round",
            "round_number", rnum, build_prior_round_view(rnd),
        )
        if rnd.get("reflector_feedback"):
            call_id = _inject_tool_result(
                messages, call_id, "get_reflector_feedback",
                "round_number", rnum, build_reflector_feedback_view(rnd),
            )

    text_payload = _to_json(request)

    if context_images:
        parts: list[dict[str, Any]] = []
        for img in context_images:
            parts.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{img['media_type']};base64,{img['image_base64']}",
                },
            })
        parts.append({"type": "text", "text": text_payload})
        messages.append({"role": "user", "content": parts})
    else:
        messages.append({"role": "user", "content": text_payload})

    return messages


# ---------------------------------------------------------------------------
# Generation entry point
# ---------------------------------------------------------------------------

async def generate(
    concepts: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    example_items: list[dict[str, Any]],
    request: dict[str, Any],
    *,
    history: list[dict[str, Any]] | None = None,
    n_items: int = 3,
    user_requirements: str = "",
    provider: str | None = None,
    context_images: list[dict[str, Any]] | None = None,
) -> list[GeneratedItem]:
    """Generate study items via tool-calling LLM.

    Returns up to *n_items* ``GeneratedItem`` instances.  The LLM is called
    once and expected to produce multiple ``generate_item`` tool calls.
    If it only produces one, we call it repeatedly.
    """
    from app.ai.providers import chat_tool_completion

    messages = build_messages(
        concepts, edges, example_items, request,
        history=history,
        n_items=n_items,
        user_requirements=user_requirements,
        context_images=context_images,
    )

    items: list[GeneratedItem] = []

    for attempt in range(n_items):
        try:
            result = await chat_tool_completion(
                messages=messages,
                tools=[TOOL_GENERATE_ITEM],
                provider=provider,
            )
            args = result.get("arguments", {})
            item = GeneratedItem(**args)
            items.append(item)

            # Inject the result back so subsequent calls see prior items
            cid = f"call_gen_{attempt}"
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": cid,
                    "type": "function",
                    "function": {
                        "name": "generate_item",
                        "arguments": _to_json(args),
                    },
                }],
            })
            messages.append({
                "role": "tool",
                "tool_call_id": cid,
                "content": _to_json({
                    "status": "generated",
                    "item_number": attempt + 1,
                    "instruction": (
                        f"Item {attempt + 1} of {n_items} generated. "
                        "Generate the next distinct item with a different angle."
                        if attempt + 1 < n_items
                        else "All items generated."
                    ),
                }),
            })
            if attempt + 1 < n_items:
                messages.append({
                    "role": "user",
                    "content": (
                        f"Generate item {attempt + 2} of {n_items}. "
                        "Use a different angle or approach."
                    ),
                })
        except Exception:
            logger.exception("Item generation attempt %d failed", attempt + 1)
            if not items:
                raise
            break

    return items
