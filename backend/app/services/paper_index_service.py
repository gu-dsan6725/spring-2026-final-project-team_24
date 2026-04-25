"""Paper ingestion orchestration.

Runs the full pipeline for one paper:

1. MinerU extract → ``<paper_root>/auto/{stem.md, images/, stem_content_list.json}``
2. Split the whole-paper md at ``##``+ headers → ``sections/section_NN__<slug>.md``
3. (Optional) LLM link-architect: propose typed directed edges between
   sections and assign each section a topological ``depth`` for the
   item-generation scheduler. Persisted to ``.meta/edges.json`` and the
   per-section frontmatter. Gated by ``settings.INGEST_BUILD_GRAPH``.
4. Sub-chunk each section body into overlapping char windows
5. Embed every chunk once (OpenAI)
6. Persist per-section sidecar JSON + local ``.npy`` vectors under ``.meta/``
7. Upsert vectors to Pinecone namespace ``user_{user_id}_docs`` (if configured)

**Single source of truth.** When ``export_path`` (or ``settings.PAPER_EXPORT_DIR``)
is set we write the paper folder directly inside it — typically the user's
Obsidian vault — instead of producing a copy inside ``data/extracted/``
and then mirroring. This means *deleting the paper folder from the vault
actually deletes the paper*: the next ingest genuinely re-runs because the
idempotency check (``.meta/paper.json``) has nothing to match. When no
``export_path`` is supplied we fall back to ``data/extracted/<stem>/``.

Paper folder layout produced::

    <paper_root>/<stem>/
    ├── <stem>__index.md              ← hub note, wikilinks to every section
    ├── auto/                         ← MinerU output (unchanged, canonical source)
    │   ├── <stem>.md                 ← whole-paper post-processed md
    │   ├── <stem>_content_list.json
    │   └── images/
    ├── sections/
    │   ├── section_00__preamble.md   ← inline refs rewritten to ../plots/<name>
    │   ├── section_01__introduction.md
    │   └── ...
    ├── plots/                        ← images actually referenced by sections (deduped)
    │   ├── figure-1.jpg
    │   └── ...
    └── .meta/                        ← hidden in Obsidian's tree; keeps the vault clean
        ├── paper.json                ← incl. per-section ``depth`` + graph summary
        ├── edges.json                ← LLM-built dependency graph (only if INGEST_BUILD_GRAPH)
        ├── sec_00.json               ← incl. ``depth`` field for the scheduler
        ├── sec_00.vectors.npy
        └── ...

Vector ids pushed to Pinecone: ``doc_{doc_id}::sec_NN::c{idx}``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.ai.pipelines import embedding_pipeline
from app.ai.pipelines.graph_builder import GraphResult, build_section_graph
from app.ai.providers.openai_embeddings import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL
from app.config import settings
from app.db import pinecone as pinecone_db
from app.ingest.section_splitter import (
    Section,
    render_section_md,
    rewrite_image_refs,
    split_sections,
)
from app.ingest.sub_chunker import SubChunk, chunk_text
from app.schemas.vectors import DocChunkIndexEntry
from app.services.extraction_service import (
    extract_bytes,
    normalize_pdf_bytes,
    read_extracted_md,
)

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def compute_doc_id(pdf_bytes: bytes) -> str:
    """Stable doc id from content hash (first 16 hex chars of sha256)."""
    return hashlib.sha256(pdf_bytes).hexdigest()[:16]


@dataclass
class IngestedChunk:
    section_id: str
    chunk_index: int
    text: str
    char_range: tuple[int, int]


@dataclass
class IngestedSection:
    section: Section
    chunks: list[IngestedChunk]

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)


@dataclass
class IngestResult:
    doc_id: str
    stem: str
    paper_dir: Path
    sections: list[IngestedSection]
    pinecone_namespace: str | None
    pinecone_indexed: int
    exported_to: Path | None
    already_ingested: bool = False

    @property
    def section_count(self) -> int:
        return len(self.sections)

    @property
    def chunk_count(self) -> int:
        return sum(s.chunk_count for s in self.sections)


# ---------------------------------------------------------------------------
# Disk writers
# ---------------------------------------------------------------------------


PLOTS_DIRNAME = "plots"
_EXTERNAL_REF_RE = ("http://", "https://", "data:", "ftp://", "//")


def _is_external_ref(target: str) -> bool:
    return any(target.lower().startswith(p) for p in _EXTERNAL_REF_RE)


def _build_plots_folder(
    paper_dir: Path,
    sections: list[Section],
) -> tuple[dict[str, str], list[str]]:
    """Copy images referenced by sections into ``paper_dir/plots/`` (deduped).

    Returns a ``(mapping, plot_basenames)`` tuple where:
      * ``mapping`` is ``{original_ref -> "../plots/<basename>"}`` suitable for
        :func:`rewrite_image_refs` applied to section bodies. Only refs whose
        source file was located under MinerU's output are included; external
        URLs and missing files pass through unchanged.
      * ``plot_basenames`` is the sorted list of files now present in ``plots/``.

    MinerU typically emits refs like ``images/abc.jpg``; some pipelines emit
    ``auto/images/abc.jpg`` or bare basenames. We resolve each ref against
    ``paper_dir`` and, if that misses, against ``paper_dir/auto`` as a fallback.
    """
    plots_dir = paper_dir / PLOTS_DIRNAME
    mapping: dict[str, str] = {}
    copied: set[str] = set()

    unique_refs: list[str] = []
    seen: set[str] = set()
    for sec in sections:
        for ref in sec.image_refs:
            if ref in seen:
                continue
            seen.add(ref)
            unique_refs.append(ref)

    for ref in unique_refs:
        if not ref or _is_external_ref(ref):
            continue
        candidates = [
            (paper_dir / ref).resolve(),
            (paper_dir / "auto" / ref).resolve(),
        ]
        src = next((c for c in candidates if c.is_file()), None)
        if src is None:
            logger.warning("Image ref %r referenced in section md not found on disk; skipping copy.", ref)
            continue
        basename = src.name
        dst = plots_dir / basename
        if basename not in copied:
            plots_dir.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(src, dst)
            except OSError as exc:
                logger.warning("Failed to copy %s -> %s: %s", src, dst, exc)
                continue
            copied.add(basename)
        mapping[ref] = f"../{PLOTS_DIRNAME}/{basename}"

    return mapping, sorted(copied)


def _section_stem(sec: Section) -> str:
    """Filename without ``.md`` — used as the Obsidian wikilink target."""
    return sec.filename[:-3] if sec.filename.endswith(".md") else sec.filename


def _yaml_escape(value: str) -> str:
    """Minimal YAML string escaping for inline frontmatter values."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _section_frontmatter(
    *,
    sec: Section,
    doc_title: str,
    doc_id: str,
    stem: str,
    total: int,
    depth: int | None = None,
) -> str:
    """Render the YAML frontmatter for a section md.

    ``depth`` is the LLM-built dependency layer (0 = no prerequisites within
    this paper). When ``None`` we omit the field entirely so older notes
    without a graph stay valid.
    """
    tag = f"paper/{stem}"
    lines = [
        "---",
        f'paper: "{_yaml_escape(doc_title)}"',
        f'paper_id: "{doc_id}"',
        f'paper_stem: "{_yaml_escape(stem)}"',
        f'section_id: "{sec.section_id}"',
        f"order: {sec.order}",
        f"total_sections: {total}",
        f"level: {sec.level}",
        f'title: "{_yaml_escape(sec.title)}"',
    ]
    if depth is not None:
        lines.append(f"depth: {int(depth)}")
    lines.append(f"tags: [paper, {tag}]")
    lines.append("---")
    lines.append("")
    return "\n".join(lines) + "\n"


