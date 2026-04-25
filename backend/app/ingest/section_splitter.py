"""Section-level splitter for MinerU-extracted paper markdown.

Takes the whole-paper markdown and partitions it at level-2+ headers into
a chain of smaller section markdowns. Each section keeps its original
MinerU image references verbatim (`![](images/...)`) and we also extract
them into a structured list for downstream metadata.

Distinct from ``app/ingest/chunker.py::chunk_sections`` (which returns
in-memory ``(title, body)`` tuples for concept extraction). Here we emit
richer ``Section`` records with order, stable id, slug, char range, and
image-ref manifest — suitable for writing one md file per section plus a
sidecar JSON.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_TITLE = 512
MAX_SECTIONS = 200

_HEADER_RE = re.compile(r"^(#{2,6})\s+(.*)$")
_IMAGE_REF_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(text: str, *, max_len: int = 60) -> str:
    """Lowercase, hyphenate, strip non-alnum. Deterministic for stable filenames."""
    s = text.strip().lower()
    s = _SLUG_STRIP.sub("-", s).strip("-")
    if not s:
        s = "section"
    return s[:max_len].rstrip("-") or "section"


def extract_image_refs(body: str) -> list[str]:
    """Return the list of image targets referenced by ``![alt](target)`` in order.

    Duplicates are kept (a paper can legitimately reference the same figure twice).
    """
    return [m.group(1).strip() for m in _IMAGE_REF_RE.finditer(body)]


def rewrite_image_refs(body: str, mapping: dict[str, str]) -> str:
    """Replace ``![alt](target)`` references according to ``mapping``.

    Only exact target strings present as keys in ``mapping`` are rewritten;
    unknown targets (e.g. remote URLs) pass through unchanged. Alt text is
    preserved verbatim.
    """
    if not mapping:
        return body

    def _sub(m: re.Match[str]) -> str:
        target = m.group(1).strip()
        new_target = mapping.get(target)
        if new_target is None:
            return m.group(0)
        # rebuild with the original alt-text prefix, replacing only the (target)
        prefix = m.group(0)[: m.start(1) - m.start(0)]
        suffix = m.group(0)[m.end(1) - m.start(0) :]
        return f"{prefix}{new_target}{suffix}"

    return _IMAGE_REF_RE.sub(_sub, body)


@dataclass
class Section:
    """One section produced by the splitter.

    ``char_range`` is the (start, end) span in the original whole-paper md
    (end-exclusive). ``section_id`` is stable for the section's order (not a
    content hash) — we keep content hashing for chunks.
    """

    order: int
    section_id: str
    title: str
    slug: str
    level: int  # header depth: 2 for ##, 3 for ###, etc. 0 = pre-first-header preamble.
    body_md: str
    char_range: tuple[int, int]
    image_refs: list[str] = field(default_factory=list)

    @property
    def filename(self) -> str:
        return f"section_{self.order:02d}__{self.slug}.md"


def split_sections(markdown: str) -> list[Section]:
    """Split paper markdown into ``Section`` records at ``##``+ headers.

    Preamble (anything before the first ``##``) is emitted as section 0 with
    title ``"Preamble"`` if non-empty. Level-1 (``#``) headers are treated as
    preamble content — typically they're the paper title and we don't want to
    re-emit the whole paper under one section.
    """
    text = markdown.rstrip()
    if not text.strip():
        return []

    lines = text.split("\n")

    # Walk lines, record section boundaries with char offsets.
    # We reconstruct char offsets by summing line lengths + newline terminator.
    boundaries: list[dict] = []  # each: {start_line, start_char, level, title}
    current = {"start_line": 0, "start_char": 0, "level": 0, "title": "Preamble"}
    char_cursor = 0
    for i, line in enumerate(lines):
        m = _HEADER_RE.match(line)
        if m:
            boundaries.append({**current, "end_line": i, "end_char": char_cursor})
            current = {
                "start_line": i,
                "start_char": char_cursor,
                "level": len(m.group(1)),
                "title": (m.group(2) or "Section").strip() or "Section",
            }
        char_cursor += len(line) + 1  # +1 for the '\n' separator
    boundaries.append({**current, "end_line": len(lines), "end_char": len(text)})

    sections: list[Section] = []
    order = 0
    for b in boundaries:
        start_char = b["start_char"]
        end_char = b["end_char"]
        body = text[start_char:end_char].rstrip()
        if not body.strip():
            continue
        # For non-preamble sections, strip the header line from the top of the body
        # so the body doesn't duplicate the title. We keep the header inside the
        # emitted md file (below) so readers see it.
        title = b["title"][:MAX_TITLE]
        sections.append(
            Section(
                order=order,
                section_id=f"sec_{order:02d}",
                title=title,
                slug=slugify(title),
                level=b["level"],
                body_md=body,
                char_range=(start_char, end_char),
                image_refs=extract_image_refs(body),
            )
        )
        order += 1
        if order >= MAX_SECTIONS:
            break

    return sections


def render_section_md(section: Section, *, doc_title: str | None = None) -> str:
    """Render a section as a standalone md file.

    If the section's body already begins with a header line (which it does
    for non-preamble sections), we pass the body through unchanged. For
    preamble (level 0), we add a leading ``# {doc_title or 'Preamble'}``
    header so the file is navigable on its own.
    """
    if section.level == 0:
        title = doc_title or section.title
        return f"# {title}\n\n{section.body_md}\n"
    return f"{section.body_md}\n"
