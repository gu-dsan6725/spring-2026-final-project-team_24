"""Paper extraction — upload PDF, extract text via MinerU, segment into concepts+edges.

Endpoints:
  POST /upload         — accepts PDF, returns segmented concepts + edges (LLM flow)
  POST /ingest-paper   — accepts PDF, runs extract → section-split → sub-chunk → embed
                         → write per-paper folder with .meta/ sidecars directly
                         into the caller's export_path (e.g. Obsidian vault) so the
                         vault is the single source of truth.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.schemas.item import PaperSegmentResult, SegmentedConcept, SegmentedEdge
from app.schemas.vectors import (
    IngestPaperRequest,
    IngestPaperResponse,
    IngestPaperSectionSummary,
)

router = APIRouter()
logger = logging.getLogger(__name__)


class PaperUploadRequest(BaseModel):
    pdf_base64: str
    filename: str = "paper.pdf"
    hint: str = ""


@router.post("/upload", response_model=PaperSegmentResult)
async def upload_paper(req: PaperUploadRequest) -> PaperSegmentResult:
    """Accept a base64-encoded PDF, extract text via MinerU, segment into concepts."""

    try:
        pdf_bytes = base64.b64decode(req.pdf_base64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid base64 PDF data: {exc}")

    logger.info(
        "[/extract/upload] filename=%r size=%d head=%r",
        req.filename,
        len(pdf_bytes),
        pdf_bytes[:12],
    )

    # Extract markdown via MinerU
    try:
        from app.services.extraction_service import extract_bytes, read_extracted_md

        stem = Path(req.filename).stem
        out_dir = extract_bytes(pdf_bytes, req.filename)

        md_text = read_extracted_md(str(out_dir), stem)
        if not md_text:
            head = pdf_bytes[:8]
            hint = ""
            if not pdf_bytes:
                hint = " (empty body)"
            elif not head.startswith(b"%PDF-"):
                hint = (
                    f" — upload is not a PDF (first bytes: {head!r}). "
                    "Re-check the file; PDFs must start with %PDF-."
                )
            else:
                hint = (
                    " — PDF header looks OK but PDFium could not parse it "
                    "(encrypted, damaged, scanned without OCR, or unsupported flavor). "
                    "Try a different PDF (e.g. an arXiv preprint) to confirm."
                )
            raise HTTPException(
                status_code=422,
                detail=f"MinerU produced no markdown for {req.filename!r}{hint}",
            )
    except ImportError:
        logger.warning("MinerU not installed — falling back to raw bytes decode")
        try:
            md_text = pdf_bytes.decode("utf-8", errors="replace")
        except Exception:
            raise HTTPException(status_code=422, detail="Could not extract text from PDF (MinerU not available).")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("MinerU extraction failed")
        raise HTTPException(status_code=500, detail=f"PDF extraction failed: {exc}")

    # Segment via LLM
    try:
        from app.ai.pipelines.paper_segmenter import segment_paper

        result = await segment_paper(md_text, hint=req.hint)
    except Exception as exc:
        logger.exception("Paper segmentation failed")
        raise HTTPException(status_code=500, detail=f"LLM segmentation failed: {exc}")

    concepts = [
        SegmentedConcept(
            title=c.get("title", "Untitled"),
            body_md=c.get("body_md", ""),
            content_type=c.get("content_type", "markdown"),
        )
        for c in result.get("concepts", [])
    ]

    edges = [
        SegmentedEdge(
            source_title=e.get("source_title", ""),
            target_title=e.get("target_title", ""),
            relationship_type=e.get("relationship_type", "prerequisite"),
            note=e.get("note", ""),
        )
        for e in result.get("edges", [])
    ]

    return PaperSegmentResult(
        concepts=concepts,
        edges=edges,
        raw_md=md_text[:5000],
    )


@router.post("/ingest-paper", response_model=IngestPaperResponse)
async def ingest_paper_endpoint(req: IngestPaperRequest) -> IngestPaperResponse:
    """Full paper ingestion: MinerU extract → section split → sub-chunk → embed → write + export.

    Produces a per-paper folder on disk with ``sections/*.md`` and ``.meta/``
    (local vectors + sidecar JSON per section, plus ``paper.json`` manifest).
    If Pinecone is configured, vectors are also upserted into
    ``user_{user_id}_docs``. If ``export_path`` (or settings.PAPER_EXPORT_DIR)
    is set, the finished paper folder is mirrored to that location.
    """
    try:
        pdf_bytes = base64.b64decode(req.pdf_base64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid base64 PDF data: {exc}")

    logger.info(
        "[/extract/ingest-paper] filename=%r size=%d head=%r user=%r",
        req.filename,
        len(pdf_bytes),
        pdf_bytes[:12],
        req.user_id,
    )

    try:
        from app.services.paper_index_service import ingest_paper

        result = await ingest_paper(
            pdf_bytes=pdf_bytes,
            filename=req.filename,
            user_id=req.user_id,
            export_path=req.export_path,
            force=req.force,
        )
    except ImportError as exc:
        logger.exception("Paper ingestion dependency missing")
        raise HTTPException(
            status_code=503,
            detail=f"Paper ingestion dependency missing: {exc}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Paper ingestion failed")
        raise HTTPException(status_code=500, detail=f"Paper ingestion failed: {exc}") from exc

    sections_summary = [
        IngestPaperSectionSummary(
            section_id=s.section.section_id,
            order=s.section.order,
            title=s.section.title,
            filename=s.section.filename,
            image_refs=s.section.image_refs,
            chunk_count=s.chunk_count,
        )
        for s in result.sections
    ]

    return IngestPaperResponse(
        doc_id=result.doc_id,
        stem=result.stem,
        paper_dir=str(Path(result.paper_dir).as_posix()),
        section_count=result.section_count,
        chunk_count=result.chunk_count,
        sections=sections_summary,
        pinecone_namespace=result.pinecone_namespace,
        pinecone_indexed=result.pinecone_indexed,
        exported_to=str(Path(result.exported_to).as_posix()) if result.exported_to else None,
        already_ingested=result.already_ingested,
    )
