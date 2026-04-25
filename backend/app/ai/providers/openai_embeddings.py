# Adapted from: vendor/yubo/app/services/providers/openai_embeddings.py
"""OpenAI embedding provider."""

from __future__ import annotations

import logging

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.OPENAI_API_KEY or "")


async def embed_texts(
    texts: list[str],
    *,
    model: str | None = None,
) -> list[list[float]]:
    """Embed a batch of texts via OpenAI. Returns vectors in input order."""
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    client = _client()
    resp = await client.embeddings.create(
        model=model or EMBEDDING_MODEL,
        input=texts,
    )
    ordered = sorted(resp.data, key=lambda d: d.index)
    vectors = [list(d.embedding) for d in ordered]

    if len(vectors) != len(texts):
        logger.warning(
            "OpenAI embedding count mismatch: got %s expected %s",
            len(vectors),
            len(texts),
        )
    for vec in vectors:
        if len(vec) != EMBEDDING_DIMENSIONS:
            logger.warning(
                "Embedding dim %s != expected %s",
                len(vec),
                EMBEDDING_DIMENSIONS,
            )
            break
    return vectors