def _section_nav(
    *,
    prev_sec: Section | None,
    next_sec: Section | None,
    index_stem: str,
) -> str:
    parts: list[str] = []
    if prev_sec is not None:
        parts.append(f"← [[{_section_stem(prev_sec)}|{prev_sec.title}]]")
    parts.append(f"[[{index_stem}|Paper index]]")
    if next_sec is not None:
        parts.append(f"[[{_section_stem(next_sec)}|{next_sec.title}]] →")
    return "> **Navigation:** " + "  ·  ".join(parts) + "\n\n"


def _write_section_mds(
    paper_dir: Path,
    doc_title: str,
    sections: list[Section],
    *,
    doc_id: str,
    stem: str,
    index_stem: str,
    image_ref_mapping: dict[str, str] | None = None,
    depths: dict[str, int] | None = None,
) -> Path:
    """Write one md per section with YAML frontmatter + Prev/Next/Index
    wikilinks so Obsidian's graph view shows a connected chain instead of
    a pile of singletons.

    When ``depths`` is supplied, each section's frontmatter also gets a
    ``depth`` field used by the depth-aware item generation scheduler.
    """
    sections_dir = paper_dir / "sections"
    sections_dir.mkdir(parents=True, exist_ok=True)
    mapping = image_ref_mapping or {}
    total = len(sections)

    for i, sec in enumerate(sections):
        md_path = sections_dir / sec.filename
        body = rewrite_image_refs(sec.body_md, mapping) if mapping else sec.body_md
        rendered = render_section_md(
            Section(
                order=sec.order,
                section_id=sec.section_id,
                title=sec.title,
                slug=sec.slug,
                level=sec.level,
                body_md=body,
                char_range=sec.char_range,
                image_refs=sec.image_refs,
            ),
            doc_title=doc_title,
        )

        prev_sec = sections[i - 1] if i > 0 else None
        next_sec = sections[i + 1] if i + 1 < total else None

        depth = depths.get(sec.section_id) if depths else None
        frontmatter = _section_frontmatter(
            sec=sec,
            doc_title=doc_title,
            doc_id=doc_id,
            stem=stem,
            total=total,
            depth=depth,
        )
        nav = _section_nav(
            prev_sec=prev_sec, next_sec=next_sec, index_stem=index_stem
        )
        md_path.write_text(frontmatter + nav + rendered, encoding="utf-8")

    return sections_dir


