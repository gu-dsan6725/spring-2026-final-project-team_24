"""Tests for paper ingestion orchestration.

MinerU, OpenAI, and Pinecone are all mocked — these tests verify the
on-disk layout, sidecar JSON shape, export copy behavior, and
idempotency logic.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.services import paper_index_service
from app.services.paper_index_service import compute_doc_id, ingest_paper

SAMPLE_MD = (
    "# Sample Paper\n\n"
    "Abstract text with a picture ![](images/abstract.png).\n\n"
    "## Introduction\n\n"
    "Background sentences. More words to make this section substantial. "
    "This continues for a while to produce at least one chunk boundary. " * 3
    + "\n\n"
    "## Method\n\n"
    "Step one ![](images/fig1.jpg). Step two. Step three. "
    "More method detail here. " * 5
    + "\n\n"
    "## Results\n\n"
    "Numbers and ![](images/plot.png) discussion.\n"
)


def _patch_extraction(
    md_text: str,
    extracted_dir: Path,
    stem: str,
    *,
    image_files: dict[str, bytes] | None = None,
):
    """Fake MinerU: writes the md under <extracted_dir>/<stem>/auto/.

    If ``image_files`` is provided (``{basename: bytes}``), the fake also
    writes those bytes into ``auto/images/<basename>`` so the plots copier
    has real files to find.
    """
    def fake_extract_bytes(raw, filename, *, output_dir=None, backend=None, lang="en"):
        out = Path(output_dir).resolve() if output_dir else extracted_dir
        auto = out / stem / "auto"
        auto.mkdir(parents=True, exist_ok=True)
        (auto / f"{stem}.md").write_text(md_text, encoding="utf-8")
        images_dir = auto / "images"
        images_dir.mkdir(exist_ok=True)
        for name, data in (image_files or {}).items():
            (images_dir / name).write_bytes(data)
        return out

    def fake_read_md(output_dir, paper_stem):
        p = Path(output_dir) / paper_stem / "auto" / f"{paper_stem}.md"
        return p.read_text(encoding="utf-8") if p.exists() else None

    return (
        patch(
            "app.services.paper_index_service.extract_bytes",
            side_effect=fake_extract_bytes,
        ),
        patch(
            "app.services.paper_index_service.read_extracted_md",
            side_effect=fake_read_md,
        ),
    )


@pytest.mark.asyncio
async def test_ingest_paper_writes_expected_folder_layout(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_index_service.settings, "EXTRACTED_DIR", str(tmp_path))
    monkeypatch.setattr(paper_index_service.settings, "DOC_CHUNK_SIZE", 400)
    monkeypatch.setattr(paper_index_service.settings, "DOC_CHUNK_OVERLAP", 50)
    monkeypatch.setattr(paper_index_service.settings, "PAPER_EXPORT_DIR", "")

    stem = "sample"
    filename = f"{stem}.pdf"
    pdf_bytes = b"%PDF-1.4 fake body bytes"

    fake_vectors = [[0.0] * 1536]  # reused per chunk via mock

    async def fake_embed(entries):
        return [[float(i)] * 1536 for i, _ in enumerate(entries)]

    p_extract, p_read = _patch_extraction(SAMPLE_MD, tmp_path, stem)

    with p_extract, p_read, patch(
        "app.services.paper_index_service.embedding_pipeline.embed_doc_chunks",
        new=AsyncMock(side_effect=fake_embed),
    ), patch(
        "app.services.paper_index_service.pinecone_db.pinecone_configured",
        return_value=False,
    ):
        result = await ingest_paper(
            pdf_bytes=pdf_bytes,
            filename=filename,
            user_id="alice",
        )

    paper_dir = tmp_path / stem
    assert result.paper_dir == paper_dir
    assert result.doc_id == compute_doc_id(pdf_bytes)
    assert result.section_count >= 3  # preamble + at least 3 sections
    assert result.chunk_count > 0
    assert result.pinecone_namespace is None
    assert result.pinecone_indexed == 0
    assert result.exported_to is None

    # Folder layout
    assert (paper_dir / "auto" / f"{stem}.md").exists()
    assert (paper_dir / "sections").is_dir()
    section_files = sorted((paper_dir / "sections").glob("section_*.md"))
    assert len(section_files) == result.section_count

    # .meta/ sidecars
    meta_dir = paper_dir / ".meta"
    assert (meta_dir / "paper.json").exists()
    for s in result.sections:
        assert (meta_dir / f"{s.section.section_id}.json").exists()
        # local vectors file should exist when we had at least one chunk
        if s.chunk_count > 0:
            assert (meta_dir / f"{s.section.section_id}.vectors.npy").exists()


@pytest.mark.asyncio
async def test_ingest_paper_records_image_refs_per_section(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_index_service.settings, "EXTRACTED_DIR", str(tmp_path))
    monkeypatch.setattr(paper_index_service.settings, "DOC_CHUNK_SIZE", 500)
    monkeypatch.setattr(paper_index_service.settings, "DOC_CHUNK_OVERLAP", 50)
    monkeypatch.setattr(paper_index_service.settings, "PAPER_EXPORT_DIR", "")

    stem = "paper2"
    pdf_bytes = b"content-v1"

    async def fake_embed(entries):
        return [[1.0] * 1536 for _ in entries]

    p_extract, p_read = _patch_extraction(SAMPLE_MD, tmp_path, stem)

    with p_extract, p_read, patch(
        "app.services.paper_index_service.embedding_pipeline.embed_doc_chunks",
        new=AsyncMock(side_effect=fake_embed),
    ), patch(
        "app.services.paper_index_service.pinecone_db.pinecone_configured",
        return_value=False,
    ):
        result = await ingest_paper(pdf_bytes=pdf_bytes, filename=f"{stem}.pdf", user_id="bob")

    meta_dir = tmp_path / stem / ".meta"
    by_section: dict[str, dict] = {}
    for sidecar in meta_dir.glob("sec_*.json"):
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        by_section[payload["section_id"]] = payload

    method_section = next(
        payload for payload in by_section.values() if payload["title"] == "Method"
    )
    assert "images/fig1.jpg" in method_section["image_refs"]

    preamble = next(
        payload for payload in by_section.values() if payload["order"] == 0
    )
    assert "images/abstract.png" in preamble["image_refs"]

    results_section = next(
        payload for payload in by_section.values() if payload["title"] == "Results"
    )
    assert "images/plot.png" in results_section["image_refs"]


@pytest.mark.asyncio
async def test_ingest_paper_builds_plots_folder_and_rewrites_refs(tmp_path, monkeypatch):
    """plots/ sibling of .meta/ should hold referenced images; section mds get ../plots/ refs."""
    monkeypatch.setattr(paper_index_service.settings, "EXTRACTED_DIR", str(tmp_path))
    monkeypatch.setattr(paper_index_service.settings, "DOC_CHUNK_SIZE", 500)
    monkeypatch.setattr(paper_index_service.settings, "DOC_CHUNK_OVERLAP", 50)
    monkeypatch.setattr(paper_index_service.settings, "PAPER_EXPORT_DIR", "")

    stem = "plots_paper"
    pdf_bytes = b"plots-v1"
    image_files = {
        "abstract.png": b"\x89PNG-abstract-bytes",
        "fig1.jpg": b"\xff\xd8\xff-fig1-bytes",
        "plot.png": b"\x89PNG-plot-bytes",
    }

    async def fake_embed(entries):
        return [[0.3] * 1536 for _ in entries]

    p_extract, p_read = _patch_extraction(
        SAMPLE_MD, tmp_path, stem, image_files=image_files
    )

    with p_extract, p_read, patch(
        "app.services.paper_index_service.embedding_pipeline.embed_doc_chunks",
        new=AsyncMock(side_effect=fake_embed),
    ), patch(
        "app.services.paper_index_service.pinecone_db.pinecone_configured",
        return_value=False,
    ):
        result = await ingest_paper(
            pdf_bytes=pdf_bytes, filename=f"{stem}.pdf", user_id="carol"
        )

    paper_dir = tmp_path / stem
    plots_dir = paper_dir / "plots"

    assert plots_dir.is_dir(), "plots/ folder should exist alongside .meta/"
    assert (plots_dir).parent == (paper_dir / ".meta").parent
    copied = sorted(p.name for p in plots_dir.iterdir())
    assert copied == ["abstract.png", "fig1.jpg", "plot.png"]

    for name, expected_bytes in image_files.items():
        assert (plots_dir / name).read_bytes() == expected_bytes

    for md_path in (paper_dir / "sections").glob("section_*.md"):
        body = md_path.read_text(encoding="utf-8")
        assert "](images/" not in body, f"old images/ ref leaked into {md_path.name}: {body!r}"
    any_rewritten = any(
        "](../plots/" in md.read_text(encoding="utf-8")
        for md in (paper_dir / "sections").glob("section_*.md")
    )
    assert any_rewritten, "at least one section should carry a rewritten ../plots/ ref"

    manifest = json.loads((paper_dir / ".meta" / "paper.json").read_text(encoding="utf-8"))
    assert manifest["plots_dir"] == "plots"
    assert sorted(manifest["plot_files"]) == ["abstract.png", "fig1.jpg", "plot.png"]

    for section in result.sections:
        assert "images/" in " ".join(section.section.image_refs) or not section.section.image_refs


@pytest.mark.asyncio
async def test_ingest_paper_exports_to_requested_path(tmp_path, monkeypatch):
    extracted = tmp_path / "extracted"
    vault = tmp_path / "vault"
    monkeypatch.setattr(paper_index_service.settings, "EXTRACTED_DIR", str(extracted))
    monkeypatch.setattr(paper_index_service.settings, "DOC_CHUNK_SIZE", 500)
    monkeypatch.setattr(paper_index_service.settings, "DOC_CHUNK_OVERLAP", 50)
    monkeypatch.setattr(paper_index_service.settings, "PAPER_EXPORT_DIR", "")

    stem = "export_paper"
    pdf_bytes = b"export-v1"

    async def fake_embed(entries):
        return [[0.5] * 1536 for _ in entries]

    p_extract, p_read = _patch_extraction(SAMPLE_MD, extracted, stem)

    with p_extract, p_read, patch(
        "app.services.paper_index_service.embedding_pipeline.embed_doc_chunks",
        new=AsyncMock(side_effect=fake_embed),
    ), patch(
        "app.services.paper_index_service.pinecone_db.pinecone_configured",
        return_value=False,
    ):
        result = await ingest_paper(
            pdf_bytes=pdf_bytes,
            filename=f"{stem}.pdf",
            user_id="alice",
            export_path=str(vault),
        )

    assert result.exported_to == (vault / stem).resolve()
    exported_dir = vault / stem
    assert (exported_dir / "sections").is_dir()
    assert (exported_dir / ".meta" / "paper.json").exists()
    assert (exported_dir / "auto").is_dir()


@pytest.mark.asyncio
async def test_ingest_paper_refuses_export_into_extraction_dir(tmp_path, monkeypatch):
    extracted = tmp_path / "extracted"
    monkeypatch.setattr(paper_index_service.settings, "EXTRACTED_DIR", str(extracted))
    monkeypatch.setattr(paper_index_service.settings, "DOC_CHUNK_SIZE", 500)
    monkeypatch.setattr(paper_index_service.settings, "DOC_CHUNK_OVERLAP", 50)
    monkeypatch.setattr(paper_index_service.settings, "PAPER_EXPORT_DIR", "")

    stem = "recursive"
    pdf_bytes = b"recursive-v1"

    async def fake_embed(entries):
        return [[0.1] * 1536 for _ in entries]

    p_extract, p_read = _patch_extraction(SAMPLE_MD, extracted, stem)

    with p_extract, p_read, patch(
        "app.services.paper_index_service.embedding_pipeline.embed_doc_chunks",
        new=AsyncMock(side_effect=fake_embed),
    ), patch(
        "app.services.paper_index_service.pinecone_db.pinecone_configured",
        return_value=False,
    ):
        with pytest.raises(ValueError, match="inside the paper"):
            await ingest_paper(
                pdf_bytes=pdf_bytes,
                filename=f"{stem}.pdf",
                user_id="alice",
                export_path=str(extracted / stem),
            )


@pytest.mark.asyncio
async def test_ingest_paper_is_idempotent_by_content_hash(tmp_path, monkeypatch):
    extracted = tmp_path / "extracted"
    monkeypatch.setattr(paper_index_service.settings, "EXTRACTED_DIR", str(extracted))
    monkeypatch.setattr(paper_index_service.settings, "DOC_CHUNK_SIZE", 500)
    monkeypatch.setattr(paper_index_service.settings, "DOC_CHUNK_OVERLAP", 50)
    monkeypatch.setattr(paper_index_service.settings, "PAPER_EXPORT_DIR", "")

    stem = "idem"
    pdf_bytes = b"same-bytes"
    embed_mock = AsyncMock(side_effect=lambda entries: [[0.1] * 1536 for _ in entries])

    p_extract, p_read = _patch_extraction(SAMPLE_MD, extracted, stem)

    with p_extract, p_read, patch(
        "app.services.paper_index_service.embedding_pipeline.embed_doc_chunks",
        new=embed_mock,
    ), patch(
        "app.services.paper_index_service.pinecone_db.pinecone_configured",
        return_value=False,
    ):
        first = await ingest_paper(
            pdf_bytes=pdf_bytes,
            filename=f"{stem}.pdf",
            user_id="alice",
        )
        second = await ingest_paper(
            pdf_bytes=pdf_bytes,
            filename=f"{stem}.pdf",
            user_id="alice",
        )

    assert first.doc_id == second.doc_id
    # On the idempotent second call we short-circuit — embedding is NOT called again.
    assert embed_mock.await_count == 1


@pytest.mark.asyncio
async def test_ingest_paper_pinecone_upsert_when_configured(tmp_path, monkeypatch):
    extracted = tmp_path / "extracted"
    monkeypatch.setattr(paper_index_service.settings, "EXTRACTED_DIR", str(extracted))
    monkeypatch.setattr(paper_index_service.settings, "DOC_CHUNK_SIZE", 500)
    monkeypatch.setattr(paper_index_service.settings, "DOC_CHUNK_OVERLAP", 50)
    monkeypatch.setattr(paper_index_service.settings, "PAPER_EXPORT_DIR", "")

    stem = "pc"
    pdf_bytes = b"pinecone-v1"

    async def fake_embed(entries):
        return [[0.2] * 1536 for _ in entries]

    upsert_mock = AsyncMock(return_value=7)

    p_extract, p_read = _patch_extraction(SAMPLE_MD, extracted, stem)

    with p_extract, p_read, patch(
        "app.services.paper_index_service.embedding_pipeline.embed_doc_chunks",
        new=AsyncMock(side_effect=fake_embed),
    ), patch(
        "app.services.paper_index_service.embedding_pipeline.index_user_doc_chunks",
        new=upsert_mock,
    ), patch(
        "app.services.paper_index_service.pinecone_db.pinecone_configured",
        return_value=True,
    ):
        result = await ingest_paper(
            pdf_bytes=pdf_bytes,
            filename=f"{stem}.pdf",
            user_id="alice",
        )

    assert result.pinecone_namespace == "user_alice_docs"
    assert result.pinecone_indexed == 7
    upsert_mock.assert_awaited_once()
    kwargs = upsert_mock.await_args.kwargs
    # Pipeline should pass precomputed vectors through to avoid double-embedding.
    assert "vectors" in kwargs
    assert len(kwargs["vectors"]) == len(upsert_mock.await_args.args[1])
