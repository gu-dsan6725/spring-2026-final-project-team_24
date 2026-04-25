# Adapted from: vendor/yubo/app/ingest/sanitize.py
"""Sanitize text for safe storage in PostgreSQL and MongoDB."""

from __future__ import annotations


def sanitize_db_text(text: str) -> str:
    """Strip characters that PostgreSQL rejects (e.g. NUL \\x00 from PDF extract)."""
    if "\x00" not in text:
        return text
    return text.replace("\x00", "")
