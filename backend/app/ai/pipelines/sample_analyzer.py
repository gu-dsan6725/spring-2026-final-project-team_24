"""Analyze a user-uploaded sample item before it's used as a few-shot reference.

The analyzer is a grader-style LLM pass that evaluates the *sample*
(not a student answer to it). Goals:
  * tell the user what their sample actually exercises
  * flag quality issues (ambiguous statement, missing answer, off-topic)
  * emit a short pedagogical note the Generator can use to emulate the
    sample's *intent* rather than just its surface form

Supports multimodal input: when ``context_images`` is populated and the
configured provider supports images, they're inlined into the analyzer
prompt. That's how scanned problems / figure-based items get graded.

Output fields mirror ``app.schemas.item.SampleItemAnalysis``.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
You are a pedagogy-aware tutor reviewing a *sample problem* that a
learner plans to use as a study reference. You are NOT grading a
student answer — you are grading the quality of the problem itself and
mapping it onto the learner's concept catalog.

You will receive:
- The sample item's title, question body, and answer (answer may be
  empty — that's fine; note it as an issue but still analyze).
- Optionally: images embedded in the problem (diagrams, plots,
  screenshots). Use them as part of the problem statement.
- A concept catalog ``[{id, title}, …]`` the learner is currently
  studying.

Return ONE JSON object, no prose, no code fences:
{
  "summary": "<one sentence, shown in the UI>",
  "item_type_guess": "problem" | "definition" | "flashcard" | "code_challenge",
  "estimated_difficulty": "easy" | "medium" | "hard" | "very_hard" | "expert",
  "concepts_covered": ["<catalog title>", ...],
  "concepts_missing_from_catalog": ["<concept this problem uses that isn't in the catalog>", ...],
  "pedagogical_notes": "<1-2 sentences: what makes this a good study item, what the Generator should emulate>",
  "strengths": ["<what's strong about the problem>", ...],
  "issues": ["<ambiguities, missing info, off-topic, etc.>", ...]
}

Rules:
- ``concepts_covered`` MUST be a subset of catalog titles, verbatim.
  If nothing matches, return []. Do not hallucinate.
- ``concepts_missing_from_catalog`` is for concepts the problem
  clearly uses but that aren't in the catalog — this flags gaps.
- Keep each list under 6 items.
- If the answer is missing, add "No reference answer provided." to
  ``issues``.
"""


ALLOWED_TYPES = {"problem", "definition", "flashcard", "code_challenge"}
ALLOWED_DIFFICULTIES = {"easy", "medium", "hard", "very_hard", "expert"}


def _format_concept_catalog(catalog: list[dict]) -> str:
    if not catalog:
        return "(catalog empty — concepts_covered must be [])"
    lines = []
    for c in catalog:
        cid = (c.get("id") or "").strip()
        title = (c.get("title") or "").strip()
        if not title:
            continue
        lines.append(f"- id: {cid!r} | title: {title!r}")
    return "\n".join(lines) if lines else "(catalog empty — concepts_covered must be [])"


def _build_user_content(
    *,
    title: str,
    body_md: str,
    answer_md: str,
    catalog_md: str,
    images: list[dict],
) -> str | list[dict]:
    """Assemble the user message.

    Returns a plain string when there are no images (cheaper, fewer
    token overheads) or an OpenAI-style multipart list when images
    are attached.
    """
    text = (
        f"## Sample Item\n**{title}**\n\n"
        f"### Question\n{body_md or '(empty)'}\n\n"
        f"### Reference Answer\n{answer_md or '(not provided)'}\n\n"
        f"## Concept Catalog\n{catalog_md}\n"
    )
    if not images:
        return text

    parts: list[dict] = [{"type": "text", "text": text}]
    for img in images:
        b64 = (img.get("image_base64") or "").strip()
        if not b64:
            continue
        media = (img.get("media_type") or "image/png").strip()
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{media};base64,{b64}"},
            }
        )
    return parts


def _coerce_list_of_str(raw: Any, *, limit: int = 6) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for v in raw:
        if isinstance(v, str):
            s = v.strip()
            if s:
                out.append(s[:300])
        if len(out) >= limit:
            break
    return out


