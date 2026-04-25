# Adapted from: vendor/yubo/tests/test_chunk.py
"""Tests for app.ingest.chunker — document section splitting."""

from __future__ import annotations

from app.ingest.chunker import chunk_sections


def test_chunk_empty():
    assert chunk_sections("") == []
    assert chunk_sections("   \n  ") == []


def test_chunk_markdown_headings():
    text = (
        "# Title (h1 ignored as split point)\n\n"
        "Intro paragraph.\n\n"
        "## First Section\n"
        "Body of first section.\n\n"
        "## Second Section\n"
        "Body of second section.\n"
    )
    chunks = chunk_sections(text)
    assert len(chunks) >= 2
    titles = [c[0] for c in chunks]
    assert "First Section" in titles
    assert "Second Section" in titles


def test_chunk_paragraphs_when_no_headings():
    text = "Block one.\n\nBlock two.\n\nBlock three."
    chunks = chunk_sections(text)
    assert len(chunks) == 3
    assert chunks[0][0] == "Part 1"
    assert chunks[1][0] == "Part 2"
    assert "Block two" in chunks[1][1]


def test_chunk_h3_headings():
    text = "### Deep Heading\nContent under h3.\n\n### Another\nMore content."
    chunks = chunk_sections(text)
    assert len(chunks) == 2
    assert chunks[0][0] == "Deep Heading"


def test_chunk_single_paragraph():
    text = "Just one paragraph with no breaks."
    chunks = chunk_sections(text)
    assert len(chunks) == 1
    assert chunks[0][0] == "Part 1"
    assert "one paragraph" in chunks[0][1]