def _write_paper_index_md(
    paper_dir: Path,
    *,
    doc_title: str,
    doc_id: str,
    stem: str,
    sections: list[Section],
    index_stem: str,
) -> Path:
    """Write a paper-level index note that wikilinks to every section.

    Gives Obsidian's graph a hub node per paper, so sections form a star
    (index ↔ sections) plus the prev/next chain we emit in each section.
    """
    lines: list[str] = [
        "---",
        f'paper: "{_yaml_escape(doc_title)}"',
        f'paper_id: "{doc_id}"',
        f'paper_stem: "{_yaml_escape(stem)}"',
        f"total_sections: {len(sections)}",
        f"tags: [paper, paper/{stem}, paper-index]",
        "---",
        "",
        f"# {doc_title}",
        "",
        f"Paper id: `{doc_id}` · Sections: {len(sections)}",
        "",
        "## Sections",
        "",
    ]
    for sec in sections:
        indent = "  " * max(0, sec.level - 1) if sec.level > 0 else ""
        lines.append(f"{indent}- [[{_section_stem(sec)}|{sec.title}]]")

    out = paper_dir / f"{index_stem}.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def _write_section_sidecar(
    meta_dir: Path,
    *,
    doc_id: str,
    section: Section,
    chunks: list[IngestedChunk],
    section_md_path: Path,
    vectors_path: Path | None,
    pinecone_namespace: str | None,
    depth: int | None = None,
) -> Path:
    payload: dict[str, Any] = {
        "doc_id": doc_id,
        "section_id": section.section_id,
        "order": section.order,
        "title": section.title,
        "slug": section.slug,
        "level": section.level,
        "depth": depth,
        "md_path": str(section_md_path.as_posix()),
        "char_range_in_paper_md": list(section.char_range),
        "image_refs": section.image_refs,
        "chunks": [
            {
                "chunk_id": f"{section.section_id}::c{c.chunk_index}",
                "chunk_index": c.chunk_index,
                "char_range_in_section": list(c.char_range),
                "text_hash": "sha256:"
                + hashlib.sha256(c.text.encode("utf-8")).hexdigest(),
                "pinecone_id": (
                    f"doc_{doc_id}::{section.section_id}::c{c.chunk_index}"
                    if pinecone_namespace
                    else None
                ),
            }
            for c in chunks
        ],
        "embedding": {
            "model": EMBEDDING_MODEL,
            "dim": EMBEDDING_DIMENSIONS,
            "created_at": _now_iso(),
            "local_vectors_path": vectors_path.name if vectors_path else None,
            "pinecone_namespace": pinecone_namespace,
        },
    }
    out = meta_dir / f"{section.section_id}.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def _write_local_vectors(
    meta_dir: Path,
    section_id: str,
    vectors: list[list[float]],
) -> Path | None:
    if not vectors:
        return None
    try:
        import numpy as np  # local import so test environments without numpy still load the module
    except ImportError:
        logger.warning("numpy not available; skipping local .vectors.npy for %s", section_id)
        return None
    arr = np.asarray(vectors, dtype=np.float32)
    out = meta_dir / f"{section_id}.vectors.npy"
    np.save(out, arr)
    return out


