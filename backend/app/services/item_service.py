"""Item management — session-based generation with refinement and progression.

Orchestrates the full item pipeline:
  1. Feasibility check
  2. Inner refinement loop (Generator -> Actors -> Reflector)
  3. Grading + difficulty escalation (outer loop)
  4. Session tracking

For POC, concept/edge data is passed inline (no DB fetch).  Session state
is held in-memory; production would persist to MongoDB.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.ai.pipelines import feasibility_check, grader
from app.ai.pipelines.item_construction import (
    build_concept_view,
    build_edge_view,
    build_example_item_view,
)
from app.ai.pipelines.item_loop import refine_round
from app.config import settings
from app.schemas.item import (
    Difficulty,
    FeasibilityOutcome,
    InlineConcept,
    InlineItemGenerateRequest,
    RoundResult,
    ScheduleMode,
    SchedulerState,
    SessionResponse,
    SessionStatus,
)

logger = logging.getLogger(__name__)

# In-memory session store for POC (production: MongoDB)
_sessions: dict[str, dict[str, Any]] = {}


def _filter_concepts_by_depth(
    concepts: list[InlineConcept],
    *,
    mode: ScheduleMode,
    focus_depth: int,
) -> tuple[list[InlineConcept], int, int]:
    """Apply the depth-aware schedule to the inline concept pool.

    Returns ``(visible, filtered_out_count, max_depth_seen)`` where
    ``visible`` are the concepts the LLM will see this round.

    With ``ScheduleMode.TOP_DOWN`` we keep concepts whose ``depth`` is
    ``<= focus_depth``. As a safety net, if the filter would leave the
    pool empty (e.g. focus_depth=0 but every concept has depth > 0), we
    fall back to the lowest-depth concepts available so the round can
    still produce items rather than crashing with "no concepts".
    """
    max_depth = max((c.depth for c in concepts), default=0)
    if mode != ScheduleMode.TOP_DOWN or not concepts:
        return concepts, 0, max_depth

    visible = [c for c in concepts if c.depth <= focus_depth]
    if not visible:
        # Defensive: never starve the generator. Pick the lowest-depth
        # concepts available — the user clearly wants to study but we
        # over-restricted, so degrade gracefully.
        min_depth = min(c.depth for c in concepts)
        visible = [c for c in concepts if c.depth == min_depth]
        logger.info(
            "schedule top_down: focus_depth=%d filtered all concepts; "
            "fell back to depth=%d (n=%d)",
            focus_depth,
            min_depth,
            len(visible),
        )

    filtered_out = len(concepts) - len(visible)
    return visible, filtered_out, max_depth


def _prepare_views(
    req: InlineItemGenerateRequest,
) -> tuple[list[dict], list[dict], list[dict], list[dict], set[str], list[dict], SchedulerState]:
    """Build curated views, concept ID set, context images, and the
    scheduler state describing what was visible this round.

    The scheduler filter is applied *before* the views are built so the
    LLM only ever sees in-scope concepts (strict top-down). The returned
    :class:`SchedulerState` reflects what was actually used and what the
    plugin should consider as the next focus depth (``next_focus_depth``
    is left equal to ``focus_depth_used`` here; auto-advance based on
    score happens in ``next_round`` / ``continue_round``).
    """
    visible_concepts, filtered_out, max_depth = _filter_concepts_by_depth(
        req.concepts,
        mode=req.schedule_mode,
        focus_depth=req.focus_depth,
    )

    concept_views = [
        build_concept_view(
            {"title": c.title, "body_md": c.body_md, "content_type": c.content_type},
            mastery=c.user_mastery,
            connected_titles=c.connected_concepts,
        )
        for c in visible_concepts
    ]

    # Keep raw-ish docs for Actor injection (need user_mastery)
    user_concepts = [
        {
            "id": c.id,
            "title": c.title,
            "body_md": c.body_md,
            "content_type": c.content_type,
            "user_mastery": c.user_mastery,
            "depth": c.depth,
        }
        for c in visible_concepts
    ]

    edge_views = [
        build_edge_view({
            "source_title": e.source_title,
            "target_title": e.target_title,
            "relationship_type": e.relationship_type,
            "body_md": e.body_md,
        })
        for e in req.edges
    ]

    example_views = [
        build_example_item_view({
            "type": ex.type,
            "title": ex.title,
            "body_md": ex.body_md,
            "answer_md": ex.answer_md,
            "difficulty": ex.difficulty,
            "analysis_notes": getattr(ex, "analysis_notes", "") or "",
        })
        for ex in req.example_items
    ]

    valid_ids = {c.id for c in visible_concepts}

    ctx_images = [
        {"image_base64": img.image_base64, "media_type": img.media_type}
        for img in getattr(req, "context_images", []) or []
    ]

    scheduler_state = SchedulerState(
        schedule_mode=req.schedule_mode,
        focus_depth_used=req.focus_depth,
        next_focus_depth=req.focus_depth,
        advance_triggered=False,
        visible_concept_count=len(visible_concepts),
        filtered_concept_count=filtered_out,
        max_depth_seen=max_depth,
    )

    return (
        concept_views,
        user_concepts,
        edge_views,
        example_views,
        valid_ids,
        ctx_images,
        scheduler_state,
    )


async def start_session(
    req: InlineItemGenerateRequest,
) -> SessionResponse:
    """Start a new generation session with the first round of items."""
    (
        concept_views,
        user_concepts,
        edge_views,
        example_views,
        valid_ids,
        ctx_images,
        sched_state,
    ) = _prepare_views(req)

    # Feasibility check sees the full pool (not just the depth-filtered
    # slice) so it can fail fast on "no usable concepts at all" instead of
    # interpreting an over-restrictive focus_depth as infeasibility.
    concept_docs = [
        {"title": c.title, "body_md": c.body_md, "content_type": c.content_type}
        for c in req.concepts
    ]

    prov = settings.ITEM_GENERATION_PROVIDER

    feas_outcome, feas_reason = await feasibility_check.check(
        concept_docs,
        req.requested_type,
        user_requirements=req.user_requirements,
        provider=prov,
    )

    session_id = uuid.uuid4().hex[:12]

    if feas_outcome == FeasibilityOutcome.ABANDON:
        logger.info("Session %s: feasibility ABANDON — %s", session_id, feas_reason)
        resp = SessionResponse(
            session_id=session_id,
            feasibility=feas_outcome,
            status=SessionStatus.COMPLETED,
            current_difficulty=req.difficulty_preference,
        )
        _sessions[session_id] = {
            "response": resp,
            "req": req,
            "concept_views": concept_views,
            "user_concepts": user_concepts,
            "edge_views": edge_views,
            "example_views": example_views,
            "valid_ids": valid_ids,
        }
        return resp

    generation_request = {
        "requested_type": req.requested_type,
        "difficulty_preference": req.difficulty_preference,
        "user_requirements": req.user_requirements,
    }

    round_result = await refine_round(
        concept_views,
        edge_views,
        example_views,
        generation_request,
        user_concepts,
        valid_ids,
        n_items=req.items_per_round,
        user_requirements=req.user_requirements,
        difficulty=req.difficulty_preference,
        feasibility=feas_outcome,
        provider=prov,
        round_number=1,
        context_images=ctx_images or None,
        all_user_concepts=user_concepts,
    )
    round_result.scheduler_state = sched_state

    resp = SessionResponse(
        session_id=session_id,
        rounds=[round_result],
        current_difficulty=req.difficulty_preference,
        status=SessionStatus.IN_PROGRESS,
        feasibility=feas_outcome,
    )

    _sessions[session_id] = {
        "response": resp,
        "req": req,
        "concept_views": concept_views,
        "user_concepts": user_concepts,
        "edge_views": edge_views,
        "example_views": example_views,
        "valid_ids": valid_ids,
        "context_images": ctx_images,
        "focus_depth": req.focus_depth,
    }

    return resp


_DIFFICULTY_ORDER = [
    Difficulty.EASY,
    Difficulty.MEDIUM,
    Difficulty.HARD,
    Difficulty.VERY_HARD,
    Difficulty.EXPERT,
]


def _pick_difficulty(
    current: Difficulty,
    user_scores: list[float] | None,
) -> Difficulty:
    """Decide next difficulty from the user's actual grading scores.

    - avg score >= 0.7  → escalate
    - avg score < 0.4   → de-escalate
    - otherwise          → stay at current difficulty
    """
    if not user_scores:
        return current

    avg = sum(user_scores) / len(user_scores)
    try:
        idx = _DIFFICULTY_ORDER.index(current)
    except ValueError:
        idx = 1

    if avg >= 0.7 and idx < len(_DIFFICULTY_ORDER) - 1:
        return _DIFFICULTY_ORDER[idx + 1]
    if avg < 0.4 and idx > 0:
        return _DIFFICULTY_ORDER[idx - 1]
    return current


def _advance_focus_depth(
    *,
    current: int,
    max_depth_seen: int,
    user_scores: list[float] | None,
    threshold: float,
) -> tuple[int, bool]:
    """Mirror of ``_pick_difficulty`` but for the depth-aware scheduler.

    When the user's avg score on the just-completed round at the current
    layer crosses ``threshold``, advance one layer (capped at the deepest
    section in the paper). Otherwise stay put — depth only goes up by
    design (we're walking the dependency DAG top-down).
    """
    if not user_scores:
        return current, False
    avg = sum(user_scores) / len(user_scores)
    if avg >= threshold and current < max_depth_seen:
        return current + 1, True
    return current, False


async def next_round(
    session_id: str,
    user_scores: list[float] | None = None,
) -> SessionResponse:
    """Produce the next round.  Never auto-completes — user controls session end.

    ``user_scores`` are the 0–1 scores from grading the user's own answers
    in the previous round.  They drive both axes of escalation:
    - **Difficulty**: easy → medium → hard …
    - **Focus depth** (top-down schedule mode only): c0 → c1 → c2 …
      One layer per qualifying round, capped at the paper's max depth.
    """
    session = _sessions.get(session_id)
    if not session:
        from app.exceptions import NotFoundError
        raise NotFoundError(f"Session {session_id} not found")

    resp: SessionResponse = session["response"]
    req: InlineItemGenerateRequest = session["req"]

    if resp.status == SessionStatus.COMPLETED:
        resp.status = SessionStatus.IN_PROGRESS

    prov = settings.ITEM_GENERATION_PROVIDER

    new_difficulty = _pick_difficulty(resp.current_difficulty, user_scores)
    resp.current_difficulty = new_difficulty

    # Depth advance: recompute the schedule from req.concepts each round
    # so a freshly-bumped focus_depth surfaces previously-hidden concepts.
    prev_state = resp.rounds[-1].scheduler_state if resp.rounds else None
    max_depth_seen = (
        prev_state.max_depth_seen
        if prev_state
        else max((c.depth for c in req.concepts), default=0)
    )
    current_focus = session.get("focus_depth", req.focus_depth)
    new_focus, advanced = _advance_focus_depth(
        current=current_focus,
        max_depth_seen=max_depth_seen,
        user_scores=user_scores,
        threshold=req.advance_threshold,
    )
    session["focus_depth"] = new_focus

    visible_concepts, filtered_out, max_depth = _filter_concepts_by_depth(
        req.concepts, mode=req.schedule_mode, focus_depth=new_focus
    )
    concept_views = [
        build_concept_view(
            {"title": c.title, "body_md": c.body_md, "content_type": c.content_type},
            mastery=c.user_mastery,
            connected_titles=c.connected_concepts,
        )
        for c in visible_concepts
    ]
    user_concepts = [
        {
            "id": c.id,
            "title": c.title,
            "body_md": c.body_md,
            "content_type": c.content_type,
            "user_mastery": c.user_mastery,
            "depth": c.depth,
        }
        for c in visible_concepts
    ]
    valid_ids = {c.id for c in visible_concepts}

    history = [r.model_dump() for r in resp.rounds]

    generation_request = {
        "requested_type": req.requested_type,
        "difficulty_preference": new_difficulty,
        "user_requirements": req.user_requirements,
    }

    round_result = await refine_round(
        concept_views,
        session["edge_views"],
        session["example_views"],
        generation_request,
        user_concepts,
        valid_ids,
        history=history,
        n_items=req.items_per_round,
        user_requirements=req.user_requirements,
        difficulty=new_difficulty,
        feasibility=resp.feasibility,
        provider=prov,
        round_number=len(resp.rounds) + 1,
        context_images=session.get("context_images") or None,
        all_user_concepts=user_concepts,
    )
    round_result.scheduler_state = SchedulerState(
        schedule_mode=req.schedule_mode,
        focus_depth_used=new_focus,
        next_focus_depth=new_focus,
        advance_triggered=advanced,
        visible_concept_count=len(visible_concepts),
        filtered_concept_count=filtered_out,
        max_depth_seen=max_depth,
    )

    resp.rounds.append(round_result)
    resp.status = SessionStatus.IN_PROGRESS
    _sessions[session_id]["response"] = resp
    return resp


def finish_session(session_id: str) -> SessionResponse:
    """Mark a session as completed (user-initiated)."""
    session = _sessions.get(session_id)
    if not session:
        from app.exceptions import NotFoundError
        raise NotFoundError(f"Session {session_id} not found")
    resp: SessionResponse = session["response"]
    resp.status = SessionStatus.COMPLETED
    _sessions[session_id]["response"] = resp
    return resp


async def continue_round(
    req: "ContinueRoundRequest",
) -> RoundResult:
    """Stateless round generation — no backend session needed.

    The plugin provides all context (concepts, edges, scores, round count,
    schedule_mode + focus_depth). Returns a single :class:`RoundResult`
    whose ``scheduler_state`` tells the plugin what was visible this round
    and what depth it should pass next round (auto-advanced if the user's
    avg score crossed ``advance_threshold``).
    """
    # Decide the focus depth for THIS round:
    # - explicit override wins (manual user pick)
    # - else auto-advance from req.focus_depth based on prior scores
    max_depth = max((c.depth for c in req.concepts), default=0)
    if req.override_focus_depth is not None:
        new_focus = min(req.override_focus_depth, max_depth)
        advanced = new_focus > req.focus_depth
    else:
        new_focus, advanced = _advance_focus_depth(
            current=req.focus_depth,
            max_depth_seen=max_depth,
            user_scores=req.user_scores or None,
            threshold=req.advance_threshold,
        )

    visible_concepts, filtered_out, _ = _filter_concepts_by_depth(
        req.concepts, mode=req.schedule_mode, focus_depth=new_focus
    )

    concept_views = [
        build_concept_view(
            {"title": c.title, "body_md": c.body_md, "content_type": c.content_type},
            mastery=c.user_mastery,
            connected_titles=c.connected_concepts,
        )
        for c in visible_concepts
    ]
    user_concepts = [
        {
            "id": c.id, "title": c.title, "body_md": c.body_md,
            "content_type": c.content_type, "user_mastery": c.user_mastery,
            "depth": c.depth,
        }
        for c in visible_concepts
    ]
    edge_views = [
        build_edge_view({
            "source_title": e.source_title, "target_title": e.target_title,
            "relationship_type": e.relationship_type, "body_md": e.body_md,
        })
        for e in req.edges
    ]
    example_views = [
        build_example_item_view({
            "type": ex.type, "title": ex.title, "body_md": ex.body_md,
            "answer_md": ex.answer_md, "difficulty": ex.difficulty,
            "analysis_notes": getattr(ex, "analysis_notes", "") or "",
        })
        for ex in req.example_items
    ]
    valid_ids = {c.id for c in visible_concepts}

    ctx_images = [
        {"image_base64": img.image_base64, "media_type": img.media_type}
        for img in (req.context_images or [])
    ]

    if req.override_difficulty:
        new_difficulty = req.override_difficulty
    else:
        new_difficulty = _pick_difficulty(req.current_difficulty, req.user_scores or None)
    prov = settings.ITEM_GENERATION_PROVIDER

    generation_request = {
        "requested_type": req.requested_type,
        "difficulty_preference": new_difficulty,
        "user_requirements": req.user_requirements,
    }

    round_result = await refine_round(
        concept_views,
        edge_views,
        example_views,
        generation_request,
        user_concepts,
        valid_ids,
        n_items=req.items_per_round,
        user_requirements=req.user_requirements,
        difficulty=new_difficulty,
        feasibility=FeasibilityOutcome.GENERATE,
        provider=prov,
        round_number=req.prior_round_count + 1,
        context_images=ctx_images or None,
        all_user_concepts=user_concepts,
    )
    round_result.scheduler_state = SchedulerState(
        schedule_mode=req.schedule_mode,
        focus_depth_used=new_focus,
        next_focus_depth=new_focus,
        advance_triggered=advanced,
        visible_concept_count=len(visible_concepts),
        filtered_concept_count=filtered_out,
        max_depth_seen=max_depth,
    )

    return round_result


def get_session(session_id: str) -> SessionResponse:
    """Return current session state."""
    session = _sessions.get(session_id)
    if not session:
        from app.exceptions import NotFoundError
        raise NotFoundError(f"Session {session_id} not found")
    return session["response"]
