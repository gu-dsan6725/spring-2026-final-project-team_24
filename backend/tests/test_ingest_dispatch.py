"""Tests for supporting ingest utilities (chunker, sanitize, html)."""

from __future__ import annotations

from app.ingest.sanitize import sanitize_db_text
from app.ingest.chunker import chunk_sections


def test_sanitize_nul():
    assert sanitize_db_text("a\x00b") == "ab"


def test_chunk_sections_markdown():
    text = "## First\nBody A\n\n## Second\nBody B\n"
    chunks = chunk_sections(text)
    assert len(chunks) == 2


def test_html_extraction():
    from app.ingest.html import extract_text_from_html

    raw = b"<html><body><p>Visible</p><script>hidden();</script></body></html>"
    text = extract_text_from_html(raw)
    assert "Visible" in text
    assert "hidden" not in text
