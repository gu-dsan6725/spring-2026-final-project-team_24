"""Tests for the char-window sub-chunker."""

from __future__ import annotations

import pytest

from app.ingest.sub_chunker import chunk_text


def test_empty_input_returns_empty():
    assert chunk_text("", chunk_size=100, overlap=10) == []
    assert chunk_text("   \n\n  ", chunk_size=100, overlap=10) == []


def test_short_input_is_single_chunk():
    text = "hello world"
    out = chunk_text(text, chunk_size=100, overlap=10)
    assert len(out) == 1
    assert out[0].text == text
    assert out[0].index == 0
    assert out[0].char_range == (0, len(text))


def test_chunking_covers_text_with_overlap():
    text = "a" * 500
    out = chunk_text(text, chunk_size=200, overlap=50)
    assert len(out) >= 3
    for i, c in enumerate(out):
        assert c.index == i
    # Ranges should be monotonically non-decreasing start, and the last chunk
    # must reach the end of the text.
    assert out[-1].char_range[1] == len(text)


def test_overlap_must_be_valid():
    with pytest.raises(ValueError):
        chunk_text("abc", chunk_size=10, overlap=-1)
    with pytest.raises(ValueError):
        chunk_text("abc", chunk_size=10, overlap=10)


def test_chunk_size_must_be_positive():
    with pytest.raises(ValueError):
        chunk_text("abc", chunk_size=0, overlap=0)


def test_whitespace_snap_prefers_paragraph_break():
    para1 = "word " * 60  # ~300 chars
    para2 = "other " * 60
    text = para1 + "\n\n" + para2
    out = chunk_text(text, chunk_size=320, overlap=40, snap_tolerance=120)
    assert len(out) >= 2
    # First chunk should end at or very near the paragraph break — definitely not
    # in the middle of a word.
    first_end = out[0].char_range[1]
    assert text[first_end - 1] in (" ", "\n")


def test_zero_overlap_progresses():
    text = "xyz" * 400  # 1200 chars, all non-whitespace
    out = chunk_text(text, chunk_size=300, overlap=0)
    # With no whitespace to snap to, chunk walks forward by exactly chunk_size.
    assert len(out) == 4
    assert out[0].char_range == (0, 300)
    assert out[-1].char_range[1] == len(text)


def test_indices_are_sequential_even_with_skipped_empty_windows():
    text = "hello world " * 50
    out = chunk_text(text, chunk_size=120, overlap=20)
    assert [c.index for c in out] == list(range(len(out)))
