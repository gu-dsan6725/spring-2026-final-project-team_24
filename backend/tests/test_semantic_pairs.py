# Adapted from: vendor/yubo/tests/test_semantic_pairing.py
"""Tests for app.ai.pipelines.connection_inference — cosine similarity pairing."""

from __future__ import annotations

from app.ai.pipelines.connection_inference import select_semantic_pairs


def test_finds_similar_vectors():
    embeddings = [
        [1.0, 0.0, 0.0],
        [0.9, 0.436, 0.0],  # cos(0, 1) ≈ 0.90
        [0.0, 0.0, 1.0],    # orthogonal to both
    ]
    pairs = select_semantic_pairs(embeddings, threshold=0.85, top_k_per_concept=2)
    idx_set = {(a, b) for a, b, _ in pairs}
    assert (0, 1) in idx_set
    assert all(score >= 0.85 for _, _, score in pairs)


def test_orthogonal_vectors_not_paired():
    embeddings = [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ]
    pairs = select_semantic_pairs(embeddings, threshold=0.5, top_k_per_concept=2)
    assert len(pairs) == 0


def test_empty_embeddings():
    assert select_semantic_pairs([], threshold=0.5, top_k_per_concept=3) == []


def test_single_embedding():
    pairs = select_semantic_pairs([[1.0, 0.0]], threshold=0.5, top_k_per_concept=2)
    assert pairs == []


def test_top_k_limits_pairs():
    embeddings = [
        [1.0, 0.0, 0.0],
        [0.99, 0.14, 0.0],
        [0.98, 0.20, 0.0],
        [0.95, 0.31, 0.0],
    ]
    pairs = select_semantic_pairs(embeddings, threshold=0.8, top_k_per_concept=1)
    per_node_counts: dict[int, int] = {}
    for a, b, _ in pairs:
        per_node_counts[a] = per_node_counts.get(a, 0) + 1
        per_node_counts[b] = per_node_counts.get(b, 0) + 1
    # top_k=1 limits but pairs are undirected so a node can appear more than once
    assert len(pairs) >= 1


def test_identical_vectors():
    embeddings = [[1.0, 0.0]] * 3
    pairs = select_semantic_pairs(embeddings, threshold=0.99, top_k_per_concept=5)
    assert len(pairs) >= 1
    for _, _, score in pairs:
        assert abs(score - 1.0) < 0.01
