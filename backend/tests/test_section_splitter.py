"""Tests for the paper section splitter."""

from __future__ import annotations

from app.ingest.section_splitter import (
    extract_image_refs,
    render_section_md,
    slugify,
    split_sections,
)


def test_slugify_basic():
    assert slugify("Introduction") == "introduction"
    assert slugify("3.1 Methods & Results") == "3-1-methods-results"
    assert slugify("") == "section"
    assert slugify("   !!! ") == "section"


def test_slugify_length_cap():
    s = slugify("a" * 200, max_len=20)
    assert len(s) == 20


def test_extract_image_refs_preserves_order_and_duplicates():
    body = (
        "Intro.\n\n"
        "![](images/a.jpg)\n"
        "Some text.\n"
        "![caption](images/b.png)\n"
        "Again: ![](images/a.jpg)\n"
    )
    refs = extract_image_refs(body)
    assert refs == ["images/a.jpg", "images/b.png", "images/a.jpg"]


def test_split_sections_basic():
    md = (
        "# Paper Title\n\n"
        "Abstract goes here.\n\n"
        "## Introduction\n\n"
        "Intro body ![](images/fig1.jpg) ends.\n\n"
        "## Method\n\n"
        "Step 1.\n\n"
        "### Details\n\n"
        "Nested detail.\n\n"
        "## Results\n\n"
        "Final numbers.\n"
    )
    secs = split_sections(md)
    titles = [s.title for s in secs]
    # Preamble (level 0) + 3 level-2 + 1 level-3
    assert titles[0] == "Preamble"
    assert "Introduction" in titles
    assert "Method" in titles
    assert "Details" in titles
    assert "Results" in titles
    assert secs[0].level == 0
    assert secs[titles.index("Details")].level == 3


def test_split_sections_image_refs_travel_with_section():
    md = (
        "## A\nbody a ![](images/a.png)\n\n"
        "## B\nbody b ![](images/b.png) ![](images/c.png)\n"
    )
    secs = split_sections(md)
    by_title = {s.title: s for s in secs}
    assert by_title["A"].image_refs == ["images/a.png"]
    assert by_title["B"].image_refs == ["images/b.png", "images/c.png"]


def test_split_sections_empty_returns_empty():
    assert split_sections("") == []
    assert split_sections("   \n\n  ") == []


def test_split_sections_no_headers_single_preamble():
    md = "Just a paragraph.\n\nAnother paragraph."
    secs = split_sections(md)
    assert len(secs) == 1
    assert secs[0].level == 0
    assert secs[0].title == "Preamble"


def test_split_sections_ids_stable_and_ordered():
    md = "## One\na\n\n## Two\nb\n\n## Three\nc\n"
    secs = split_sections(md)
    assert [s.section_id for s in secs] == ["sec_00", "sec_01", "sec_02"]
    assert [s.order for s in secs] == [0, 1, 2]


def test_render_section_md_preamble_adds_title_header():
    md = "## Method\nhello\n"
    secs = split_sections("intro text\n\n" + md)
    preamble = secs[0]
    out = render_section_md(preamble, doc_title="My Paper")
    assert out.startswith("# My Paper\n")
    assert "intro text" in out


def test_render_section_md_non_preamble_passes_through():
    md = "## Method\nhello world\n"
    secs = split_sections(md)
    out = render_section_md(secs[0])
    assert out.startswith("## Method")
    assert "hello world" in out


def test_char_ranges_cover_body_monotonically():
    md = "## A\nalpha\n\n## B\nbeta\n\n## C\ngamma\n"
    secs = split_sections(md)
    prev_end = 0
    for s in secs:
        start, end = s.char_range
        assert start >= prev_end
        assert end > start
        prev_end = end
