# DSAN 6725 — Final Project Backend

A knowledge-sharing platform where users contribute concepts (notes, videos, audio), connect them through directed edges into a collaborative knowledge graph, and derive active study materials — powered by configurable AI services and a dual-loop optimization architecture.

The underlying data model is a **content-rich superhypergraph**: concepts are nodes, relationship edges carry markdown bodies, items are hyperedges spanning multiple concepts, and groups define nested, scoped subgraphs.

## Branches

| Branch | Purpose | What's in it |
|---|---|---|
| `main` | Stable baseline | Initial scaffold, README |
| `docs/architecture-plan` | Design docs & notes | Architecture plan, all `notes/`, `.cursor/rules/` — **no code** |
| `feat/skeleton` | Active development | Full backend skeleton: `app/`, `tests/`, config, notes, rules — **start here for coding** |

**To start working on code**, branch off `feat/skeleton`:

```bash
git checkout feat/skeleton
git checkout -b feat/your-feature
```

## Core Concepts

| Concept | Description |
|---|---|
| **Concept** | A unit of knowledge — markdown notes, video URLs, or audio recordings |
| **Edge** | A unified connection between two concepts — has direction, type (prerequisite, reference, application, etc.), optional note, and origin. Traversal derives from directed `prerequisite` edges |
| **Item** | A hyperedge spanning multiple concepts — problems, exercises, flashcards, definitions |
| **Data Entity** | A dataset reference with download metadata and appendable freeform entries (ML metrics, pipeline results). A specialized "dive" |
| **Dive** *(experimental)* | An advanced exploration hyperedge spanning multiple foundation concepts |
| **Group Landscape** | A merged view of all members' notes; similar notes collapse into canonical nodes with perspectives |
| **Traversal Engine** | Personalized learning path based on Knowledge Space Theory (outer fringe computation) |
| **Fork** | A universal provenance operation applicable to any entity (concept, edge, dive) |

These concepts live in a **three-layer graph**: personal graph (per-user, private) → group landscape (merged canonical view) → traversal graph (personalized DAG for study mode).

See [`plan.md`](plan.md) for the full architectural plan and [`notes/`](notes/) for detailed design specs on each module.

## Implementation Status

> Full details with code references: [`notes/13-development-progress.md`](notes/13-development-progress.md)

| Module | Status | Notes |
|---|---|---|
| FastAPI shell, config, exceptions | **Completed** | `app/main.py`, `app/config.py` |
| **Observability** (health + optional Prometheus) | **Completed** | [`app/monitoring.py`](app/monitoring.py), [`notes/15-observability.md`](notes/15-observability.md) |
| AI providers (OpenAI, Anthropic, Groq) | **Completed** | Dispatch layer in `app/ai/providers/` |
| Document extraction (MinerU) | **Completed + Tested** | PDF/DOCX/image → markdown + images |
| Ingest pipeline (chunker, sanitizer, HTML) | **Completed + Tested** | `app/ingest/` |
| Edge inference (lexical + semantic) | **Prototyped + Tested** | Jaccard overlap + cosine + LLM refinement |
| Item generation (tool-calling) | **Completed + Tested** | Session-based generation loop + grading APIs; **offline evals** in [`evals/item_generation/`](evals/item_generation/) — see [`notes/13-development-progress.md`](notes/13-development-progress.md) |
| Vector index + semantic search | **Completed + Tested** | OpenAI embeddings + Pinecone via `/api/v1/vectors/concepts/index`, `/search`, `/search-multi`, `/clear` |
| Concepts, edges, items CRUD | Stub | Docstring specs, no logic yet |
| Groups, traversal, auth | Stub | Docstring specs, no logic yet |
| **Obsidian plugin** | **Completed (Item Generator)** | Item generation + extraction + semantic workflow (index/search/clear namespace + one-click search-add-generate) |
| ACE roles (Curator, Meta-Curator, Reflector) | Stub | Specs written, dormant for POC |
| Meta-Harness (outer loop) | Stub | Intentionally dormant for POC |
| DB clients (Mongo, Postgres, Pinecone, S3) | Partial | Pinecone client helpers implemented; Mongo/Postgres/S3 remain stub |
| **Test suite** | **47 tests passing** | 8 test modules |

## Tech Stack

