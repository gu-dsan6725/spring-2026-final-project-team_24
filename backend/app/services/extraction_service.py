# Adapted from: vendor/mineru/mineru/cli/common.py (do_parse API)
"""Document extraction service — wraps MinerU's do_parse for local use.

Usage::

    from app.services.extraction_service import extract_file

    result = extract_file("data/Meta-Harness.pdf")
    # Output lands in data/extracted/Meta-Harness/auto/
    #   ├── Meta-Harness.md            ← post-processed (pipe tables)
    #   ├── images/
    #   └── Meta-Harness_content_list.json
"""

from __future__ import annotations

import os
import logging
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


_VALID_MINERU_BACKEND_PREFIXES = ("pipeline", "vlm-", "hybrid-")


def _normalize_mineru_backend(be: str) -> str:
    """Validate + coerce the configured MinerU backend.

    MinerU's ``do_parse`` only recognizes exactly ``"pipeline"`` or any
    prefix ``"vlm-"`` / ``"hybrid-"``. Anything else (e.g. the
    historically-shipped default ``"auto"``) falls through every branch
    and silently produces no output. We log a clear warning and coerce
    to ``"pipeline"`` — the safe, CPU-capable default — rather than let
    users hit the silent no-op.
    """
    if be == "pipeline" or be.startswith(("vlm-", "hybrid-")):
        return be
    logger.error(
        "Configured MINERU_BACKEND=%r is not a valid MinerU backend. "
        "Valid values: 'pipeline', 'vlm-<engine>', or 'hybrid-<engine>'. "
        "Falling back to 'pipeline' (otherwise do_parse silently produces no output).",
        be,
    )
    return "pipeline"


def _postprocess_all_md(directory: Path) -> None:
    """Post-process every ``.md`` under *directory* in place.

    MinerU emits markdown with HTML tables inline; our postprocessor
    rewrites those to pipe tables for cleaner rendering. We also
    opportunistically delete any legacy ``<stem>.raw.md`` files left
    behind by older builds that kept a raw backup — the post-processor
    is deterministic, so the duplicate adds only clutter.
    """
    from app.ingest.postprocess import postprocess_md

    for root, _dirs, files in os.walk(directory):
        for f in files:
            p = Path(root, f)
            if f.endswith(".raw.md"):
                try:
                    p.unlink()
                    logger.info("Removed legacy raw md %s", p)
                except OSError:
                    pass
                continue
            if f.endswith(".md"):
                raw_text = p.read_text(encoding="utf-8")
                cleaned = postprocess_md(raw_text)
                if cleaned != raw_text:
                    p.write_text(cleaned, encoding="utf-8")
                    logger.info("Post-processed md %s", p)


def extract_file(
    input_path: str,
    *,
    output_dir: str | None = None,
    backend: str | None = None,
    lang: str = "en",
) -> Path:
    """Extract a PDF/image/docx via MinerU and write .md + images to disk.

    Returns the output directory containing the extracted files.
    """
    from mineru.cli.common import do_parse, read_fn
    from mineru.utils.enum_class import MakeMode

    input_path = str(Path(input_path).resolve())
    stem = Path(input_path).stem
    suffix = Path(input_path).suffix.lstrip(".").lower()
    out = Path(output_dir or settings.EXTRACTED_DIR).resolve()
    os.makedirs(out, exist_ok=True)

    pdf_bytes = read_fn(input_path, file_suffix=suffix)
    be = _normalize_mineru_backend(backend or settings.MINERU_BACKEND)

    do_parse(
        output_dir=str(out),
        pdf_file_names=[stem],
        pdf_bytes_list=[pdf_bytes],
        p_lang_list=[lang],
        backend=be,
        parse_method="auto",
        formula_enable=True,
        table_enable=True,
        f_draw_layout_bbox=False,
        f_draw_span_bbox=False,
        f_dump_md=True,
        f_dump_middle_json=False,
        f_dump_model_output=False,
        f_dump_orig_pdf=False,
        f_dump_content_list=True,
        f_make_md_mode=MakeMode.MM_MD,
    )

    _postprocess_all_md(out)
    logger.info("Extracted %s → %s", input_path, out)
    return out


