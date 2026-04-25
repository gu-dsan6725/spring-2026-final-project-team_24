"""Tests for the answer-grader verdict pipeline.

Focus is on the per-concept verdict plumbing added by Fix #1:
  * prompt input (``{id, title}`` vs legacy string titles)
  * response parsing (well-formed, partially malformed, ids unknown)
  * fallback when the LLM emits no verdicts at all.

We stub out ``chat_json_completion`` so these run offline.
"""

from __future__ import annotations

import json

import pytest

from app.ai.pipelines import answer_grader
from app.ai.pipelines.answer_grader import (
    _format_concept_catalog,
    _normalize_concepts,
    _parse_per_concept,
    grade_answer,
)


# ---------------------------------------------------------------------------
# Pure helper unit tests — no LLM
# ---------------------------------------------------------------------------


def test_normalize_concepts_accepts_dicts_and_strings() -> None:
    out = _normalize_concepts([{"id": "x", "title": "Naive Bayes"}, "QDA"])
    assert out == [
        {"id": "x", "title": "Naive Bayes"},
        {"id": "c1", "title": "QDA"},
    ]


def test_normalize_concepts_mints_synthetic_ids_for_missing() -> None:
    out = _normalize_concepts([{"title": "A"}, {"id": "", "title": "B"}])
    assert out[0]["id"] == "c0"
    assert out[1]["id"] == "c1"


def test_format_concept_catalog_renders_id_and_title() -> None:
    text = _format_concept_catalog([{"id": "nb", "title": "Naive Bayes"}])
    assert "nb" in text and "Naive Bayes" in text


def test_format_concept_catalog_empty_is_none_sentinel() -> None:
    assert _format_concept_catalog([]) == "(none)"


def test_parse_per_concept_happy_path() -> None:
    raw = [
        {"concept_id": "nb", "status": "correctly_applied", "confidence": 0.9, "note": "ok"},
        {"concept_id": "qda", "status": "misapplied", "confidence": 0.7, "note": "swapped σ"},
    ]
    verdicts = _parse_per_concept(raw, known_ids={"nb", "qda"})
    assert len(verdicts) == 2
    assert verdicts[0]["status"] == "correctly_applied"
    assert verdicts[1]["status"] == "misapplied"
    assert verdicts[1]["confidence"] == 0.7


def test_parse_per_concept_drops_unknown_id_when_known_provided() -> None:
    raw = [
        {"concept_id": "nb", "status": "correctly_applied", "confidence": 0.8},
        {"concept_id": "ghost", "status": "correctly_applied", "confidence": 0.8},
    ]
    verdicts = _parse_per_concept(raw, known_ids={"nb"})
    assert [v["concept_id"] for v in verdicts] == ["nb"]


def test_parse_per_concept_accepts_anything_when_known_empty() -> None:
    # Legacy path: caller didn't pass concept ids, so we can't
    # validate — trust the model, keep whatever it emits.
    raw = [{"concept_id": "c0", "status": "correctly_applied", "confidence": 1.0}]
    verdicts = _parse_per_concept(raw, known_ids=set())
    assert len(verdicts) == 1


def test_parse_per_concept_drops_invalid_status() -> None:
    raw = [
        {"concept_id": "nb", "status": "nuked_it", "confidence": 1.0},
        {"concept_id": "nb", "status": "alternative_path", "confidence": 1.0},
    ]
    verdicts = _parse_per_concept(raw, known_ids={"nb"})
    assert [v["status"] for v in verdicts] == ["alternative_path"]


def test_parse_per_concept_clips_confidence_and_skips_bad_entries() -> None:
    raw = [
        {"concept_id": "nb", "status": "correctly_applied", "confidence": 4.2},
        {"not_a_dict": True},  # skipped
        {"concept_id": "", "status": "correctly_applied"},  # empty id, skipped
    ]
    verdicts = _parse_per_concept(raw, known_ids={"nb"})
    assert len(verdicts) == 1
    assert verdicts[0]["confidence"] == 1.0