- **Language:** Python 3.11+
- **Framework:** FastAPI (async)
- **Document Store:** MongoDB (concepts, edges, canonical nodes, ACE playbooks — delta updates via `motor`)
- **Relational DB:** PostgreSQL + SQLAlchemy 2.0 + Alembic (users, groups, permissions, scheduling)
- **Vector Search:** Pinecone Serverless (merge detection, edge dedup, foreign content resolution)
- **Object Store:** S3-compatible / MinIO (audio, images, handwritten submissions)
- **Document Extraction:** [MinerU](https://github.com/opendatalab/MinerU) (PDF/DOCX/image → markdown with tables, formulas, figures)
- **AI:** Pluggable LLM/embedding providers per group (OpenAI, Anthropic, Groq)
- **AI Optimization:** ACE (inner loop, context refinement) + Meta-Harness (outer loop, pipeline optimization)
- **Frontend:** [Obsidian](https://obsidian.md/) plugin (TypeScript, esbuild, Cytoscape.js) — thin client calling the backend
- **Protocol:** MCP (Model Context Protocol) for extensible AI tool integration

## Project Structure

```
app/
├── api/v1/           # FastAPI route handlers
├── schemas/          # Pydantic request/response models
├── models/           # Document & ORM models
├── services/         # Business logic (extraction, edges, concepts)
├── ai/
│   ├── providers/    # OpenAI, Anthropic, Groq dispatch
│   ├── pipelines/    # Connection inference, item construction, etc.
│   ├── ace/          # ACE inner-loop roles (curator, reflector)
│   └── meta_harness/ # Outer-loop optimizer (dormant)
├── ingest/           # PDF, DOCX, HTML, chunker, sanitizer, postprocessor
├── mcp/              # MCP server/client integration
├── db/               # Database sessions & repositories
├── monitoring.py     # /health, /ready, optional Prometheus /metrics
└── exceptions.py     # Domain-specific exceptions

plugin/               # Obsidian plugin (TypeScript thin client)
├── src/views/        # GraphView, TraversalView, ItemView, LandscapeView
├── src/commands/     # Publish command (save/index/share)
└── src/api.ts        # Typed requestUrl() wrappers

tests/                # 47 tests across 8 modules
notes/                # Design specs per module (01-concepts through 15-observability)
vendor/               # Git-cloned team/external repos (gitignored, local only)
data/                 # Test PDFs, extracted output (gitignored)
```

## Design Notes

All design decisions are documented in `notes/`:

| Note | Topic |
|---|---|
| [01-concepts](notes/01-concepts.md) | Concept nodes, three-layer graph model |
| [02-edges](notes/02-edges.md) | Unified edge model + dive hyperedges |
| [03-forking](notes/03-forking.md) | Fork/extends flow |
| [04-merging](notes/04-merging.md) | Canonical node merge pipeline |
| [05-traversal](notes/05-traversal.md) | KST traversal engine |
| [06-items](notes/06-items.md) | Item hyperedges, generation via tool-calling |
| [07-data-entities](notes/07-data-entities.md) | Data entities (specialized dive) |
| [08-groups](notes/08-groups.md) | Group regions, permissions |
| [09-ai-optimization](notes/09-ai-optimization.md) | ACE + Meta-Harness architecture |
| [10-architecture](notes/10-architecture.md) | Infrastructure, DB, events |
| [11-open-questions](notes/11-open-questions.md) | Unresolved design decisions |
| [12-vendor-integration](notes/12-vendor-integration.md) | MinerU + vendor/yubo integrations |
| [13-development-progress](notes/13-development-progress.md) | Full module status with code references |
| [14-obsidian-integration](notes/14-obsidian-integration.md) | Obsidian plugin MVP — architecture, privacy model, build scope |
| [15-observability](notes/15-observability.md) | Health/readiness, optional Prometheus metrics |

## Getting Started

### Prerequisites

- Python 3.11+
- Docker (for Postgres, MongoDB, MinIO)

### Setup

```bash
# Clone and switch to the coding branch
git clone https://github.com/chaowei312/finalproj-backend.git
cd finalproj-backend
git checkout feat/skeleton

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Copy environment template and fill in your values
cp .env.example .env

# Start infrastructure (Postgres, MongoDB, MinIO)
docker compose up -d

# Run database migrations
alembic upgrade head

# Start the dev server
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

### Running Tests

```bash
pytest                    # all 47 tests
pytest tests/test_*.py -v # verbose output
```

### Vendor Folder

`vendor/` holds git-cloned repos from teammates or external sources. It's gitignored — each team member clones what they need locally. See [module-integration rules](.cursor/rules/module-integration.mdc) for the integration workflow: search vendor → copy into `app/` → refactor imports → never import directly from vendor.

## Development

### Branch Naming

```
feat/entity-connections      # new feature
fix/embedding-timeout        # bug fix
refactor/service-layer       # refactoring
docs/api-schema              # documentation
test/item-generation         # tests
```

### Commit Messages

```
feat: add entity embedding pipeline
fix: handle null content_type in edge creation
refactor: extract repository layer from services
```

Prefix with `feat`, `fix`, `refactor`, `docs`, `test`, or `chore`. Imperative mood, lowercase.

### Cursor Rules

This repo includes shared [Cursor](https://cursor.com) AI rules in `.cursor/rules/`. They are automatically picked up when any team member opens the project — no setup needed.

| Rule | What it covers |
|---|---|
| `project-overview.mdc` | Domain model, tech constraints |
| `python-standards.mdc` | Code style, async patterns |
| `api-conventions.mdc` | FastAPI endpoint patterns |
| `database-models.mdc` | ORM and document model conventions |
| `schemas-pydantic.mdc` | Pydantic schema patterns |
| `ai-services.mdc` | AI provider and pipeline conventions |
| `module-integration.mdc` | Vendor → app integration workflow |
| `obsidian-plugin.mdc` | Obsidian plugin TypeScript conventions |
| `git-conventions.mdc` | Branch naming, commit format |

## Team

DSAN 6725 Final Project Group — Georgetown University

## License

This project is for academic use as part of Georgetown University's DSAN 6725 course.
