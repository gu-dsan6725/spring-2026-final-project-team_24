"""Grade a user's free-text answer against a reference solution.

Returns structured feedback: score, correctness, strengths, mistakes,
suggestions, mastery estimate, and **per-concept verdicts**.

Per-concept verdicts are the key new signal: they let the plugin tell
the difference between
  * "solved correctly using listed concept"          → full credit
  * "solved correctly via a different valid path"    → full credit
    (concept didn't need to be invoked — don't penalize)
  * "tried to use the concept and got it wrong"      → mastery drop
  * "never reached the concept"                      → no update

Without this split, a single global score gets distributed uniformly
across every ``foundation_concept_id``, which is both unfair (penalizes
unrelated concepts) and uninformative for mastery tracking.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
You are a precise, encouraging tutor grading a student's answer.

You will receive:
- The problem statement
- The reference (correct) solution
- The student's answer
- A catalog of foundation concepts (each with `id` and `title`) that
  the author of this item tagged as relevant

Evaluate the student's answer and return ONE JSON object:
{
  "score": <0.0-1.0 overall correctness>,
  "correct": <true if the core answer is right, false otherwise>,
  "strengths": [<things the student did well>],
  "mistakes": [<specific errors or gaps>],
  "suggestions": "<one paragraph of constructive advice>",
  "mastery_estimate": <0.0-1.0 estimated overall mastery>,
  "per_concept": [
    {
      "concept_id": "<exact id from the catalog>",
      "status": "correctly_applied" | "alternative_path" |
                "misapplied" | "not_demonstrated",
      "confidence": <0.0-1.0 how sure you are of this verdict>,
      "note": "<one short sentence citing evidence>"
    },
    ...
  ]
}

Verdict rules (IMPORTANT):
- ``correctly_applied`` — student invoked this concept and used it
  correctly.
- ``alternative_path`` — student solved the problem without invoking
  this concept (e.g. reached the right answer via a different valid
  technique). DO NOT penalize: the item author tagged it as relevant,
  but the student's route didn't require it.
- ``misapplied`` — student clearly attempted to use this concept and
  got it wrong in a way that signals misunderstanding. Reserve this
  for unambiguous errors (e.g. swapped prior and likelihood, applied
  independence assumption to non-independent variables). This is the
  only verdict that SHOULD reduce mastery.
- ``not_demonstrated`` — student's answer doesn't touch this concept
  in any way (e.g. blank answer, or only addressed a subproblem).
  Neutral: no mastery update either direction.

Emit EXACTLY ONE verdict per concept in the catalog. Use the ``id``
field verbatim. Be specific in ``note`` about what you observed.

If the answer is blank or says "I don't know", give score 0, mark
every concept as ``not_demonstrated``, and give helpful guidance.

Return ONLY the JSON object — no prose, no code fences.
"""


def _format_concept_catalog(concepts: list[dict] | list[str]) -> str:
    """Render concepts for the grader prompt.

    Accepts either [{id, title}, …] or legacy [title, …]. In the
    legacy case we mint synthetic ids so the model still has something
    stable to reference (the caller won't be able to map verdicts back
    to real concept ids, but the grader's reasoning is still useful).
    """
    if not concepts:
        return "(none)"
    lines: list[str] = []
    for i, c in enumerate(concepts):
        if isinstance(c, dict):
            cid = c.get("id") or f"c{i}"
            title = c.get("title") or cid
        else:
            cid = f"c{i}"
            title = str(c)
        lines.append(f"- id: {cid!r} | title: {title!r}")
    return "\n".join(lines)


def _normalize_concepts(concepts: list[dict] | list[str]) -> list[dict]:
    """Normalize input concepts to ``[{id, title}, …]`` with synthetic
    ids for legacy string-only input. Used both for prompt rendering
    and for sanity-checking the model's returned ``concept_id`` values."""
    out: list[dict] = []
    for i, c in enumerate(concepts or []):
        if isinstance(c, dict):
            out.append({"id": c.get("id") or f"c{i}", "title": c.get("title") or ""})
        else:
            out.append({"id": f"c{i}", "title": str(c)})
    return out


