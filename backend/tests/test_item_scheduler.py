"""Tests for the depth-aware scheduler in ``app.services.item_service``.

Focuses on the pure helpers (``_filter_concepts_by_depth`` and
``_advance_focus_depth``) and the end-to-end ``continue_round`` path with
``refine_round`` stubbed so we don't make any real LLM calls.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.schemas.item import (
    ContinueRoundRequest,
    Difficulty,
    InlineConcept,
    ItemType,
    RoundResult,
    ScheduleMode,
)
from app.services import item_service


# ---------------------------------------------------------------------------
# _filter_concepts_by_depth
# ---------------------------------------------------------------------------


def _ic(idx: int, depth: int = 0) -> InlineConcept:
    return InlineConcept(
        id=f"c{idx}",
        title=f"Concept {idx}",
        body_md=f"body {idx}",
        depth=depth,
    )


def test_filter_all_mode_passes_everything_through():
    concepts = [_ic(i, depth=i) for i in range(5)]
    visible, filtered, max_d = item_service._filter_concepts_by_depth(
        concepts, mode=ScheduleMode.ALL, focus_depth=0
    )
    assert visible == concepts
    assert filtered == 0
    assert max_d == 4


def test_filter_top_down_strict_cap():
    concepts = [_ic(i, depth=d) for i, d in enumerate([0, 0, 1, 1, 2, 2, 3])]
    visible, filtered, max_d = item_service._filter_concepts_by_depth(
        concepts, mode=ScheduleMode.TOP_DOWN, focus_depth=1
    )
    assert {c.depth for c in visible} == {0, 1}
    assert len(visible) == 4
    assert filtered == 3
    assert max_d == 3


def test_filter_top_down_focus_zero_only_keeps_roots():
    concepts = [_ic(i, depth=d) for i, d in enumerate([0, 1, 2])]
    visible, filtered, _ = item_service._filter_concepts_by_depth(
        concepts, mode=ScheduleMode.TOP_DOWN, focus_depth=0
    )
    assert [c.id for c in visible] == ["c0"]
    assert filtered == 2


def test_filter_top_down_falls_back_to_lowest_layer_if_empty():
    """Defensive: if every concept is deeper than focus_depth, we keep the
    shallowest layer rather than starve the generator with []."""
    concepts = [_ic(i, depth=d) for i, d in enumerate([3, 3, 4])]
    visible, filtered, _ = item_service._filter_concepts_by_depth(
        concepts, mode=ScheduleMode.TOP_DOWN, focus_depth=0
    )
    assert {c.depth for c in visible} == {3}
    assert len(visible) == 2
    assert filtered == 1


def test_filter_handles_empty_concepts():
    visible, filtered, max_d = item_service._filter_concepts_by_depth(
        [], mode=ScheduleMode.TOP_DOWN, focus_depth=5
    )
    assert visible == []
    assert filtered == 0
    assert max_d == 0


# ---------------------------------------------------------------------------
# _advance_focus_depth
# ---------------------------------------------------------------------------


def test_advance_high_score_steps_one_layer_up():
    new, adv = item_service._advance_focus_depth(
        current=1, max_depth_seen=4, user_scores=[0.8, 0.9, 0.75], threshold=0.7
    )
    assert new == 2
    assert adv is True


def test_advance_low_score_holds():
    new, adv = item_service._advance_focus_depth(
        current=2, max_depth_seen=4, user_scores=[0.4, 0.3], threshold=0.7
    )
    assert new == 2
    assert adv is False


def test_advance_capped_at_max_depth():
    new, adv = item_service._advance_focus_depth(
        current=4, max_depth_seen=4, user_scores=[1.0], threshold=0.7
    )
    assert new == 4  # already at the deepest layer
    assert adv is False


def test_advance_no_scores_holds():
    new, adv = item_service._advance_focus_depth(
        current=0, max_depth_seen=3, user_scores=None, threshold=0.7
    )
    assert new == 0
    assert adv is False


def test_advance_exactly_at_threshold_advances():
    new, adv = item_service._advance_focus_depth(
        current=0, max_depth_seen=2, user_scores=[0.7], threshold=0.7
    )
    assert new == 1
    assert adv is True


# ---------------------------------------------------------------------------
# continue_round end-to-end with stubbed LLM
# ---------------------------------------------------------------------------


def _stub_refine_round(monkeypatch: pytest.MonkeyPatch, capture: dict[str, Any]):
    async def fake(
        concept_views,
        edge_views,
        example_views,
        generation_request,
        user_concepts,
        valid_ids,
        **kwargs: Any,
    ) -> RoundResult:
        capture["concept_count"] = len(concept_views)
        capture["valid_ids"] = set(valid_ids)
        capture["depths"] = sorted({c.get("depth", 0) for c in user_concepts})
        return RoundResult(round_number=kwargs.get("round_number", 1))

    monkeypatch.setattr(item_service, "refine_round", fake)


def test_continue_round_top_down_filters_by_focus_depth(
    monkeypatch: pytest.MonkeyPatch,
):
    capture: dict[str, Any] = {}
    _stub_refine_round(monkeypatch, capture)

    concepts = [_ic(i, depth=d) for i, d in enumerate([0, 0, 1, 1, 2, 3])]
    req = ContinueRoundRequest(
        concepts=concepts,
        schedule_mode=ScheduleMode.TOP_DOWN,
        focus_depth=1,
        user_scores=[],
        prior_round_count=0,
        current_difficulty=Difficulty.EASY,
        requested_type=ItemType.PROBLEM,
    )

    result = asyncio.run(item_service.continue_round(req))

    # 4 of 6 concepts visible (depths 0 and 1)
    assert capture["concept_count"] == 4
    assert capture["depths"] == [0, 1]
    sched = result.scheduler_state
    assert sched is not None
    assert sched.focus_depth_used == 1
    assert sched.visible_concept_count == 4
    assert sched.filtered_concept_count == 2
    assert sched.max_depth_seen == 3
    assert sched.advance_triggered is False


def test_continue_round_auto_advances_focus_depth_on_high_score(
    monkeypatch: pytest.MonkeyPatch,
):
    capture: dict[str, Any] = {}
    _stub_refine_round(monkeypatch, capture)

    concepts = [_ic(i, depth=d) for i, d in enumerate([0, 0, 1, 1, 2, 2])]
    req = ContinueRoundRequest(
        concepts=concepts,
        schedule_mode=ScheduleMode.TOP_DOWN,
        focus_depth=0,
        user_scores=[0.85, 0.8],  # crosses 0.7 threshold
        prior_round_count=1,
        current_difficulty=Difficulty.EASY,
        requested_type=ItemType.PROBLEM,
    )

    result = asyncio.run(item_service.continue_round(req))

    sched = result.scheduler_state
    assert sched is not None
    assert sched.advance_triggered is True
    assert sched.focus_depth_used == 1  # advanced from 0 → 1
    assert sched.next_focus_depth == 1
    assert capture["depths"] == [0, 1]


def test_continue_round_override_focus_depth_wins_over_score(
    monkeypatch: pytest.MonkeyPatch,
):
    capture: dict[str, Any] = {}
    _stub_refine_round(monkeypatch, capture)

    concepts = [_ic(i, depth=d) for i, d in enumerate([0, 1, 2, 3])]
    req = ContinueRoundRequest(
        concepts=concepts,
        schedule_mode=ScheduleMode.TOP_DOWN,
        focus_depth=0,
        override_focus_depth=2,
        user_scores=[0.2],  # would normally hold or de-escalate
        prior_round_count=2,
        current_difficulty=Difficulty.MEDIUM,
        requested_type=ItemType.PROBLEM,
    )

    result = asyncio.run(item_service.continue_round(req))
    sched = result.scheduler_state
    assert sched is not None
    assert sched.focus_depth_used == 2
    assert capture["depths"] == [0, 1, 2]


def test_continue_round_all_mode_ignores_focus_depth(
    monkeypatch: pytest.MonkeyPatch,
):
    capture: dict[str, Any] = {}
    _stub_refine_round(monkeypatch, capture)

    concepts = [_ic(i, depth=d) for i, d in enumerate([0, 1, 2, 3])]
    req = ContinueRoundRequest(
        concepts=concepts,
        schedule_mode=ScheduleMode.ALL,
        focus_depth=0,  # would filter to just c0 if top_down
        user_scores=[],
        prior_round_count=0,
        current_difficulty=Difficulty.MEDIUM,
        requested_type=ItemType.PROBLEM,
    )

    result = asyncio.run(item_service.continue_round(req))
    assert capture["concept_count"] == 4
    sched = result.scheduler_state
    assert sched is not None
    assert sched.schedule_mode == ScheduleMode.ALL
    assert sched.filtered_concept_count == 0
