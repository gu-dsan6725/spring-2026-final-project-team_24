"""Post-processing for MinerU markdown output.

Only performs safe, lossless format conversions — never guesses at
structural corrections that could turn correct data into wrong data.

Currently:
  HTML tables → markdown pipe tables  (1:1 format swap, no data changes)
"""

from __future__ import annotations

import re
from html.parser import HTMLParser


def postprocess_md(text: str) -> str:
    """Apply safe format fixes to MinerU markdown output."""
    text = convert_html_tables_to_markdown(text)
    return text


# ---------------------------------------------------------------------------
# 1. HTML table → markdown pipe table
# ---------------------------------------------------------------------------

class _TableParser(HTMLParser):
    """Minimal HTML table parser that extracts rows of cell text."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._current_row: list[str] = []
        self._current_cell: list[str] = []
        self._in_cell = False
        self._rowspans: dict[int, tuple[str, int]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._current_row = []
        elif tag in ("td", "th"):
            self._in_cell = True
            self._current_cell = []
            attr_dict = dict(attrs)
            self._colspan = int(attr_dict.get("colspan", "1"))
            self._rowspan = int(attr_dict.get("rowspan", "1"))

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th"):
            self._in_cell = False
            cell_text = "".join(self._current_cell).strip()
            col_idx = len(self._current_row)
            while col_idx in self._rowspans:
                span_text, remaining = self._rowspans[col_idx]
                self._current_row.append(span_text)
                if remaining <= 1:
                    del self._rowspans[col_idx]
                else:
                    self._rowspans[col_idx] = (span_text, remaining - 1)
                col_idx = len(self._current_row)
            for _ in range(self._colspan):
                self._current_row.append(cell_text)
            if self._rowspan > 1:
                for c in range(self._colspan):
                    self._rowspans[col_idx - self._colspan + c + 1] = (
                        cell_text,
                        self._rowspan - 1,
                    )
        elif tag == "tr":
            while len(self._current_row) in self._rowspans:
                col_idx = len(self._current_row)
                span_text, remaining = self._rowspans[col_idx]
                self._current_row.append(span_text)
                if remaining <= 1:
                    del self._rowspans[col_idx]
                else:
                    self._rowspans[col_idx] = (span_text, remaining - 1)
            self.rows.append(self._current_row)

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._current_cell.append(data)


def _rows_to_md_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    ncols = max(len(r) for r in rows)
    for r in rows:
        while len(r) < ncols:
            r.append("")

    widths = [
        max(len(rows[r][c]) for r in range(len(rows)))
        for c in range(ncols)
    ]
    widths = [max(w, 3) for w in widths]

    lines: list[str] = []
    for i, row in enumerate(rows):
        cells = [cell.ljust(widths[j]) for j, cell in enumerate(row)]
        lines.append("| " + " | ".join(cells) + " |")
        if i == 0:
            lines.append("| " + " | ".join("-" * w for w in widths) + " |")
    return "\n".join(lines)


_HTML_TABLE_RE = re.compile(r"<table>.*?</table>", re.DOTALL | re.IGNORECASE)


def convert_html_tables_to_markdown(text: str) -> str:
    """Replace inline HTML tables with markdown pipe tables."""
    def _replace(m: re.Match) -> str:
        parser = _TableParser()
        try:
            parser.feed(m.group(0))
        except Exception:
            return m.group(0)
        if not parser.rows:
            return m.group(0)
        return "\n" + _rows_to_md_table(parser.rows) + "\n"

    return _HTML_TABLE_RE.sub(_replace, text)
