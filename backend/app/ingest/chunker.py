# Adapted from: vendor/yubo/app/ingest/chunk.py
"""Content chunker — split documents into concept-sized sections.

Prefers Markdown ``##`` (or deeper) headings as split points.
Falls back to paragraph-boundary splitting when no headings are found.
"""

from __future__ import annotations

import re

MAX_TITLE = 512
MAX_CHUNKS = 80
MAX_BODY_PER_CHUNK = 100_000


def chunk_sections(raw: str) -> list[tuple[str, str]]:
    """Split text into ``(title, body)`` pairs.

    Returns at most ``MAX_CHUNKS`` sections.
    """
    text = raw.strip()
    if not text:
        return []

    if not re.search(r"(?m)^#{2,}\s+", text):
        return _split_paragraphs(text)

    lines = text.split("\n")
    chunks: list[tuple[str, str]] = []
    current_title = "Document"
    buf: list[str] = []
    header_re = re.compile(r"^#{2,}\s+(.*)$")

    def flush() -> None:
        body = "\n".join(buf).strip()
        buf.clear()
        if body:
            chunks.append((current_title[:MAX_TITLE], body[:MAX_BODY_PER_CHUNK]))

    for line in lines:
        m = header_re.match(line.strip())
        if m:
            flush()
            title = (m.group(1) or "Section").strip() or "Section"
            current_title = title[:MAX_TITLE]
        else:
            buf.append(line)
    flush()

    out = chunks[:MAX_CHUNKS]
    return out if out else _split_paragraphs(text)


def _split_paragraphs(text: str) -> list[tuple[str, str]]:
    parts = [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]
    if not parts:
        return []
    out: list[tuple[str, str]] = []
    for i, p in enumerate(parts[:MAX_CHUNKS]):
        title = f"Part {i + 1}"
        out.append((title[:MAX_TITLE], p[:MAX_BODY_PER_CHUNK]))
    return out
