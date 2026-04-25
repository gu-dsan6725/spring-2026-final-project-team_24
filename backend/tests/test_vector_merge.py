"""Pure helpers for Pinecone hit merging (no network)."""

from app.db.pinecone import VectorMatch, merge_matches_by_id


def test_merge_keeps_highest_score_per_id():
    hits = [
        VectorMatch("a", 0.5, {}),
        VectorMatch("a", 0.9, {"k": 1}),
        VectorMatch("b", 0.7, {}),
    ]
    merged = merge_matches_by_id(hits, top_k=10)
    assert [m.id for m in merged] == ["a", "b"]
    assert merged[0].score == 0.9
    assert merged[0].metadata == {"k": 1}


def test_merge_respects_top_k():
    hits = [
        VectorMatch("x", 0.1, {}),
        VectorMatch("y", 0.99, {}),
        VectorMatch("z", 0.5, {}),
    ]
    merged = merge_matches_by_id(hits, top_k=2)
    assert len(merged) == 2
    assert merged[0].id == "y"
    assert merged[1].id == "z"
