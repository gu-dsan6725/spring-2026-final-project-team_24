"""Embedding + Pinecone orchestration (mocked)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.ai.pipelines.embedding_pipeline import (
    clear_user_concepts_namespace,
    index_user_concepts,
    search_concepts_across_namespaces,
    search_user_concepts,
)
from app.config import settings
from app.db import pinecone as pinecone_db
from app.db.pinecone import VectorMatch
from app.schemas.vectors import ConceptIndexEntry


@pytest.fixture(autouse=True)
def vector_env_keys(monkeypatch):
    monkeypatch.setattr(settings, "PINECONE_API_KEY", "pk-test", raising=False)
    monkeypatch.setattr(settings, "PINECONE_INDEX", "idx-test", raising=False)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test", raising=False)


@pytest.mark.asyncio
async def test_index_user_concepts_upserts():
    captured: dict = {}

    async def fake_to_thread(fn, /, *args, **kwargs):
        if fn is pinecone_db.upsert_tuples:
            captured.update(kwargs)
        return None

    with patch(
        "app.ai.pipelines.embedding_pipeline.openai_embeddings.embed_texts",
        new=AsyncMock(return_value=[[0.1] * 1536, [0.2] * 1536]),
    ):
        with patch(
            "app.ai.pipelines.embedding_pipeline.asyncio.to_thread",
            new=AsyncMock(side_effect=fake_to_thread),
        ):
            n = await index_user_concepts(
                "u1",
                [
                    ConceptIndexEntry(concept_id="c1", text="hello"),
                    ConceptIndexEntry(
                        concept_id="c2",
                        text="world",
                        vault_path="Notes/b.md",
                        title="B",
                    ),
                ],
            )

    assert n == 2
    assert captured["namespace"] == "user_u1_concepts"
    assert len(captured["vectors"]) == 2
    assert captured["vectors"][0][0] == "c1"
    assert captured["vectors"][0][2]["user_id"] == "u1"
    assert captured["vectors"][1][2]["vault_path"] == "Notes/b.md"
    assert captured["vectors"][1][2]["title"] == "B"


@pytest.mark.asyncio
async def test_search_user_concepts():
    async def fake_to_thread(fn, /, *args, **kwargs):
        if fn is pinecone_db.query_namespace:
            return [VectorMatch("c1", 0.88, {"concept_id": "c1", "user_id": "u1"})]
        return None

    with patch(
        "app.ai.pipelines.embedding_pipeline.openai_embeddings.embed_texts",
        new=AsyncMock(return_value=[[0.3] * 1536]),
    ):
        with patch(
            "app.ai.pipelines.embedding_pipeline.asyncio.to_thread",
            new=AsyncMock(side_effect=fake_to_thread),
        ):
            hits = await search_user_concepts("u1", "linear algebra", top_k=5)

    assert len(hits) == 1
    assert hits[0].id == "c1"
    assert hits[0].score == 0.88


@pytest.mark.asyncio
async def test_search_across_namespaces():
    async def fake_to_thread(fn, /, *args, **kwargs):
        if fn is pinecone_db.query_namespaces_merged:
            return [
                VectorMatch("x", 0.5, {"concept_id": "x"}),
                VectorMatch("y", 0.6, {"concept_id": "y"}),
            ]
        return None

    with patch(
        "app.ai.pipelines.embedding_pipeline.openai_embeddings.embed_texts",
        new=AsyncMock(return_value=[[0.4] * 1536]),
    ):
        with patch(
            "app.ai.pipelines.embedding_pipeline.asyncio.to_thread",
            new=AsyncMock(side_effect=fake_to_thread),
        ):
            hits = await search_concepts_across_namespaces(
                "q",
                ["user_a_concepts", "user_b_concepts"],
                top_k=5,
            )

    assert len(hits) == 2


@pytest.mark.asyncio
async def test_clear_user_concepts_namespace_calls_delete_all():
    captured: dict = {}

    async def fake_to_thread(fn, /, *args, **kwargs):
        if fn is pinecone_db.delete_namespace_all:
            captured.update(kwargs)
        return None

    with patch(
        "app.ai.pipelines.embedding_pipeline.asyncio.to_thread",
        new=AsyncMock(side_effect=fake_to_thread),
    ):
        ns = await clear_user_concepts_namespace("u1")

    assert ns == "user_u1_concepts"
    assert captured["namespace"] == "user_u1_concepts"
