# Adapted from: vendor/yubo/app/ingest/html_extract.py
"""HTML text extraction using BeautifulSoup."""

from __future__ import annotations

from bs4 import BeautifulSoup

from app.ingest.sanitize import sanitize_db_text


def extract_text_from_html(raw: bytes) -> str:
    """Strip tags and scripts; keep visible text with newlines between blocks."""
    text = raw.decode("utf-8", errors="replace")
    soup = BeautifulSoup(text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    visible = soup.get_text(separator="\n", strip=True)
    return sanitize_db_text(visible)
