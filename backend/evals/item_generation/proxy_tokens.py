"""Rough token counts for eval cost tracking (not billing-grade; no app changes)."""

from __future__ import annotations

import json
from typing import Any


def estimate_proxy_tokens(request: dict[str, Any], output_text: str) -> dict[str, Any]:
    """Encode request JSON + model output with ``cl100k_base`` as a proxy for API usage."""
    try:
        import tiktoken
    except ImportError:
        return {
            "proxy_prompt_tokens": None,
            "proxy_completion_tokens": None,
            "proxy_total_tokens": None,
            "proxy_encoding": None,
        }

    enc = tiktoken.get_encoding("cl100k_base")
    prompt_str = json.dumps(request, ensure_ascii=False, default=str)
    out = output_text or ""
    pt = len(enc.encode(prompt_str))
    ct = len(enc.encode(out))
    return {
        "proxy_prompt_tokens": pt,
        "proxy_completion_tokens": ct,
        "proxy_total_tokens": pt + ct,
        "proxy_encoding": "cl100k_base",
    }
