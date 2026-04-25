# Adapted from: vendor/yubo/app/services/providers/anthropic_chat.py
"""Anthropic chat completion provider."""

from __future__ import annotations

import anthropic

from app.config import settings


async def complete_json_anthropic(
    *,
    system: str,
    user: str | list,
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.2,
) -> str:
    """Chat completion via Anthropic. Returns the first text block.

    If ``user`` is an OpenAI-style multipart list (with
    ``{"type": "image_url", …}`` parts), convert each part into the
    Anthropic ``image`` block shape so multimodal inputs work
    uniformly across providers.
    """
    if not settings.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured")

    from app.ai.providers import _convert_user_content_to_anthropic

    content: str | list
    if isinstance(user, list):
        content = _convert_user_content_to_anthropic(user)
    else:
        content = user

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    msg = await client.messages.create(
        model=model or "claude-sonnet-4-20250514",
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": content}],
    )
    for block in msg.content:
        if block.type == "text":
            return block.text
    return "{}"
