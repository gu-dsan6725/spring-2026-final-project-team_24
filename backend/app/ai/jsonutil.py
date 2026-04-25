# Adapted from: vendor/yubo/app/services/karpathy_agents/jsonutil.py
"""Robust JSON extraction from LLM output.

LLMs often wrap JSON in code fences, add preamble text, or produce
malformed output. This module provides best-effort extraction used by
every LLM-calling pipeline in the platform.
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)


def strip_code_fence(raw: str) -> str:
    """Remove ```json ... ``` wrappers if present."""
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9]*\s*", "", s)
        s = re.sub(r"\s*```\s*$", "", s)
    return s.strip()


def extract_first_json_object(text: str) -> str | None:
    """Best-effort: pull the first top-level {...} from noisy LLM output."""
    s = strip_code_fence(text)
    start = s.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return None


def load_llm_json(raw: str) -> dict | None:
    """Parse LLM output into a dict, with fallback brace-extraction.

    Returns None if parsing fails entirely.
    """
    if not raw or not raw.strip():
        return None
    cleaned = strip_code_fence(raw)
    for attempt, candidate in enumerate(
        (cleaned, extract_first_json_object(raw) or ""),
    ):
        if not candidate.strip():
            continue
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError as e:
            if attempt == 1:
                logger.warning(
                    "LLM JSON parse failed after brace-extract: %s (snippet=%r)",
                    e,
                    candidate[:400],
                )
            continue
        if isinstance(data, dict):
            return data
    logger.warning("LLM returned non-object JSON or empty; snippet=%r", cleaned[:500])
    return None
