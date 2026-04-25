# Vendor Integration Log

---

## vendor/mineru — MinerU PDF/Document Extraction

Source: `vendor/mineru/` — [opendatalab/MinerU](https://github.com/opendatalab/MinerU) (AGPL-3.0, 59K+ stars).

### What MinerU does

Converts complex PDFs (tables, formulas, images, multi-column layouts) into clean markdown/JSON. Supports 109 languages via dual VLM + OCR engine.

### Integration architecture

MinerU is installed as a local Python package (`pip install mineru[pipeline]`). The extraction service calls `do_parse()` directly — no sidecar or HTTP needed.

```
extract_file("data/paper.pdf")
    │
    ▼
mineru.cli.common.do_parse()  →  layout detection → OCR → table/formula recognition
    │
    ▼
data/extracted/paper/auto/
    ├── paper.md              ← clean markdown with tables, formulas, image refs
    ├── images/               ← extracted figures as .jpg
    └── paper_content_list.json
```

### Files created/modified

| File | Role |
|---|---|
| `app/services/extraction_service.py` | `extract_file()`, `extract_bytes()`, `read_extracted_md()`, `list_extracted_images()` — thin wrapper around `do_parse` |
| `app/config.py` | Added `MINERU_BACKEND`, `EXTRACTED_DIR` settings |
| `.env.example` | Added MinerU env vars |
| `requirements.txt` | Added `mineru[pipeline]` |

### Backend options (via `MINERU_BACKEND` env var)

| Value | Description |
|---|---|
| `auto` | Auto-detect best method per file (default) |
| `pipeline` | Classic CV/OCR — multi-lang, no hallucination, CPU or GPU |
| `vlm-auto-engine` | Vision-language model — high accuracy, CN/EN only, needs GPU |
| `hybrid-auto-engine` | Pipeline + VLM combined — best accuracy, multi-lang, needs GPU |

### Usage

```python
from app.services.extraction_service import extract_file, read_extracted_md
extract_file("data/paper.pdf")  # writes to data/extracted/
md = read_extracted_md("data/extracted", "paper")
```

### Verified output

`data/Meta-Harness.pdf` (26 pages) → 520 lines markdown, 22 images, tables as HTML, formulas as LaTeX. 5 passing tests.

---

## vendor/yubo — Team member Yubo's repo

Source: `vendor/yubo/` — team member Yubo's repo.

## Integrated Modules

| # | vendor/yubo source | Integrated to | What it does |
|---|---|---|---|
| 1 | `services/karpathy_agents/jsonutil.py` | `app/ai/jsonutil.py` | Robust JSON extraction from LLM output: strip code fences, find balanced `{...}`, parse with fallback. Used by every LLM-calling pipeline. |
| 2 | `services/providers/openai_chat.py` | `app/ai/providers/openai_chat.py` | AsyncOpenAI chat completion with JSON response mode. |
| 3 | `services/providers/openai_embeddings.py` | `app/ai/providers/openai_embeddings.py` | AsyncOpenAI batch embedding with dimension validation. |
| 4 | `services/providers/anthropic_chat.py` | `app/ai/providers/anthropic_chat.py` | AsyncAnthropic chat completion. |
| 5 | `ingest/chunk.py` | `app/ingest/chunker.py` | Splits text into (title, body) sections by `##` headings or paragraph boundaries. |
| 6 | `ingest/sanitize.py` | `app/ingest/sanitize.py` | Strips NUL bytes for Postgres/Mongo safety. |
| 7 | `ingest/pdf.py` | `app/ingest/pdf.py` | pypdf per-page text extraction, rejects encrypted PDFs. |
| 8 | `ingest/docx_extract.py` | `app/ingest/docx.py` | python-docx paragraph text extraction. |
| 9 | `ingest/html_extract.py` | `app/ingest/html.py` | BeautifulSoup visible text extraction. |
| 10 | `services/semantic_pairing.py` + `services/llm_edge_refiner.py` | `app/ai/pipelines/connection_inference.py` | Cosine similarity matrix → top-K pairs → optional LLM relation/label refinement. |
| 11 | `services/lexical_edges.py` | `app/services/edge_service.py` | Token-bag Jaccard similarity for cheap lexical overlap edges (no embeddings needed). |

## Refactoring Applied

Per `.cursor/rules/module-integration.mdc`:

- All imports rewritten from `app.config.Settings` → `app.config.settings` (singleton).
- `app.models.entity.Entity` / `app.models.edge.Edge` ORM references replaced with plain dicts or protocol types (we use MongoDB, not their SQLAlchemy models).
- Provider functions use our `app.config.settings` attributes (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`) instead of yubo's `settings.openai_api_key`.
- Exception classes adapted to `app.exceptions` hierarchy.
- Each integrated file has `# Adapted from: vendor/yubo/...` attribution comment.

## Not Integrated (and why)

| vendor/yubo component | Reason |
|---|---|
| `models/entity.py` (pgvector) | We use Pinecone for vectors, not pgvector in Postgres |
| `app/db/` (SQLAlchemy setup) | Different schema split (Postgres + Mongo) |
| `services/ingest_service.py` | Orchestration pattern noted but our event-driven flow differs; concepts from it inform `concept_service.py` |
| `services/ingest_note_synthesis.py` | Single-shot LLM note rewriting; may integrate later as a `writing_assist` enhancement |
| `karpathy_agents/pipeline.py` | Multi-agent pipeline; architecture noted for future ACE loop reference |
| `app/security.py` | We have our own JWT auth |
| `app/examples/` | Static demo fixtures |
| `frontend/` | Not backend |
| `alembic/` | Schema-specific to their entity model |
