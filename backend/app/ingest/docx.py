# Adapted from: vendor/yubo/app/ingest/docx_extract.py
"""DOCX text extraction using python-docx."""

from __future__ import annotations

import io

from docx import Document

from app.exceptions import DocxExtractError
from app.ingest.sanitize import sanitize_db_text


def extract_text_from_docx(raw: bytes) -> str:
    """Extract paragraph text from a .docx file."""
    try:
        doc = Document(io.BytesIO(raw))
    except Exception as exc:  # noqa: BLE001
        raise DocxExtractError("Invalid or corrupted .docx file.") from exc

    parts = [p.text for p in doc.paragraphs if p.text and p.text.strip()]
    body = "\n\n".join(parts).strip()
    return sanitize_db_text(body)
