"""Extra eval scorers: proxy cost (1), quality heuristics (2). All Braintrust-compatible callables."""

from __future__ import annotations

import re
from typing import Any, Optional


def proxy_token_efficiency_scorer(
    output: str,
    expected: Optional[str] = None,
    metadata: Optional[dict] = None,
    **kwargs: Any,
) -> Optional[dict]:
    """Prefer moderate total proxy tokens (penalize extreme verbosity)."""
    if not metadata:
        return None
    total = metadata.get("proxy_total_tokens")
    if total is None:
        return None
    # soft cap: full score below 25k proxy tokens, then taper
    if total <= 8000:
        score = 1.0
    elif total <= 25000:
        score = 1.0 - (total - 8000) / (25000 - 8000) * 0.35
    else:
        score = max(0.25, 0.65 - (total - 25000) / 100000)
    return {
        "name": "ProxyTokenEfficiency",
        "score": float(score),
        "metadata": {
            "proxy_prompt_tokens": metadata.get("proxy_prompt_tokens"),
            "proxy_completion_tokens": metadata.get("proxy_completion_tokens"),
            "proxy_total_tokens": total,
        },
    }


def body_length_band_scorer(
    output: str,
    expected: Optional[str] = None,
    metadata: Optional[dict] = None,
    **kwargs: Any,
) -> Optional[dict]:
    """First item body length in a reasonable band for markdown problems."""
    if not metadata or metadata.get("run_error"):
        return None
    items = metadata.get("items") or []
    if not items:
        return None
    body = (items[0].get("body_md") or "").strip()
    n = len(body)
    if 80 <= n <= 12000:
        score = 1.0
    elif 40 <= n < 80 or 12000 < n <= 20000:
        score = 0.65
    else:
        score = 0.25
    return {"name": "BodyLengthBand", "score": score, "metadata": {"body_chars": n}}


def answer_length_scorer(
    output: str,
    expected: Optional[str] = None,
    metadata: Optional[dict] = None,
    **kwargs: Any,
) -> Optional[dict]:
    if not metadata or metadata.get("run_error"):
        return None
    items = metadata.get("items") or []
    if not items:
        return None
    ans = (items[0].get("answer_md") or "").strip()
    n = len(ans)
    ok = 15 <= n <= 8000
    return {"name": "AnswerLength", "score": 1.0 if ok else 0.35, "metadata": {"answer_chars": n}}


def markdown_structure_scorer(
    output: str,
    expected: Optional[str] = None,
    metadata: Optional[dict] = None,
    **kwargs: Any,
) -> Optional[dict]:
    """Light structure: heading, list, or code fence."""
    if not metadata or metadata.get("run_error"):
        return None
    items = metadata.get("items") or []
    if not items:
        return None
    body = items[0].get("body_md") or ""
    has_heading = bool(re.search(r"^#{1,3}\s+\S", body, re.MULTILINE))
    has_list = bool(re.search(r"^\s*[-*]\s+\S", body, re.MULTILINE))
    has_fence = "```" in body
    checks = sum([has_heading, has_list, has_fence])
    score = min(1.0, 0.35 + checks * 0.22)
    return {
        "name": "MarkdownStructure",
        "score": score,
        "metadata": {"has_heading": has_heading, "has_list": has_list, "has_fence": has_fence},
    }


def problem_has_prompt_scorer(
    output: str,
    expected: Optional[str] = None,
    metadata: Optional[dict] = None,
    **kwargs: Any,
) -> Optional[dict]:
    """For ``problem`` type, body should look like a question (heuristic)."""
    if not metadata or metadata.get("run_error"):
        return None
    if (metadata.get("requested_type") or "").lower() != "problem":
        return {"name": "ProblemPromptShape", "score": 1.0, "metadata": {"skipped": True}}
    items = metadata.get("items") or []
    if not items:
        return None
    body = (items[0].get("body_md") or "").strip()
    has_q = "?" in body
    score = 1.0 if has_q else 0.55
    return {"name": "ProblemPromptShape", "score": score, "metadata": {"has_question_mark": has_q}}


def foundation_coverage_scorer(
    output: str,
    expected: Optional[str] = None,
    metadata: Optional[dict] = None,
    **kwargs: Any,
) -> Optional[dict]:
    """Share of input concept ids that appear in foundation_concept_ids (subset reward)."""
    if not metadata or metadata.get("run_error"):
        return None
    valid = set(metadata.get("valid_concept_ids") or [])
    items = metadata.get("items") or []
    if not valid or not items:
        return None
    fc = items[0].get("foundation_concept_ids") or []
    used = valid.intersection(fc)
    ratio = len(used) / len(valid)
    extra = set(fc) - valid
    penalty = min(0.4, 0.1 * len(extra))
    score = max(0.0, ratio - penalty)
    return {
        "name": "FoundationCoverage",
        "score": float(score),
        "metadata": {
            "valid_n": len(valid),
            "used_valid_n": len(used),
            "extra_ids": list(extra)[:8],
        },
    }
