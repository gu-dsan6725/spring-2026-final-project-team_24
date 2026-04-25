"""Tests for the LLM-driven graph builder + depth layering.

The async ``build_section_graph`` path is exercised via a stub for
``chat_json_completion`` so we don't burn API quota in CI; the pure-logic
``compute_depths`` is tested directly.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.ai.pipelines import graph_builder
from app.ai.pipelines.graph_builder import (
    GraphEdge,
    build_section_graph,
    compute_depths,
)
from app.ingest.section_splitter import Section


# ---------------------------------------------------------------------------
# compute_depths — pure logic
# ---------------------------------------------------------------------------


def _sec(i: int) -> str:
    return f"sec_{i:02d}"


def test_compute_depths_linear_chain():
    """sec_01 depends_on sec_00, sec_02 depends_on sec_01 → depths 0,1,2."""
    sids = [_sec(0), _sec(1), _sec(2)]
    edges = [
        GraphEdge(source=_sec(1), target=_sec(0), label="depends_on"),
        GraphEdge(source=_sec(2), target=_sec(1), label="depends_on"),
    ]
    depths = compute_depths(sids, edges)
    assert depths == {_sec(0): 0, _sec(1): 1, _sec(2): 2}


def test_compute_depths_diamond():
    """Diamond DAG: 0 ← 1, 0 ← 2, 1 ← 3, 2 ← 3 → depth(3) = 2."""
    sids = [_sec(0), _sec(1), _sec(2), _sec(3)]
    edges = [
        GraphEdge(source=_sec(1), target=_sec(0), label="depends_on"),
        GraphEdge(source=_sec(2), target=_sec(0), label="depends_on"),
        GraphEdge(source=_sec(3), target=_sec(1), label="depends_on"),
        GraphEdge(source=_sec(3), target=_sec(2), label="depends_on"),
    ]
    depths = compute_depths(sids, edges)
    assert depths[_sec(0)] == 0
    assert depths[_sec(1)] == 1
    assert depths[_sec(2)] == 1
    assert depths[_sec(3)] == 2


def test_compute_depths_orphan_section_gets_zero():
    sids = [_sec(0), _sec(1), _sec(2)]
    edges = [GraphEdge(source=_sec(1), target=_sec(0), label="depends_on")]
    depths = compute_depths(sids, edges)
    assert depths[_sec(2)] == 0  # untouched by any edge


def test_compute_depths_ignores_non_dependency_relations():
    sids = [_sec(0), _sec(1)]
    edges = [
        GraphEdge(source=_sec(1), target=_sec(0), label="contrasts"),
        GraphEdge(source=_sec(1), target=_sec(0), label="generalizes"),
    ]
    depths = compute_depths(sids, edges)
    assert depths == {_sec(0): 0, _sec(1): 0}


def test_compute_depths_cycle_collapses_to_single_layer():
    """A 2-cycle must not produce infinite depth: SCC condensation puts
    both nodes in the same layer."""
    sids = [_sec(0), _sec(1), _sec(2)]
    edges = [
        GraphEdge(source=_sec(0), target=_sec(1), label="depends_on"),
        GraphEdge(source=_sec(1), target=_sec(0), label="depends_on"),
        GraphEdge(source=_sec(2), target=_sec(0), label="depends_on"),
    ]
    depths = compute_depths(sids, edges)
    assert depths[_sec(0)] == depths[_sec(1)]
    assert depths[_sec(2)] > depths[_sec(0)]


def test_compute_depths_drops_self_and_unknown_ids():
    sids = [_sec(0), _sec(1)]
    edges = [
        GraphEdge(source=_sec(0), target=_sec(0), label="depends_on"),
        GraphEdge(source=_sec(1), target="sec_99", label="depends_on"),
        GraphEdge(source="sec_99", target=_sec(0), label="depends_on"),
    ]
    depths = compute_depths(sids, edges)
    assert depths == {_sec(0): 0, _sec(1): 0}


# ---------------------------------------------------------------------------
# build_section_graph — full path with stubbed LLM
# ---------------------------------------------------------------------------


def _make_section(order: int, title: str, body: str = "") -> Section:
    return Section(
        order=order,
        section_id=f"sec_{order:02d}",
        title=title,
        slug=title.lower().replace(" ", "-"),
        level=2,
        body_md=body or f"Body of section {order}.",
        char_range=(0, len(body)),
        image_refs=[],
    )


def test_build_section_graph_too_few_sections_returns_zero_depth():
    sections = [_make_section(0, "Intro")]
    res = asyncio.run(build_section_graph(sections, provider="openai"))
    assert res.edges == []
    assert res.depths == {"sec_00": 0}


def test_build_section_graph_no_chat_provider_falls_back(monkeypatch: pytest.MonkeyPatch):
    """When ``chat_available`` returns False, return depth=0 for every
    section without raising."""
    monkeypatch.setattr(graph_builder, "chat_available", lambda *_a, **_kw: False)
    sections = [_make_section(i, f"S{i}") for i in range(3)]
    res = asyncio.run(build_section_graph(sections, provider="openai"))
    assert res.edges == []
    assert res.depths == {"sec_00": 0, "sec_01": 0, "sec_02": 0}


def test_build_section_graph_uses_llm_response(monkeypatch: pytest.MonkeyPatch):
    """Stub the LLM to return a known edge set; confirm depths line up."""
    monkeypatch.setattr(graph_builder, "chat_available", lambda *_a, **_kw: True)

    fake_response = (
        '{"edges":['
        '{"source":"sec_01","target":"sec_00","label":"depends_on","anchor":"Bayes"},'
        '{"source":"sec_02","target":"sec_01","label":"depends_on"},'
        '{"source":"sec_02","target":"sec_00","label":"generalizes"}'
        "]}"
    )

    async def fake_chat(**_kw: Any) -> str:
        return fake_response

    monkeypatch.setattr(graph_builder, "chat_json_completion", fake_chat)

    sections = [_make_section(i, f"S{i}") for i in range(3)]
    res = asyncio.run(build_section_graph(sections, provider="openai"))

    assert len(res.edges) == 3
    labels = sorted(e.label for e in res.edges)
    assert labels == ["depends_on", "depends_on", "generalizes"]
    # generalizes edge is present but not used for depth layering
    assert res.depths == {"sec_00": 0, "sec_01": 1, "sec_02": 2}
    # anchor preserved
    bayes = next(e for e in res.edges if e.anchor == "Bayes")
    assert bayes.source == "sec_01"


def test_build_section_graph_handles_garbage_json(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(graph_builder, "chat_available", lambda *_a, **_kw: True)

    async def fake_chat(**_kw: Any) -> str:
        return "not json at all"

    monkeypatch.setattr(graph_builder, "chat_json_completion", fake_chat)

    sections = [_make_section(i, f"S{i}") for i in range(2)]
    res = asyncio.run(build_section_graph(sections, provider="openai"))
    assert res.edges == []
    assert res.depths == {"sec_00": 0, "sec_01": 0}


def test_build_section_graph_handles_llm_exception(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(graph_builder, "chat_available", lambda *_a, **_kw: True)

    async def boom(**_kw: Any) -> str:
        raise RuntimeError("network exploded")

    monkeypatch.setattr(graph_builder, "chat_json_completion", boom)

    sections = [_make_section(i, f"S{i}") for i in range(2)]
    res = asyncio.run(build_section_graph(sections, provider="openai"))
    assert res.edges == []
    # Still covers every section
    assert set(res.depths) == {"sec_00", "sec_01"}
    assert all(d == 0 for d in res.depths.values())


def test_build_section_graph_filters_out_unknown_ids_in_response(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(graph_builder, "chat_available", lambda *_a, **_kw: True)

    async def fake_chat(**_kw: Any) -> str:
        return (
            '{"edges":['
            '{"source":"sec_99","target":"sec_00","label":"depends_on"},'
            '{"source":"sec_01","target":"sec_99","label":"depends_on"},'
            '{"source":"sec_01","target":"sec_00","label":"depends_on"}'
            "]}"
        )

    monkeypatch.setattr(graph_builder, "chat_json_completion", fake_chat)
    sections = [_make_section(i, f"S{i}") for i in range(2)]
    res = asyncio.run(build_section_graph(sections, provider="openai"))
    # Only the valid edge survives
    assert len(res.edges) == 1
    assert res.edges[0].source == "sec_01"
    assert res.depths == {"sec_00": 0, "sec_01": 1}
