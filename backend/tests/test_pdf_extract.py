"""Tests for PDF extraction via MinerU (app.services.extraction_service)."""

from __future__ import annotations

import os

import pytest

from app.services.extraction_service import (
    extract_file,
    list_extracted_images,
    read_extracted_md,
)


DATA_DIR = "data"
OUTPUT_DIR = "data/extracted"


@pytest.fixture(scope="module")
def extracted():
    """Run extraction once for the module, reuse across tests."""
    out = extract_file(
        f"{DATA_DIR}/Meta-Harness.pdf",
        output_dir=OUTPUT_DIR,
        backend="pipeline",
    )
    return str(out)


def test_extraction_produces_md(extracted):
    md = read_extracted_md(extracted, "Meta-Harness")
    assert md is not None
    assert len(md) > 500
    assert "Meta-Harness" in md


def test_extraction_produces_images(extracted):
    images = list_extracted_images(extracted, "Meta-Harness")
    assert len(images) > 0
    for img_path in images:
        assert os.path.isfile(img_path)


def test_md_contains_tables(extracted):
    md = read_extracted_md(extracted, "Meta-Harness")
    assert md is not None
    assert "<table>" in md or "|" in md


def test_md_contains_formulas(extracted):
    md = read_extracted_md(extracted, "Meta-Harness")
    assert md is not None
    assert "$$" in md or "\\(" in md or "$" in md


def test_md_contains_image_refs(extracted):
    md = read_extracted_md(extracted, "Meta-Harness")
    assert md is not None
    assert "![" in md
