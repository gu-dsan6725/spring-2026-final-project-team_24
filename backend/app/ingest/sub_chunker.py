"""Deterministic character-window sub-chunker.

Used inside each section produced by :mod:`app.ingest.section_splitter` to
split a section body into smaller windows, each of which gets its own
embedding. We keep this mechanical (no tokenizer, no LLM) so re-ingesting
the same paper produces identical chunks.

Windows snap to a whitespace boundary near the hard cut-off when possible
to avoid splitting mid-word. Overlap is honored, but never negative and
never >= chunk_size.
"""

from __future__ import annotations

from dataclasses import dataclass

SNAP_TOLERANCE_DEFAULT = 80  # chars we're willing to walk back to find whitespace


@dataclass(frozen=True)
class SubChunk:
    """One sub-chunk of a section body.

    ``char_range`` is a (start, end) pair in the section body's char space
    (end-exclusive, same convention as Python slicing).
    """

    index: int
    text: str
    char_range: tuple[int, int]


def _snap_back_to_whitespace(text: str, cut: int, tolerance: int) -> int:
    """Return an adjusted cut index that lands on a whitespace char when possible.

    Walks back up to ``tolerance`` chars looking for a ``\\n`` (preferred) or
    any whitespace. If none found, returns the original ``cut``.
    """
    if cut >= len(text):
        return len(text)
    lo = max(0, cut - tolerance)
    # Prefer paragraph/newline break.
    nl = text.rfind("\n", lo, cut)
    if nl != -1 and nl + 1 > lo:
        return nl + 1
    ws = -1
    for i in range(cut - 1, lo - 1, -1):
        if text[i].isspace():
            ws = i + 1
            break
    return ws if ws != -1 else cut


def chunk_text(
    text: str,
    *,
    chunk_size: int,
    overlap: int,
    snap_tolerance: int = SNAP_TOLERANCE_DEFAULT,
) -> list[SubChunk]:
    """Split ``text`` into overlapping character windows.

    - ``chunk_size`` must be > 0.
    - ``overlap`` must be >= 0 and < chunk_size.
    - Empty or whitespace-only input returns ``[]``.
    - The last chunk is emitted even if shorter than ``chunk_size``.
    """
    if chunk_size <= 0:
        raise ValueError(f"chunk_size must be > 0, got {chunk_size}")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError(
            f"overlap must be in [0, chunk_size); got overlap={overlap}, chunk_size={chunk_size}"
        )

    body = text
    n = len(body)
    if n == 0 or not body.strip():
        return []

    out: list[SubChunk] = []
    idx = 0
    start = 0
    step = chunk_size - overlap  # guaranteed >= 1

    while start < n:
        hard_end = min(start + chunk_size, n)
        if hard_end < n:
            end = _snap_back_to_whitespace(body, hard_end, snap_tolerance)
            # If snapping didn't actually advance past start, fall back to hard cut
            # to guarantee progress.
            if end <= start:
                end = hard_end
        else:
            end = n

        window = body[start:end].strip()
        if window:
            out.append(SubChunk(index=idx, text=window, char_range=(start, end)))
            idx += 1

        if end >= n:
            break
        # Next start walks forward by ``step`` from the un-snapped anchor.
        next_start = start + step
        # Keep forward progress even if snapping rewound end behind next_start.
        start = max(next_start, end - overlap) if end > start else next_start

    return out