def _write_paper_manifest(
    meta_dir: Path,
    *,
    doc_id: str,
    stem: str,
    filename: str,
    sections: list[IngestedSection],
    user_id: str,
    pinecone_namespace: str | None,
    plots_dir: str | None = None,
    plot_files: list[str] | None = None,
    depths: dict[str, int] | None = None,
    has_graph: bool = False,
) -> Path:
    """Persist the per-paper manifest. ``depths`` (when supplied) is mirrored
    into each section entry so plugins reading paper.json don't need to
    reopen each ``sec_NN.json`` just to render the depth bar."""
    depth_map = depths or {}
    payload = {
        "doc_id": doc_id,
        "stem": stem,
        "source_filename": filename,
        "user_id": user_id,
        "created_at": _now_iso(),
        "embedding": {"model": EMBEDDING_MODEL, "dim": EMBEDDING_DIMENSIONS},
        "pinecone_namespace": pinecone_namespace,
        "plots_dir": plots_dir,
        "plot_files": plot_files or [],
        "graph": {
            "built": has_graph,
            "max_depth": max(depth_map.values()) if depth_map else 0,
        },
        "sections": [
            {
                "section_id": s.section.section_id,
                "order": s.section.order,
                "title": s.section.title,
                "slug": s.section.slug,
                "filename": s.section.filename,
                "level": s.section.level,
                "depth": depth_map.get(s.section.section_id, 0),
                "image_refs": s.section.image_refs,
                "chunk_count": s.chunk_count,
            }
            for s in sections
        ],
    }
    out = meta_dir / "paper.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def _write_edges_json(
    meta_dir: Path,
    *,
    doc_id: str,
    graph: GraphResult,
) -> Path:
    """Persist the LLM-built dependency graph as a sidecar JSON."""
    payload = {
        "doc_id": doc_id,
        "created_at": _now_iso(),
        "edge_count": len(graph.edges),
        "max_depth": max(graph.depths.values(), default=0),
        "depths": graph.depths,
        "edges": graph.edges_for_persist(),
    }
    out = meta_dir / "edges.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def _resolve_paper_root(*, export_path: str | None) -> tuple[Path, bool]:
    """Resolve where the paper folder lives on disk.

    Returns ``(paper_root, is_exported)``. When the caller (or settings)
    provides an export path — typically the user's Obsidian vault — we
    write the paper folder *directly* inside it, making the vault the
    single source of truth. When no export path is set we fall back to
    the project-local extraction cache so the pipeline still works
    headlessly (tests, CLI runs, etc.).
    """
    raw = (export_path or "").strip() or (settings.PAPER_EXPORT_DIR or "").strip()
    if raw:
        return Path(raw).expanduser().resolve(), True
    return Path(settings.EXTRACTED_DIR).resolve(), False


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------