def test_parse_per_concept_handles_non_list_raw() -> None:
    assert _parse_per_concept("not a list", known_ids={"nb"}) == []  # type: ignore[arg-type]
    assert _parse_per_concept(None, known_ids={"nb"}) == []  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# End-to-end grade_answer with stubbed LLM
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_chat(monkeypatch: pytest.MonkeyPatch):
    """Replace the chat completion call with a programmable stub."""
    calls: list[dict] = []
    response_holder: dict[str, str] = {"resp": "{}"}

    async def fake_chat(*, system: str, user: str, provider: str | None = None) -> str:
        calls.append({"system": system, "user": user, "provider": provider})
        return response_holder["resp"]

    monkeypatch.setattr(
        "app.ai.providers.chat_json_completion", fake_chat
    )
    # The module imports it lazily inside grade_answer, so also patch
    # the local reference path used there.
    monkeypatch.setattr(
        answer_grader, "grade_answer", answer_grader.grade_answer
    )
    return calls, response_holder


@pytest.mark.asyncio
async def test_grade_answer_returns_verdicts_on_well_formed_response(stub_chat):
    _, holder = stub_chat
    holder["resp"] = json.dumps(
        {
            "score": 0.85,
            "correct": True,
            "strengths": ["set up Bayes rule correctly"],
            "mistakes": [],
            "suggestions": "Nice.",
            "mastery_estimate": 0.8,
            "per_concept": [
                {
                    "concept_id": "nb",
                    "status": "correctly_applied",
                    "confidence": 0.9,
                    "note": "Applied P(y|x) ∝ P(x|y)P(y).",
                },
                {
                    "concept_id": "qda",
                    "status": "alternative_path",
                    "confidence": 0.7,
                    "note": "Didn't need to invoke QDA; solved via NB.",
                },
            ],
        }
    )

    result = await grade_answer(
        item_title="Spam classifier",
        item_body_md="Classify.",
        reference_answer_md="Use Bayes.",
        user_answer_md="P(spam|words) ∝ P(words|spam)P(spam). Classify spam.",
        foundation_concepts=[
            {"id": "nb", "title": "Naive Bayes"},
            {"id": "qda", "title": "QDA"},
        ],
    )

    assert result["score"] == pytest.approx(0.85)
    assert len(result["per_concept"]) == 2
    statuses = {v["concept_id"]: v["status"] for v in result["per_concept"]}
    assert statuses == {"nb": "correctly_applied", "qda": "alternative_path"}


@pytest.mark.asyncio
async def test_grade_answer_handles_unparseable_response(stub_chat):
    _, holder = stub_chat
    holder["resp"] = "not json at all {{["

    result = await grade_answer(
        item_title="x",
        item_body_md="x",
        reference_answer_md="x",
        user_answer_md="x",
        foundation_concepts=[{"id": "nb", "title": "Naive Bayes"}],
    )

    assert result["score"] == 0.0
    assert result["correct"] is False
    assert result["per_concept"] == []


@pytest.mark.asyncio
async def test_grade_answer_drops_verdicts_for_unknown_ids(stub_chat):
    _, holder = stub_chat
    holder["resp"] = json.dumps(
        {
            "score": 0.6,
            "correct": True,
            "strengths": [],
            "mistakes": [],
            "suggestions": "",
            "mastery_estimate": 0.6,
            "per_concept": [
                {"concept_id": "nb", "status": "correctly_applied", "confidence": 1.0},
                {"concept_id": "fakeid", "status": "correctly_applied", "confidence": 1.0},
            ],
        }
    )

    result = await grade_answer(
        item_title="x", item_body_md="x", reference_answer_md="x",
        user_answer_md="x",
        foundation_concepts=[{"id": "nb", "title": "Naive Bayes"}],
    )
    assert [v["concept_id"] for v in result["per_concept"]] == ["nb"]


@pytest.mark.asyncio
async def test_grade_answer_legacy_title_only_caller_still_works(stub_chat):
    """Old callers that pass ``foundation_concepts=[title, …]`` should
    still get parsed verdicts back, just with synthetic ids."""
    _, holder = stub_chat
    holder["resp"] = json.dumps(
        {
            "score": 0.5,
            "correct": False,
            "strengths": [],
            "mistakes": [],
            "suggestions": "",
            "mastery_estimate": 0.5,
            "per_concept": [
                {"concept_id": "c0", "status": "misapplied", "confidence": 0.9},
            ],
        }
    )

    result = await grade_answer(
        item_title="x", item_body_md="x", reference_answer_md="x",
        user_answer_md="x",
        foundation_concepts=["Naive Bayes"],  # legacy path
    )
    assert len(result["per_concept"]) == 1
    assert result["per_concept"][0]["status"] == "misapplied"