def _filter_covered_concepts(raw: Any, catalog: list[dict]) -> list[str]:
    """Clamp ``concepts_covered`` to titles present in the catalog.

    The model is told to return only catalog titles, but we defend
    against hallucination by intersecting against the allowed set
    (case-insensitive). Titles that don't match are dropped silently —
    they'll surface via ``concepts_missing_from_catalog`` if the
    model also listed them there.
    """
    allowed = {(c.get("title") or "").strip().lower(): (c.get("title") or "").strip() for c in catalog}
    allowed.pop("", None)
    if not allowed:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for v in (raw or []):
        if not isinstance(v, str):
            continue
        key = v.strip().lower()
        canonical = allowed.get(key)
        if canonical and canonical not in seen:
            out.append(canonical)
            seen.add(canonical)
    return out


def _safe_fallback(issue: str = "Analyzer produced no parseable response.") -> dict:
    return {
        "summary": "Unable to analyze sample.",
        "item_type_guess": "problem",
        "estimated_difficulty": "medium",
        "concepts_covered": [],
        "concepts_missing_from_catalog": [],
        "pedagogical_notes": "",
        "strengths": [],
        "issues": [issue],
    }


async def analyze_sample_item(
    *,
    title: str,
    body_md: str,
    answer_md: str = "",
    concept_catalog: list[dict] | None = None,
    context_images: list[dict] | None = None,
    provider: str | None = None,
) -> dict:
    """Run the sample-item analyzer.

    Returns a dict shaped like ``SampleItemAnalysis``. On LLM failure
    (empty or unparseable response) returns a safe default with the
    error recorded in ``issues`` so the caller can still proceed.
    """
    from app.ai.jsonutil import load_llm_json
    from app.ai.providers import chat_json_completion
    from app.config import settings

    prov = provider or settings.ITEM_GENERATION_PROVIDER
    catalog = list(concept_catalog or [])
    images = list(context_images or [])

    catalog_md = _format_concept_catalog(catalog)
    user_content = _build_user_content(
        title=title,
        body_md=body_md,
        answer_md=answer_md,
        catalog_md=catalog_md,
        images=images,
    )

    try:
        raw = await chat_json_completion(
            system=SYSTEM_PROMPT,
            user=user_content,
            provider=prov,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("sample_analyzer: LLM call failed: %s", exc)
        return _safe_fallback(f"Analyzer LLM error: {exc!s}")

    parsed = load_llm_json(raw)
    if not parsed:
        logger.warning("sample_analyzer: unparseable JSON from %s", prov or "default")
        return _safe_fallback()

    item_type = str(parsed.get("item_type_guess", "")).strip().lower()
    if item_type not in ALLOWED_TYPES:
        item_type = "problem"

    diff = str(parsed.get("estimated_difficulty", "")).strip().lower()
    if diff not in ALLOWED_DIFFICULTIES:
        diff = "medium"

    covered = _filter_covered_concepts(parsed.get("concepts_covered", []), catalog)
    missing = _coerce_list_of_str(parsed.get("concepts_missing_from_catalog", []))

    return {
        "summary": str(parsed.get("summary", "")).strip()[:400],
        "item_type_guess": item_type,
        "estimated_difficulty": diff,
        "concepts_covered": covered,
        "concepts_missing_from_catalog": missing,
        "pedagogical_notes": str(parsed.get("pedagogical_notes", "")).strip()[:600],
        "strengths": _coerce_list_of_str(parsed.get("strengths", [])),
        "issues": _coerce_list_of_str(parsed.get("issues", [])),
    }


def format_analysis_for_prompt(analysis: dict | None) -> str:
    """Render an analysis block that goes into the Generator prompt
    alongside a sample item. Empty string if no analysis attached —
    keeps the prompt lean when the feature isn't used.
    """
    if not analysis:
        return ""
    parts: list[str] = []
    if s := analysis.get("summary"):
        parts.append(f"Summary: {s}")
    if diff := analysis.get("estimated_difficulty"):
        parts.append(f"Estimated difficulty: {diff}")
    covered = analysis.get("concepts_covered") or []
    if covered:
        parts.append(f"Concepts exercised: {', '.join(covered)}")
    notes = (analysis.get("pedagogical_notes") or "").strip()
    if notes:
        parts.append(f"Pedagogical notes: {notes}")
    strengths = analysis.get("strengths") or []
    if strengths:
        parts.append("Strengths: " + "; ".join(strengths))
    issues = analysis.get("issues") or []
    if issues:
        parts.append("Known issues: " + "; ".join(issues))
    return "\n".join(parts)
