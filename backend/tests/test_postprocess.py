"""Tests for MinerU markdown post-processing.

Only tests safe, lossless format conversions (HTML table → pipe table).
LaTeX content is left as-is — MinerU owns the extraction, we own presentation format.
"""

from __future__ import annotations

from app.ingest.postprocess import (
    convert_html_tables_to_markdown,
    postprocess_md,
)


def test_html_table_to_markdown_simple():
    html = '<table><tr><td>A</td><td>B</td></tr><tr><td>1</td><td>2</td></tr></table>'
    result = convert_html_tables_to_markdown(html)
    assert "|" in result
    assert "<table>" not in result
    assert "A" in result
    assert "B" in result


def test_html_table_preserves_surrounding_text():
    text = "Before.\n\n<table><tr><td>X</td></tr></table>\n\nAfter."
    result = convert_html_tables_to_markdown(text)
    assert "Before." in result
    assert "After." in result
    assert "<table>" not in result


def test_html_table_with_rowspan():
    html = (
        '<table>'
        '<tr><td rowspan="2">Method</td><td>A</td></tr>'
        '<tr><td>B</td></tr>'
        '</table>'
    )
    result = convert_html_tables_to_markdown(html)
    lines = [l for l in result.strip().split("\n") if l.strip()]
    assert len(lines) == 3  # header + separator + data row


def test_html_table_with_colspan():
    html = (
        '<table>'
        '<tr><td colspan="2">Wide</td></tr>'
        '<tr><td>L</td><td>R</td></tr>'
        '</table>'
    )
    result = convert_html_tables_to_markdown(html)
    assert "Wide" in result
    assert "L" in result


def test_latex_content_preserved_in_cells():
    """LaTeX in table cells is passed through untouched."""
    html = (
        '<table><tr><td>Method</td><td>Score</td></tr>'
        '<tr><td>Ours</td><td>$3 1 . 7 ( + 8 . 7 ) $</td></tr></table>'
    )
    result = convert_html_tables_to_markdown(html)
    assert "<table>" not in result
    assert "$3 1 . 7 ( + 8 . 7 ) $" in result


def test_postprocess_only_converts_format():
    text = (
        "# Title\n\n"
        '<table><tr><td>Method</td><td>Score</td></tr>'
        '<tr><td>Ours</td><td>$3 1 . 7$</td></tr></table>\n\n'
        "Inline math $H^* = \\arg\\max$ stays."
    )
    result = postprocess_md(text)
    assert "<table>" not in result
    assert "| Method" in result
    assert "$3 1 . 7$" in result  # LaTeX preserved exactly
    assert "$H^*" in result       # inline math untouched


def test_on_real_extracted_file():
    """Verify post-processing cleans the actual Meta-Harness extraction."""
    from app.services.extraction_service import read_extracted_md

    md = read_extracted_md("data/extracted", "Meta-Harness")
    if md is None:
        return  # skip if extraction hasn't been run
    assert "<table>" not in md
    assert "| " in md