def normalize_pdf_bytes(raw: bytes) -> bytes | None:
    """Rewrite a PDF using PyMuPDF to sanitize it for PDFium/MinerU.

    Many real-world PDFs (ACM/IEEE/Springer, scanner outputs, LaTeX exports
    with odd object streams) trip up PDFium's strict parser even though
    they open fine in Chrome, Acrobat, or PyMuPDF. Re-serializing them
    via PyMuPDF with ``garbage=4, deflate=True, clean=True`` usually
    produces a byte-for-byte different PDF with the same content that
    PDFium can parse.

    Returns the normalized bytes on success, or ``None`` if PyMuPDF
    itself can't open the file (at which point the PDF is likely
    genuinely corrupt / encrypted without a password).
    """
    try:
        import pymupdf  # type: ignore
    except Exception:
        try:
            import fitz as pymupdf  # type: ignore
        except Exception as err:
            logger.warning("pymupdf not available for PDF normalization: %s", err)
            return None

    try:
        doc = pymupdf.open(stream=raw, filetype="pdf")
    except Exception as err:
        logger.warning("PyMuPDF could not open PDF for normalization: %s", err)
        return None

    try:
        if getattr(doc, "is_encrypted", False):
            try:
                ok = doc.authenticate("")
            except Exception:
                ok = 0
            if not ok:
                logger.warning(
                    "PDF is encrypted and empty password failed; cannot normalize."
                )
                doc.close()
                return None

        try:
            page_count = doc.page_count
        except Exception:
            page_count = -1
        out = doc.tobytes(garbage=4, deflate=True, clean=True)
        logger.warning(
            "PyMuPDF normalized PDF: %d pages, %d bytes → %d bytes",
            page_count,
            len(raw),
            len(out),
        )
        return out
    except Exception as err:
        logger.warning("PyMuPDF normalization failed: %s", err)
        return None
    finally:
        try:
            doc.close()
        except Exception:
            pass


def extract_bytes(
    raw: bytes,
    filename: str,
    *,
    output_dir: str | None = None,
    backend: str | None = None,
    lang: str = "en",
) -> Path:
    """Extract from in-memory bytes (e.g. upload). Same output as extract_file."""
    from mineru.cli.common import do_parse
    from mineru.utils.enum_class import MakeMode

    stem = Path(filename).stem
    out = Path(output_dir or settings.EXTRACTED_DIR).resolve()
    os.makedirs(out, exist_ok=True)
    be = _normalize_mineru_backend(backend or settings.MINERU_BACKEND)
    logger.info(
        "extract_bytes: filename=%r stem=%r backend=%r size=%d → %s",
        filename,
        stem,
        be,
        len(raw),
        out,
    )

    do_parse(
        output_dir=str(out),
        pdf_file_names=[stem],
        pdf_bytes_list=[raw],
        p_lang_list=[lang],
        backend=be,
        parse_method="auto",
        formula_enable=True,
        table_enable=True,
        f_draw_layout_bbox=False,
        f_draw_span_bbox=False,
        f_dump_md=True,
        f_dump_middle_json=False,
        f_dump_model_output=False,
        f_dump_orig_pdf=False,
        f_dump_content_list=True,
        f_make_md_mode=MakeMode.MM_MD,
    )

    _postprocess_all_md(out)
    logger.info("Extracted %s → %s", filename, out)
    return out


def read_extracted_md(output_dir: str, stem: str) -> str | None:
    """Read the .md output from a previous extraction.

    Files are post-processed at extraction time, but we apply it again
    defensively in case the file was extracted before the fix existed.
    """
    from app.ingest.postprocess import postprocess_md

    target = f"{stem}.md"
    md_candidates: list[str] = []
    for root, _dirs, files in os.walk(output_dir):
        for f in files:
            if f == target:
                raw = Path(root, f).read_text(encoding="utf-8")
                return postprocess_md(raw)
            if f.endswith(".md") and not f.endswith(".raw.md"):
                md_candidates.append(os.path.join(root, f))

    if md_candidates:
        logger.warning(
            "read_extracted_md: no exact match for %r under %s; "
            "found other .md files: %s",
            target,
            output_dir,
            md_candidates[:5],
        )
    return None


def list_extracted_images(output_dir: str, stem: str) -> list[str]:
    """List image file paths from a previous extraction."""
    images: list[str] = []
    for root, _dirs, files in os.walk(output_dir):
        if os.path.basename(root) == "images":
            for f in sorted(files):
                images.append(os.path.join(root, f))
    return images