async def ingest_paper(
    pdf_bytes: bytes,
    filename: str,
    user_id: str,
    *,
    export_path: str | None = None,
    force: bool = False,
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> IngestResult:
    """Run the full pipeline for a single paper.

    Safe to call without Pinecone configured — the local folder + sidecar
    JSONs + ``.vectors.npy`` are still produced; Pinecone upsert is skipped
    with a logged warning.
    """
    doc_id = compute_doc_id(pdf_bytes)
    stem = Path(filename).stem or "paper"

    cs = chunk_size or settings.DOC_CHUNK_SIZE
    ov = overlap if overlap is not None else settings.DOC_CHUNK_OVERLAP

    # Resolve the paper root: prefer the caller-provided export target
    # (typically the user's Obsidian vault) so the vault is the single
    # source of truth. If no export path is given, fall back to the
    # project-local extraction cache.
    paper_root, is_exported = _resolve_paper_root(export_path=export_path)
    paper_dir = paper_root / stem

    # 0. Idempotency: reuse prior ingest if doc_id matches and not forcing.
    existing_manifest = paper_dir / ".meta" / "paper.json"
    if existing_manifest.exists() and not force:
        try:
            prior = json.loads(existing_manifest.read_text(encoding="utf-8"))
            if prior.get("doc_id") == doc_id:
                logger.info(
                    "Paper %s already ingested at %s (doc_id=%s); skipping extraction.",
                    stem,
                    paper_dir,
                    doc_id,
                )
                return _reconstruct_result_from_manifest(
                    paper_dir=paper_dir,
                    manifest=prior,
                    is_exported=is_exported,
                    stem=stem,
                )
        except Exception:
            logger.warning("Failed to read existing manifest %s; re-ingesting.", existing_manifest)

    # 1. MinerU extract (first pass on raw bytes).
    paper_root.mkdir(parents=True, exist_ok=True)
    logger.info(
        "ingest_paper: starting MinerU extract for %r (stem=%s, %d bytes) → %s "
        "(exported=%s)",
        filename,
        stem,
        len(pdf_bytes),
        paper_root,
        is_exported,
    )
    try:
        extract_bytes(pdf_bytes, filename, output_dir=str(paper_root))
    except Exception as err:
        logger.exception("MinerU extract_bytes raised for %r: %s", filename, err)
        raise RuntimeError(
            f"MinerU extraction crashed for {filename!r}: {err!s}"
        ) from err

    md_text = read_extracted_md(str(paper_root), stem)
    logger.info(
        "ingest_paper: post-extract read_extracted_md(stem=%s) → %s chars",
        stem,
        len(md_text) if md_text else 0,
    )

    # 1b. Fallback: if MinerU/PDFium produced nothing, try normalizing the
    # PDF via PyMuPDF and re-running MinerU once. PyMuPDF is far more
    # permissive and can rewrite publisher-quirky PDFs (ACM, IEEE, etc.)
    # into a form PDFium can parse.
    if not md_text and pdf_bytes[:8].startswith(b"%PDF-"):
        logger.warning(
            "MinerU produced no markdown for %r on first pass; "
            "retrying after PyMuPDF normalization.",
            filename,
        )
        normalized = normalize_pdf_bytes(pdf_bytes)
        logger.warning(
            "PyMuPDF normalize returned: %s",
            "None"
            if normalized is None
            else f"{len(normalized)} bytes (same={normalized == pdf_bytes})",
        )
        if normalized and normalized != pdf_bytes:
            try:
                extract_bytes(normalized, filename, output_dir=str(paper_root))
            except Exception as err:
                logger.exception(
                    "MinerU retry after normalization crashed for %r: %s", filename, err
                )
            md_text = read_extracted_md(str(paper_root), stem)
            if md_text:
                logger.warning(
                    "MinerU succeeded after PyMuPDF normalization for %r (%d chars md).",
                    filename,
                    len(md_text),
                )
            else:
                logger.warning(
                    "MinerU still produced no markdown after PyMuPDF normalization for %r.",
                    filename,
                )

    if not md_text:
        head = pdf_bytes[:8]
        if not pdf_bytes:
            hint = " (empty body)"
        elif not head.startswith(b"%PDF-"):
            hint = (
                f" — upload is not a PDF (first bytes: {head!r}). "
                "PDFs must start with %PDF-."
            )
        else:
            hint = (
                " — PDF header looks OK but neither PDFium nor PyMuPDF "
                "normalization could make MinerU produce markdown. "
                "Likely encrypted with a password, scanned without an OCR layer, "
                "or an XFA/unusual PDF flavor. Try a different PDF to confirm."
            )
        raise RuntimeError(
            f"MinerU extraction for {filename!r} produced no markdown{hint}"
        )

    # 2. Section split
    sections = split_sections(md_text)
    if not sections:
        raise RuntimeError(f"No sections produced from {stem!r} (empty or unheadered md).")

    doc_title = stem.replace("_", " ").replace("-", " ").title()
    # Filename of the paper-level index note (used as the wikilink target
    # from every section's nav block). Keep it distinct from any section
    # filename by suffixing ``__index``.
    index_stem = f"{stem}__index"

    # 2b. Optional dependency-graph build via the link-architect agent.
    # One LLM call per paper; degrades to depth=0 for everything if no
    # chat key is set or the call fails. Always returns a depths map
    # covering every section_id so downstream writers can rely on it.
    if settings.INGEST_BUILD_GRAPH:
        graph_provider = (
            settings.GRAPH_LLM_PROVIDER.strip()
            or settings.ITEM_GENERATION_PROVIDER
        )
        logger.info(
            "ingest_paper: building dependency graph for stem=%s with provider=%s",
            stem,
            graph_provider,
        )
        graph = await build_section_graph(sections, provider=graph_provider)
    else:
        graph = GraphResult(
            edges=[],
            depths={s.section_id: 0 for s in sections},
        )

    # 2c. Curated plots/ folder (copy referenced images; rewrite section md refs).
    plot_mapping, plot_basenames = _build_plots_folder(paper_dir, sections)
    _write_section_mds(
        paper_dir,
        doc_title,
        sections,
        doc_id=doc_id,
        stem=stem,
        index_stem=index_stem,
        image_ref_mapping=plot_mapping,
        depths=graph.depths if graph.edges else None,
    )
    _write_paper_index_md(
        paper_dir,
        doc_title=doc_title,
        doc_id=doc_id,
        stem=stem,
        sections=sections,
        index_stem=index_stem,
    )

    # ".meta/" is deliberately a dotfolder — Obsidian's file explorer
    # hides it, keeping the vault tree clean while still persisting
    # sidecar JSONs + local embedding .npy on disk. Clean up any
    # transient "meta/" from an older build so only one location exists.
    legacy_meta = paper_dir / "meta"
    if legacy_meta.is_dir():
        shutil.rmtree(legacy_meta, ignore_errors=True)
    meta_dir = paper_dir / ".meta"
    meta_dir.mkdir(parents=True, exist_ok=True)

    # 3. Sub-chunk
    ingested_sections: list[IngestedSection] = []
    flat_entries: list[DocChunkIndexEntry] = []
    flat_to_section: list[int] = []  # index of owning section in ingested_sections
    for sec in sections:
        subs: list[SubChunk] = chunk_text(
            sec.body_md,
            chunk_size=cs,
            overlap=ov,
        )
        ichunks = [
            IngestedChunk(
                section_id=sec.section_id,
                chunk_index=c.index,
                text=c.text,
                char_range=c.char_range,
            )
            for c in subs
        ]
        ingested_sections.append(IngestedSection(section=sec, chunks=ichunks))
        for c in ichunks:
            flat_entries.append(
                DocChunkIndexEntry(
                    doc_id=doc_id,
                    section_id=sec.section_id,
                    chunk_index=c.chunk_index,
                    text=c.text,
                    section_title=sec.title,
                )
            )
            flat_to_section.append(len(ingested_sections) - 1)

    # 4. Embed (single batched call; skips if no OpenAI key — local-only mode)
    all_vectors: list[list[float]] = []
    embedded = False
    if flat_entries:
        try:
            all_vectors = await embedding_pipeline.embed_doc_chunks(flat_entries)
            embedded = True
        except RuntimeError as exc:
            logger.warning("Embedding skipped for paper %s: %s", stem, exc)
            all_vectors = []

    # 5. Persist local per-section vectors + sidecar JSON
    pinecone_ns: str | None = None
    if pinecone_db.pinecone_configured():
        pinecone_ns = pinecone_db.namespace_user_docs(user_id)

    for sec_idx, isec in enumerate(ingested_sections):
        sec_vectors = [
            all_vectors[i] for i, owner in enumerate(flat_to_section) if owner == sec_idx
        ] if embedded else []
        vec_path = _write_local_vectors(meta_dir, isec.section.section_id, sec_vectors)
        md_path = paper_dir / "sections" / isec.section.filename
        _write_section_sidecar(
            meta_dir,
            doc_id=doc_id,
            section=isec.section,
            chunks=isec.chunks,
            section_md_path=md_path.relative_to(paper_dir),
            vectors_path=vec_path,
            pinecone_namespace=pinecone_ns,
            depth=graph.depths.get(isec.section.section_id),
        )

    has_graph = bool(graph.edges)
    if has_graph:
        _write_edges_json(meta_dir, doc_id=doc_id, graph=graph)

    _write_paper_manifest(
        meta_dir,
        doc_id=doc_id,
        stem=stem,
        filename=filename,
        sections=ingested_sections,
        user_id=user_id,
        pinecone_namespace=pinecone_ns,
        plots_dir=PLOTS_DIRNAME if plot_basenames else None,
        plot_files=plot_basenames,
        depths=graph.depths,
        has_graph=has_graph,
    )

    # 6. Pinecone upsert
    pinecone_indexed = 0
    if pinecone_ns and embedded and flat_entries:
        try:
            pinecone_indexed = await embedding_pipeline.index_user_doc_chunks(
                user_id,
                flat_entries,
                vectors=all_vectors,
            )
        except RuntimeError as exc:
            logger.warning("Pinecone upsert skipped for paper %s: %s", stem, exc)

    # 7. No separate mirror step — we wrote directly into paper_root.
    # ``exported_to`` reflects whether that root lives under the caller's
    # export path (typical Obsidian vault case) or the local cache.
    return IngestResult(
        doc_id=doc_id,
        stem=stem,
        paper_dir=paper_dir,
        sections=ingested_sections,
        pinecone_namespace=pinecone_ns,
        pinecone_indexed=pinecone_indexed,
        exported_to=paper_dir if is_exported else None,
    )


def _reconstruct_result_from_manifest(
    *,
    paper_dir: Path,
    manifest: dict,
    is_exported: bool,
    stem: str,
) -> IngestResult:
    """Rebuild an IngestResult from an existing paper.json (idempotent short-circuit).

    When the user re-ingests the same paper and the on-disk ``.meta/paper.json``
    already matches the doc_id, we skip extraction/embedding and just report
    that the folder already exists where it belongs. No copy is performed —
    the paper folder is the single source of truth, so if the user deleted
    it from their vault this branch is not reached.
    """
    sections: list[IngestedSection] = []
    for s in manifest.get("sections", []):
        sec = Section(
            order=int(s.get("order", 0)),
            section_id=str(s.get("section_id", "")),
            title=str(s.get("title", "")),
            slug=str(s.get("slug", "")),
            level=int(s.get("level", 2)),
            body_md="",  # body not materialized from manifest; section md on disk is canonical
            char_range=(0, 0),
            image_refs=list(s.get("image_refs", [])),
        )
        chunks = [
            IngestedChunk(section_id=sec.section_id, chunk_index=i, text="", char_range=(0, 0))
            for i in range(int(s.get("chunk_count", 0)))
        ]
        sections.append(IngestedSection(section=sec, chunks=chunks))

    return IngestResult(
        doc_id=str(manifest.get("doc_id", "")),
        stem=stem,
        paper_dir=paper_dir,
        sections=sections,
        pinecone_namespace=manifest.get("pinecone_namespace"),
        pinecone_indexed=0,
        exported_to=paper_dir if is_exported else None,
        already_ingested=True,
    )
