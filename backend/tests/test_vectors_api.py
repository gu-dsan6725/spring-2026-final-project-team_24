"""Tests for vector index/search API routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.db.pinecone import VectorMatch
from app.main import app


def test_index_concepts_success() -> None:
    payload = {
        "user_id": "jeff",
        "entries": [
            {
                "concept_id": "c1",
                "text": "linear algebra basics",
                "vault_path": "Math/Linear Algebra.md",
                "title": "Linear Algebra",
            }
        ],
    }
    with patch(
        "app.api.v1.vectors.embedding_pipeline.index_user_concepts",
        new=AsyncMock(return_value=1),
    ):
        with TestClient(app) as client:
            resp = client.post("/api/v1/vectors/concepts/index", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["indexed"] == 1
    assert body["namespace"] == "user_jeff_concepts"


def test_index_concepts_returns_503_on_runtime_error() -> None:
    payload = {
        "user_id": "jeff",
        "entries": [{"concept_id": "c1", "text": "x"}],
    }
    with patch(
        "app.api.v1.vectors.embedding_pipeline.index_user_concepts",
        new=AsyncMock(side_effect=RuntimeError("Pinecone is not configured")),
    ):
        with TestClient(app) as client:
            resp = client.post("/api/v1/vectors/concepts/index", json=payload)
    assert resp.status_code == 503
    assert "Pinecone is not configured" in resp.json()["detail"]


def test_search_concepts_success_includes_metadata() -> None:
    matches = [
        VectorMatch(
            id="c1",
            score=0.91,
            metadata={
                "concept_id": "c1",
                "title": "Linear Algebra",
                "vault_path": "Math/Linear Algebra.md",
            },
        )
    ]
    with patch(
        "app.api.v1.vectors.embedding_pipeline.search_user_concepts",
        new=AsyncMock(return_value=matches),
    ):
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/vectors/concepts/search",
                json={"user_id": "jeff", "query": "eigenvalues", "top_k": 5},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["namespace"] == "user_jeff_concepts"
    assert len(body["hits"]) == 1
    assert body["hits"][0]["concept_id"] == "c1"
    assert body["hits"][0]["metadata"]["vault_path"] == "Math/Linear Algebra.md"


def test_search_concepts_multi_success() -> None:
    matches = [
        VectorMatch(id="c2", score=0.82, metadata={"concept_id": "c2", "title": "Probability"})
    ]
    with patch(
        "app.api.v1.vectors.embedding_pipeline.search_concepts_across_namespaces",
        new=AsyncMock(return_value=matches),
    ):
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/vectors/concepts/search-multi",
                json={
                    "query": "random variable",
                    "namespaces": ["user_jeff_concepts", "user_alice_concepts"],
                    "top_k": 5,
                },
            )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["hits"]) == 1
    assert body["hits"][0]["concept_id"] == "c2"
    assert body["hits"][0]["metadata"]["title"] == "Probability"


def test_clear_concepts_namespace_success() -> None:
    with patch(
        "app.api.v1.vectors.embedding_pipeline.clear_user_concepts_namespace",
        new=AsyncMock(return_value="user_jeff_concepts"),
    ):
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/vectors/concepts/clear",
                json={"user_id": "jeff"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["namespace"] == "user_jeff_concepts"
    assert body["cleared"] is True


# ---------------------------------------------------------------------------
# /docs/* — paper chunk endpoints
# ---------------------------------------------------------------------------


def test_index_doc_chunks_success() -> None:
    payload = {
        "user_id": "jeff",
        "entries": [
            {
                "doc_id": "abc123",
                "section_id": "sec_01",
                "chunk_index": 0,
                "text": "chunk body",
                "section_title": "Introduction",
            },
            {
                "doc_id": "abc123",
                "section_id": "sec_01",
                "chunk_index": 1,
                "text": "second chunk",
                "section_title": "Introduction",
            },
        ],
    }
    with patch(
        "app.api.v1.vectors.embedding_pipeline.index_user_doc_chunks",
        new=AsyncMock(return_value=2),
    ):
        with TestClient(app) as client:
            resp = client.post("/api/v1/vectors/docs/index", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["indexed"] == 2
    assert body["namespace"] == "user_jeff_docs"


def test_search_doc_chunks_returns_structured_hits() -> None:
    matches = [
        VectorMatch(
            id="doc_abc123::sec_02::c0",
            score=0.88,
            metadata={
                "doc_id": "abc123",
                "section_id": "sec_02",
                "chunk_index": 0,
                "section_title": "Method",
            },
        )
    ]
    with patch(
        "app.api.v1.vectors.embedding_pipeline.search_user_doc_chunks",
        new=AsyncMock(return_value=matches),
    ):
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/vectors/docs/search",
                json={"user_id": "jeff", "query": "bayes rule", "top_k": 5},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["namespace"] == "user_jeff_docs"
    assert len(body["hits"]) == 1
    hit = body["hits"][0]
    assert hit["vector_id"] == "doc_abc123::sec_02::c0"
    assert hit["doc_id"] == "abc123"
    assert hit["section_id"] == "sec_02"
    assert hit["chunk_index"] == 0
    assert hit["metadata"]["section_title"] == "Method"


def test_clear_docs_namespace_success() -> None:
    with patch(
        "app.api.v1.vectors.embedding_pipeline.clear_user_docs_namespace",
        new=AsyncMock(return_value="user_jeff_docs"),
    ):
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/vectors/docs/clear",
                json={"user_id": "jeff"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["namespace"] == "user_jeff_docs"
    assert body["cleared"] is True


def test_index_doc_chunks_returns_503_when_pinecone_unconfigured() -> None:
    payload = {
        "user_id": "jeff",
        "entries": [
            {"doc_id": "x", "section_id": "sec_00", "chunk_index": 0, "text": "hello"}
        ],
    }
    with patch(
        "app.api.v1.vectors.embedding_pipeline.index_user_doc_chunks",
        new=AsyncMock(side_effect=RuntimeError("Pinecone is not configured")),
    ):
        with TestClient(app) as client:
            resp = client.post("/api/v1/vectors/docs/index", json=payload)
    assert resp.status_code == 503
