# Adapted from: vendor/yubo/tests/test_lexical_edges.py
"""Tests for lexical overlap edge generation in app.services.edge_service."""

from __future__ import annotations

from app.services.edge_service import _pair_key, build_lexical_overlap_edges


def test_pair_key_is_stable():
    assert _pair_key("aaa", "bbb") == _pair_key("bbb", "aaa")
    assert _pair_key("same", "same") == ("same", "same")


def test_lexical_edges_connect_overlapping_concepts():
    concepts = [
        {
            "_id": "c1",
            "title": "Alpha machine learning",
            "body": "Neural networks and gradient descent for training models.",
        },
        {
            "_id": "c2",
            "title": "Beta optimization",
            "body": "Gradient descent is used for optimization in deep learning.",
        },
        {
            "_id": "c3",
            "title": "Gamma cooking",
            "body": "Recipes for soup and bread baking at home.",
        },
    ]

    edges = build_lexical_overlap_edges(
        concepts,
        top_k_per_concept=4,
        min_jaccard=0.02,
    )
    pair_ids = set()
    for e in edges:
        pair_ids.add((e["source_id"], e["target_id"]))
        pair_ids.add((e["target_id"], e["source_id"]))

    assert ("c1", "c2") in pair_ids or ("c2", "c1") in pair_ids
    assert all(e["relation"] == "similarity" for e in edges)
    assert all(e["label"] == "lexical_overlap" for e in edges)


def test_lexical_edges_skip_low_overlap():
    concepts = [
        {"_id": "c1", "title": "Quantum physics", "body": "Entanglement and superposition."},
        {"_id": "c2", "title": "Italian cooking", "body": "Pasta and risotto recipes."},
    ]
    edges = build_lexical_overlap_edges(concepts, min_jaccard=0.3)
    assert edges == []


def test_lexical_edges_respects_existing_pairs():
    concepts = [
        {"_id": "c1", "title": "Machine learning", "body": "gradient descent optimization"},
        {"_id": "c2", "title": "Deep learning", "body": "gradient descent neural networks"},
    ]
    edges = build_lexical_overlap_edges(
        concepts,
        min_jaccard=0.01,
        existing_pairs={("c1", "c2")},
    )
    assert edges == []


def test_lexical_edges_single_concept():
    concepts = [{"_id": "c1", "title": "Only one", "body": "No pairs possible."}]
    assert build_lexical_overlap_edges(concepts) == []