def _parse_per_concept(raw: list, known_ids: set[str]) -> list[dict]:
    """Defensively pull verdicts out of the model's JSON.

    Drop entries that reference unknown ids, use an unknown status,
    or are malformed. Keeps what's usable rather than failing the
    whole grading response — the overall score/strengths/etc. are
    still useful even if the per-concept block is partially broken.
    """
    allowed_status = {
        "correctly_applied",
        "alternative_path",
        "misapplied",
        "not_demonstrated",
    }
    verdicts: list[dict] = []
    if not isinstance(raw, list):
        return verdicts

    for item in raw:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("concept_id", "")).strip()
        if not cid:
            continue
        # Accept unknown ids from the model but mark them synthetic so
        # the plugin can decide whether to drop them. For legacy
        # callers (no ids passed in), known_ids is empty — skip the check.
        if known_ids and cid not in known_ids:
            logger.debug("grader returned unknown concept_id %r; skipping", cid)
            continue
        status = str(item.get("status", "")).strip().lower()
        if status not in allowed_status:
            continue
        try:
            conf = float(item.get("confidence", 0.8))
        except (TypeError, ValueError):
            conf = 0.8
        conf = max(0.0, min(1.0, conf))
        note = str(item.get("note", "")).strip()[:300]
        verdicts.append(
            {
                "concept_id": cid,
                "status": status,
                "confidence": conf,
                "note": note,
            }
        )
    return verdicts


async def grade_answer(
    *,
    item_title: str,
    item_body_md: str,
    reference_answer_md: str,
    user_answer_md: str,
    foundation_concepts: list[dict] | list[str],
    provider: str | None = None,
) -> dict:
    """Grade one user answer. Returns parsed AnswerFeedback fields
    including ``per_concept`` verdicts.

    ``foundation_concepts`` may be ``[{id, title}, …]`` (preferred, so
    verdicts carry real ids) or ``[title, …]`` (legacy). In the legacy
    path the returned verdicts will have synthetic ``c0, c1, …`` ids
    that the caller cannot reattach to anything.
    """
    from app.ai.jsonutil import load_llm_json
    from app.ai.providers import chat_json_completion
    from app.config import settings

    prov = provider or settings.ITEM_GENERATION_PROVIDER

    catalog = _format_concept_catalog(foundation_concepts)
    normalized = _normalize_concepts(foundation_concepts)
    known_ids = {c["id"] for c in normalized}

    user_msg = (
        f"## Problem\n**{item_title}**\n\n{item_body_md}\n\n"
        f"## Foundation Concepts (id | title)\n{catalog}\n\n"
        f"## Reference Solution\n{reference_answer_md}\n\n"
        f"## Student's Answer\n{user_answer_md}\n"
    )

    raw = await chat_json_completion(
        system=SYSTEM_PROMPT,
        user=user_msg,
        provider=prov,
    )

    parsed = load_llm_json(raw)
    if not parsed:
        logger.warning(
            "grade_answer: unparseable JSON from %s; falling back to safe default",
            prov or "default",
        )
        return {
            "score": 0.0,
            "correct": False,
            "strengths": [],
            "mistakes": ["Unable to parse grading response"],
            "suggestions": "Please try again.",
            "mastery_estimate": 0.5,
            "per_concept": [],
        }

    per_concept = _parse_per_concept(parsed.get("per_concept", []), known_ids)

    return {
        "score": float(parsed.get("score", 0)),
        "correct": bool(parsed.get("correct", False)),
        "strengths": parsed.get("strengths", []),
        "mistakes": parsed.get("mistakes", []),
        "suggestions": str(parsed.get("suggestions", "")),
        "mastery_estimate": float(parsed.get("mastery_estimate", 0.5)),
        "per_concept": per_concept,
    }
