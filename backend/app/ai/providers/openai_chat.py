# Adapted from: vendor/yubo/app/services/providers/openai_chat.py
"""OpenAI chat completion provider."""

from __future__ import annotations

from openai import AsyncOpenAI

from app.config import settings


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.OPENAI_API_KEY or "")


async def complete_json_openai(
    *,
    system: str,
    user: str | list,
    model: str | None = None,
    temperature: float = 0.2,
) -> str:
    """Chat completion with JSON response mode.

    ``user`` may be a plain string OR an OpenAI multipart list
    (``[{"type": "text", …}, {"type": "image_url", …}]``) for
    multimodal prompts. OpenAI accepts that shape natively, so we
    pass it through without translation.

    Returns the assistant message content (expected to be a JSON object).
    """
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    client = _client()
    resp = await client.chat.completions.create(
        model=model or "gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
    )
    return resp.choices[0].message.content or "{}"
