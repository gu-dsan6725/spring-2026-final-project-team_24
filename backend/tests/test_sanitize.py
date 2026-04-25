# Adapted from: vendor/yubo/tests/test_sanitize.py
"""Tests for app.ingest.sanitize — DB-safe text cleaning."""

from __future__ import annotations

from app.ingest.sanitize import sanitize_db_text


def test_strips_nul_bytes():
    assert sanitize_db_text("a\x00b") == "ab"


def test_leaves_clean_text_unchanged():
    assert sanitize_db_text("hello world") == "hello world"


def test_empty_string():
    assert sanitize_db_text("") == ""


def test_multiple_nul_bytes():
    assert sanitize_db_text("\x00a\x00b\x00c\x00") == "abc"
