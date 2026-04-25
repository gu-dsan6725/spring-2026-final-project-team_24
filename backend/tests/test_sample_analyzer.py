"""Tests for the sample-item analyzer pipeline.

Focus:
- catalog formatting & fallback when catalog is empty
- multipart user content when images are attached
- covered-concept clamping (model-returned title MUST match catalog)
- defensive coercion (bad types, too-long lists, invalid enums)
- end-to-end ``analyze_sample_item`` with stubbed LLM including the
  unparseable-response safe fallback.

All LLM calls are stubbed so tests run offline.
"""

from __future__ import annotations

import json

import pytest

from app.ai.pipelines import sample_analyzer
from app.ai.pipelines.sample_analyzer import (
    _build_user_content,
    _coerce_list_of_str,
    _filter_covered_concepts,
    _format_concept_catalog,
    analyze_sample_item,
    format_analysis_for_prompt,
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_format_concept_catalog_renders_id_and_title() -> None:
    text = _format_concept_catalog(
        [{"id": "nb", "title": "Naive Bayes"}, {"id": "", "title": ""}]
    )
    assert "'nb'" in text
    assert "'Naive Bayes'" in text


def test_format_concept_catalog_empty_sentinel() -> None:
    assert "catalog empty" in _format_concept_catalog([])
    # Entries with no usable fields also fall back to the sentinel so
    # the LLM doesn't see "- id: '' | title: ''" noise.
    assert "catalog empty" in _format_concept_catalog([{"id": "", "title": ""}])


def test_build_user_content_text_only_returns_string() -> None:
    out = _build_user_content(
        title="Q", body_md="body", answer_md="ans", catalog_md="(cat)", images=[]
    )
    assert isinstance(out, str)
    assert "body" in out and "ans" in out


def test_build_user_content_attaches_images_as_multipart() -> None:
    out = _build_user_content(
        title="Q",
        body_md="body",
        answer_md="",
        catalog_md="(cat)",
        images=[
            {"image_base64": "AAA", "media_type": "image/png"},
            {"image_base64": "", "media_type": "image/jpeg"},  # dropped: empty b64
            {"image_base64": "BBB"},  # defaults to image/png
        ],
    )
    assert isinstance(out, list)
    kinds = [p["type"] for p in out]
    assert kinds[0] == "text"
    # Only 2 images kept (empty-b64 dropped).
    assert kinds.count("image_url") == 2
    urls = [p["image_url"]["url"] for p in out if p["type"] == "image_url"]
    assert urls[0].startswith("data:image/png;base64,AAA")
    assert urls[1].startswith("data:image/png;base64,BBB")


def test_build_user_content_no_images_ignores_empty_list() -> None:
    out = _build_user_content(
        title="Q", body_md="b", answer_md="a", catalog_md="c", images=[]
    )
    assert isinstance(out, str)


def test_filter_covered_concepts_drops_unknown_titles() -> None:
    catalog = [{"id": "nb", "title": "Naive Bayes"}, {"id": "qda", "title": "QDA"}]
    out = _filter_covered_concepts(
        ["Naive Bayes", "LogReg", "qda"],  # case-insensitive match for QDA
        catalog,
    )
    assert out == ["Naive Bayes", "QDA"]


def test_filter_covered_concepts_empty_catalog_returns_empty() -> None:
    assert _filter_covered_concepts(["anything"], []) == []


def test_filter_covered_concepts_deduplicates() -> None:
    catalog = [{"id": "nb", "title": "Naive Bayes"}]
    out = _filter_covered_concepts(["Naive Bayes", "naive bayes"], catalog)
    assert out == ["Naive Bayes"]


def test_coerce_list_of_str_limits_and_strips() -> None:
    out = _coerce_list_of_str(
        ["  hello  ", "", 42, "world", None, "a", "b", "c", "d", "e", "f"],
        limit=5,
    )
    assert out == ["hello", "world", "a", "b", "c"]


def test_coerce_list_of_str_not_a_list_returns_empty() -> None:
    assert _coerce_list_of_str("not a list") == []  # type: ignore[arg-type]


def test_format_analysis_for_prompt_skips_empty_fields() -> None:
    out = format_analysis_for_prompt(
        {
            "summary": "A short summary.",
            "estimated_difficulty": "hard",
            "concepts_covered": ["Naive Bayes"],
            "pedagogical_notes": "",  # empty -> skipped
            "strengths": [],  # empty -> skipped
            "issues": ["Missing answer"],
        }
    )
    assert "Summary:" in out
    assert "Pedagogical notes:" not in out
    assert "Strengths:" not in out
    assert "Known issues: Missing answer" in out


def test_format_analysis_for_prompt_none_returns_empty() -> None:
    assert format_analysis_for_prompt(None) == ""


# ---------------------------------------------------------------------------
# End-to-end analyze_sample_item with stubbed LLM
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_chat(monkeypatch: pytest.MonkeyPatch):
    calls: list[dict] = []
    resp: dict[str, str | Exception] = {"resp": "{}"}

    async def fake_chat(*, system: str, user, provider: str | None = None) -> str:
        r = resp["resp"]
        if isinstance(r, Exception):
            raise r
        calls.append({"system": system, "user": user, "provider": provider})
        return r  # type: ignore[return-value]

    monkeypatch.setattr("app.ai.providers.chat_json_completion", fake_chat)
    return calls, resp


@pytest.mark.asyncio
async def test_analyze_sample_item_happy_path(stub_chat):
    _, holder = stub_chat
    holder["resp"] = json.dumps(
        {
            "summary": "Spam classifier using Naive Bayes.",
            "item_type_guess": "problem",
            "estimated_difficulty": "medium",
            "concepts_covered": ["Naive Bayes", "Hallucinated Concept"],
            "concepts_missing_from_catalog": ["Laplace smoothing"],
            "pedagogical_notes": "Good build-up from priors to posteriors.",
            "strengths": ["Clear setup"],
            "issues": ["No numeric worked example"],
        }
    )

    result = await analyze_sample_item(
        title="Spam",
        body_md="Classify spam using priors.",
        answer_md="Use Bayes rule.",
        concept_catalog=[
            {"id": "nb", "title": "Naive Bayes"},
            {"id": "qda", "title": "QDA"},
        ],
    )

    assert result["summary"].startswith("Spam classifier")
    assert result["item_type_guess"] == "problem"
    assert result["estimated_difficulty"] == "medium"
    # Hallucinated concept dropped by catalog clamp.
    assert result["concepts_covered"] == ["Naive Bayes"]
    assert result["concepts_missing_from_catalog"] == ["Laplace smoothing"]
    assert "priors" in result["pedagogical_notes"]
    assert result["strengths"] == ["Clear setup"]
    assert result["issues"] == ["No numeric worked example"]


@pytest.mark.asyncio
async def test_analyze_sample_item_unparseable_falls_back(stub_chat):
    _, holder = stub_chat
    holder["resp"] = "not-json {{{"

    result = await analyze_sample_item(
        title="x",
        body_md="x",
        concept_catalog=[{"id": "a", "title": "A"}],
    )

    assert result["item_type_guess"] == "problem"
    assert result["estimated_difficulty"] == "medium"
    assert result["concepts_covered"] == []
    assert any("parseable" in i.lower() or "analyzer" in i.lower() for i in result["issues"])


@pytest.mark.asyncio
async def test_analyze_sample_item_clamps_invalid_enums(stub_chat):
    _, holder = stub_chat
    holder["resp"] = json.dumps(
        {
            "summary": "",
            "item_type_guess": "essay",  # invalid -> clamped to "problem"
            "estimated_difficulty": "impossible",  # invalid -> clamped to "medium"
            "concepts_covered": [],
            "pedagogical_notes": "",
        }
    )

    result = await analyze_sample_item(title="t", body_md="b")
    assert result["item_type_guess"] == "problem"
    assert result["estimated_difficulty"] == "medium"


@pytest.mark.asyncio
async def test_analyze_sample_item_forwards_images_as_multipart(stub_chat):
    calls, holder = stub_chat
    holder["resp"] = json.dumps(
        {
            "summary": "ok",
            "item_type_guess": "problem",
            "estimated_difficulty": "easy",
            "concepts_covered": [],
            "pedagogical_notes": "",
        }
    )

    await analyze_sample_item(
        title="t",
        body_md="b",
        context_images=[{"image_base64": "XXX", "media_type": "image/png"}],
    )

    # Verify the analyzer passed a multipart list to chat completion.
    sent_user = calls[0]["user"]
    assert isinstance(sent_user, list)
    assert any(p.get("type") == "image_url" for p in sent_user)


@pytest.mark.asyncio
async def test_analyze_sample_item_catches_llm_exceptions(stub_chat):
    _, holder = stub_chat
    holder["resp"] = RuntimeError("upstream boom")

    result = await analyze_sample_item(title="t", body_md="b")
    assert result["concepts_covered"] == []
    assert any("LLM" in i or "analyzer" in i.lower() for i in result["issues"])
