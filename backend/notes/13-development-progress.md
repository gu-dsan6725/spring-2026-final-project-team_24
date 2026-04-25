# Development Progress

Status legend:
- **Completed** — implemented + tested, ready for integration
- **Prototyped** — functional code exists, not yet fully tested
- **Tested** — has passing unit/integration tests
- **Stub** — file exists with docstring spec only, no logic
- **Deferred** — not started, planned for future

---

## Summary

| Note | Domain | Code Status | Tests |
|---|---|---|---|
| [01-concepts](01-concepts.md) | Concept nodes, 3-layer graph | Stub | Stub |
| [02-edges](02-edges.md) | Unified edge model | Prototyped (lexical + semantic) | Tested |
| [03-forking](03-forking.md) | Fork/extends flow | Stub | — |
| [04-merging](04-merging.md) | Canonical node merge pipeline | Stub | Stub |
| [05-traversal](05-traversal.md) | KST traversal engine | Stub | Stub |
| [06-items](06-items.md) | Item hyperedges, generation | **Completed** (full pipeline + API) | Tested |
| [07-data-entities](07-data-entities.md) | Data entities (specialized dive) | Stub | — |
| [08-groups](08-groups.md) | Group regions, permissions | Stub | Stub |
| [09-ai-optimization](09-ai-optimization.md) | ACE + Meta-Harness | Stub (specs written) | — |
| [10-architecture](10-architecture.md) | Infra, DB, events | Prototyped (config, FastAPI shell) | — |
| [11-open-questions](11-open-questions.md) | Design decisions & open items | — | — |
| [12-vendor-integration](12-vendor-integration.md) | vendor/yubo + MinerU | Completed | Tested |
| [14-obsidian-integration](14-obsidian-integration.md) | Obsidian plugin MVP | **Completed** (Item Generator) | — |
| [15-observability](15-observability.md) | HTTP metrics, health | **Completed** | Tested |

---

## 01 — [Concepts](01-concepts.md)

| File | Status | What it does |
|---|---|---|
| `app/models/concept.py` | Stub | Docstring spec for concept MongoDB document |
| `app/schemas/concept.py` | Stub | Docstring with search DTO sketch, no Pydantic models |
| `app/services/concept_service.py` | Stub | Docstring for concept CRUD |
| `app/services/concept_search_service.py` | Stub | Docstring for privacy-preserving group concept search |
| `app/api/v1/concepts.py` | Stub | APIRouter registered, no routes implemented |
| `tests/test_concepts.py` | Stub | No tests |

**Next**: Define Pydantic schemas → MongoDB CRUD in concept_service → wire API routes.

---

## 02 — [Edges](02-edges.md)

| File | Status | What it does |
|---|---|---|
| `app/models/edge.py` | Stub | Docstring spec for relationship vs traversal edge models |
| `app/schemas/edge.py` | Stub | No Pydantic models |
| `app/services/edge_service.py` | **Prototyped** | `build_lexical_overlap_edges()` — token-bag Jaccard similarity for cheap cross-links without embeddings |
| `app/ai/pipelines/connection_inference.py` | **Prototyped** | Full pipeline: cosine similarity matrix → top-K pairs → LLM relation/label refinement via `refine_pairs_with_llm()` |
| `app/api/v1/edges.py` | Stub | APIRouter registered, no routes |
| `tests/test_lexical_edges.py` | **Tested** (5 tests) | Overlap detection, low-overlap skip, existing-pair dedup, single concept |
| `tests/test_semantic_pairs.py` | **Tested** (6 tests) | Cosine pairing, orthogonal rejection, empty/single, top-K limits, identical vectors |

**What works**: Given concept dicts with embeddings, `infer_edges()` produces typed `InferredEdge` dicts. `build_lexical_overlap_edges()` works as a cheap fallback when embeddings aren't available.

**Next**: Define edge Pydantic schemas → MongoDB persistence → wire API routes → add traversal edge DAG cycle detection.

---

## 03 — [Forking](03-forking.md)

| File | Status | What it does |
|---|---|---|
| `app/services/fork_service.py` | Stub | Docstring for fork/extends flow |

**Next**: Implement after concept + edge CRUD is live.

---

## 04 — [Merging & Canonical Nodes](04-merging.md)

| File | Status | What it does |
|---|---|---|
| `app/models/canonical_node.py` | Stub | Docstring for canonical landscape document |
| `app/schemas/canonical.py` | Stub | No schemas |
| `app/services/merge_service.py` | Stub | Docstring describing integration with meta_curator + similarity_verifier |
| `app/ai/ace/meta_curator.py` | Stub | Docstring spec for group landscape gatekeeper (gated push, 3-band routing) |
| `app/ai/providers/similarity_verifier.py` | Stub | Docstring spec for two-stage verification (Pinecone + LLM confirmation) |
| `tests/test_merge.py` | Stub | No tests |

**Next**: Requires Pinecone client + concept service first. Then wire the merge pipeline.

---

## 05 — [Traversal Engine](05-traversal.md)

| File | Status | What it does |
|---|---|---|
| `app/models/knowledge_state.py` | Stub | Docstring for knowledge state K (PostgreSQL) |
| `app/services/traversal_service.py` | Stub | Docstring for KST outer-fringe algorithm |
| `app/services/spaced_repetition.py` | Stub | Docstring for SM-2/FSRS scheduling |
| `app/schemas/traversal.py` | Stub | No schemas |
| `app/api/v1/traversal.py` | Stub | APIRouter registered, no routes |
| `tests/test_traversal.py` | Stub | No tests |

**Next**: Requires traversal edge DAG + knowledge state model first.

---

## 06 — [Items (Hyperedges)](06-items.md)

| File | Status | What it does |
|---|---|---|
| `app/models/item.py` | **Prototyped** | Item hyperedge model with type/difficulty enums |
| `app/schemas/item.py` | **Completed** | Full Pydantic schemas: `GeneratedItem`, `ActorTrajectory`, `ReflectorFeedback`, `GraderSummary`, `RoundResult`, `SessionResponse`, `InlineConcept/Edge`, `AnswerGradeRequest/Feedback`, `ContinueRoundRequest`, `ContextImage`, `PaperSegmentResult`, `SegmentedConcept/Edge` |
| `app/services/item_service.py` | **Completed** | Session-based orchestration: `start_session()`, `next_round()`, `finish_session()`, stateless `continue_round()` with manual difficulty override |
| `app/ai/pipelines/item_construction.py` | **Completed** | Tool schemas, curated view builders, `build_messages()` with inline image support + `generate()` with multi-item extraction and tool-calling |
| `app/ai/pipelines/item_loop.py` | **Completed** | Two-phase loop: Phase 1 (standard refinement) + Phase 2 (iterative hardening for hard/very_hard/expert with actor trajectory feedback) |
| `app/ai/pipelines/actor.py` | **Completed** | Actor agent — solves generated items using concept context via tool-calling |
| `app/ai/pipelines/reflector.py` | **Completed** | Reflector agent — quality evaluation + hardening evaluator (analyzes actor trajectories to produce targeted difficulty escalation directives) |
| `app/ai/pipelines/grader.py` | **Completed** | Grader agent — assesses learning progress, recommends difficulty adjustment |
| `app/ai/pipelines/answer_grader.py` | **Completed** | User answer grading — compares free-text user answers against reference solutions |
| `app/ai/pipelines/feasibility_check.py` | **Completed** | Domain/difficulty classification gate (ABANDON / GENERATE_WITH_REVIEW / GENERATE) |
| `app/ai/pipelines/item_evaluation.py` | **Completed** | Post-generation quality gate with ACCEPT/REJECT/FLAG outcomes |
| `app/ai/pipelines/paper_segmenter.py` | **Completed** | LLM pipeline: extracted paper markdown → concept nodes + directed edges (JSON) |
| `app/ai/pipelines/item_pool.py` | Stub | Docstring for search-first item retrieval |
| `app/ai/providers/__init__.py` | **Completed** | Provider dispatch with Anthropic native tool-calling, multimodal image support (data URI → Anthropic image blocks), Groq failed_generation fallback |
| `app/api/v1/items.py` | **Completed** | Full REST API: `POST /generate`, `POST /sessions/{id}/next-round`, `POST /sessions/{id}/finish`, `GET /sessions/{id}`, `POST /continue-round` (stateless resume), `POST /grade-answer` |
| `app/api/v1/extraction.py` | **Completed** | `POST /extract/upload` — PDF upload → MinerU extraction → LLM segmentation into concepts + edges |
| `tests/test_items.py` | **Tested** | Comprehensive tests for schemas, service logic, difficulty progression |

**What works**: Full item generation pipeline with 5 difficulty tiers (easy → medium → hard → very_hard → expert). Hard+ difficulties use iterative hardening: generator produces medium items, then a hardening reflector analyzes actor trajectories to produce "make harder" directives + pulls random additional concepts from the user's knowledge graph. Each iteration is in-place (item(i+1) = f(item(i)), no context accumulation). Inline image context: exam paper images are sent as base64 alongside tool-calling JSON for visual context. PDF upload: MinerU extracts text, LLM segments into concept nodes + directed edges, auto-created as vault notes. Manual difficulty selection in plugin (no auto-escalation). Cancel button on generation.

**Providers tested**: Anthropic (primary, native tool-calling + multimodal images), Groq (fallback with `failed_generation` recovery).

---

## 07 — [Data Entities](07-data-entities.md)

| File | Status | What it does |
|---|---|---|
| `app/models/data_entity.py` | Stub | One-line docstring |
| `app/schemas/data_entity.py` | Stub | No schemas |
| `app/services/data_entity_service.py` | Stub | Docstring for SQL/chart entities |
| `app/api/v1/data_entities.py` | Stub | APIRouter registered, no routes |

**Status**: Deferred — lowest priority for POC.

---

## 08 — [Groups](08-groups.md)

| File | Status | What it does |
|---|---|---|
| `app/models/group.py` | Stub | Docstring for group/membership model |
| `app/schemas/group.py` | Stub | No schemas |
| `app/services/group_service.py` | Stub | Docstring for group CRUD + membership |
| `app/api/v1/groups.py` | Stub | APIRouter registered, no routes |
| `tests/test_groups.py` | Stub | No tests |

**Next**: Define group model → permissions → region scoping.

---

## 09 — [AI Optimization (ACE + Meta-Harness)](09-ai-optimization.md)

### ACE (Inner Loop)

| File | Status | What it does |
|---|---|---|
| `app/ai/ace/__init__.py` | Stub | Package docstring mapping ACE roles to platform |
| `app/ai/ace/curator.py` | Stub | Docstring: personal graph health, per-user playbook |
| `app/ai/ace/meta_curator.py` | Stub | Docstring: group landscape gatekeeper, gated push |
| `app/ai/ace/reflector.py` | Stub | Docstring: feedback distillation at personal + group tiers |
| `app/ai/ace/playbook.py` | Stub | Docstring: two-tier playbook CRUD with delta ops |
| `app/models/playbook.py` | Stub | Docstring for playbook MongoDB document |

### Meta-Harness (Outer Loop — Dormant)

| File | Status | What it does |
|---|---|---|
| `app/ai/meta_harness/__init__.py` | Stub | Docstring: marked dormant for POC, future ACE item refinement loop |
| `app/ai/meta_harness/optimizer.py` | Stub | Docstring: future refinement proposer |
| `app/ai/meta_harness/evaluator.py` | Stub | Docstring: future "Actor" (simulated student) |

**Status**: All spec-only. ACE roles are well-defined in docstrings with clear responsibilities. Meta-Harness is intentionally dormant.

---

## 10 — [Architecture & Infrastructure](10-architecture.md)

### Core App Shell

| File | Status | What it does |
|---|---|---|
| `app/main.py` | **Completed** | FastAPI app with v1 router mounted |
| `app/config.py` | **Completed** | Pydantic Settings: app, Postgres, Mongo, Pinecone, S3, AI providers, Groq, MinerU, auth |
| `app/exceptions.py` | **Completed** | Exception hierarchy: `AppError`, `NotFoundError`, `ForbiddenError`, `ConflictError`, `CycleError`, `PdfExtractError`, `DocxExtractError` |
| `app/api/v1/router.py` | **Completed** | Central router wiring all v1 sub-routers |
| `app/security.py` | Stub | JWT + password hashing placeholder |

### Database Clients

| File | Status | What it does |
|---|---|---|
| `app/db/postgres.py` | Stub | Docstring for SQLAlchemy async engine/session |
| `app/db/mongo.py` | Stub | Docstring for Motor async client |
| `app/db/pinecone.py` | **Prototyped** | Pinecone client helpers: namespace builders, upsert/delete, single-namespace query, fan-out query with merged top-K dedup |
| `app/db/s3.py` | Stub | Docstring for S3/MinIO object storage |

### Events

| File | Status | What it does |
|---|---|---|
| `app/events/bus.py` | Stub | Event bus placeholder |
| `app/events/handlers.py` | Stub | Handlers placeholder |

### MCP

| File | Status | What it does |
|---|---|---|
| `app/mcp/server.py` | Stub | MCP server placeholder |
| `app/mcp/client.py` | Stub | MCP client placeholder |

### Infra Files

| File | Status | What it does |
|---|---|---|
| `docker-compose.yml` | **Completed** | Postgres 16, MongoDB 7, MinIO |
| `.env.example` | **Completed** | All env vars documented |
| `requirements.txt` | **Completed** | All dependencies including `mineru[pipeline]` |
| `pytest.ini` | **Completed** | Test config with `asyncio_mode = auto` |
| `alembic.ini` | **Completed** | Alembic migration config |

---

## 12 — [Vendor Integration](12-vendor-integration.md)

### MinerU (PDF/Document Extraction)

| File | Status | What it does |
|---|---|---|
| `app/services/extraction_service.py` | **Completed** | `extract_file()`, `extract_bytes()`, `read_extracted_md()`, `list_extracted_images()` — wraps MinerU `do_parse`. Saves raw MinerU output as `.raw.md` alongside post-processed `.md` |
| `app/ingest/postprocess.py` | **Completed** | Safe, lossless post-processing: HTML `<table>` → markdown pipe tables only. LaTeX and all other content left untouched — MinerU owns extraction, we own presentation format |
| `tests/test_pdf_extract.py` | **Tested** (5 tests) | Full extraction of `data/Meta-Harness.pdf` → validates .md output, images, tables, formulas, image refs |
| `tests/test_postprocess.py` | **Tested** (7 tests) | HTML→pipe table conversion, rowspan/colspan handling, LaTeX passthrough, real file validation |

**Verified output**: 26-page paper → 634-line markdown + 22 extracted images + content list. Each extraction produces two markdown files:
- `<stem>.md` — post-processed (pipe tables for readability)
- `<stem>.raw.md` — untouched MinerU output (HTML tables, preserved for reference)

**Known MinerU limitations** (upstream, not fixable from our side):
- Table column merging: OCR sometimes merges adjacent columns in dense tables
- LaTeX number noise: OCR wraps plain numbers in `$...$` with spurious spaces (`$3 1 . 7$`)
- Algorithm blocks: heavy math typography (subscripts, calligraphic letters, set notation) often OCR-corrupted

### vendor/yubo Integrations

| File | Status | What it does |
|---|---|---|
| `app/ai/jsonutil.py` | **Completed** | LLM JSON extraction: fence stripping, brace-extract, fallback parse |
| `app/ai/providers/openai_chat.py` | **Completed** | AsyncOpenAI chat with JSON response mode |
| `app/ai/providers/openai_embeddings.py` | **Completed** | AsyncOpenAI batch embedding with dim validation |
| `app/ai/pipelines/embedding_pipeline.py` | **Completed** | Concept embedding/index pipeline: `index_user_concepts()`, `search_user_concepts()`, `search_concepts_across_namespaces()`, delete helpers |
| `app/ai/providers/anthropic_chat.py` | **Completed** | AsyncAnthropic chat completion |
| `app/ai/providers/__init__.py` | **Completed** | Provider dispatch: `embed_texts()`, `chat_json_completion()`, `chat_tool_completion()` routing to openai/anthropic/groq — includes Anthropic native tool-calling and Groq `failed_generation` fallback |
| `app/ai/providers/local_llm.py` | **Completed** | Groq-backed AsyncOpenAI client for free LLM access |
| `app/ingest/chunker.py` | **Completed** | Markdown heading / paragraph splitter |
| `app/ingest/sanitize.py` | **Completed** | NUL byte stripping |
| `app/ingest/docx.py` | **Completed** | python-docx paragraph extraction |
| `app/ingest/html.py` | **Completed** | BeautifulSoup visible text extraction |
| `app/ingest/postprocess.py` | **Completed** | MinerU post-processing: HTML table → pipe table (lossless) |
| `app/ai/pipelines/connection_inference.py` | **Completed** | Cosine pairs + LLM refinement pipeline |
| `app/services/edge_service.py` | **Completed** | Lexical Jaccard overlap edges |
| `app/schemas/vectors.py` | **Completed** | Pydantic models for vector index/search requests and responses |
| `app/api/v1/vectors.py` | **Completed** | Vector endpoints: `POST /vectors/concepts/index`, `POST /vectors/concepts/search`, `POST /vectors/concepts/search-multi`, `POST /vectors/concepts/clear` |
| `tests/test_jsonutil.py` | **Tested** (9 tests) | Fence strip, brace extract, load_llm_json edge cases |
| `tests/test_chunker.py` | **Tested** (5 tests) | Headings, paragraphs, h3, single, empty |
| `tests/test_sanitize.py` | **Tested** (4 tests) | NUL stripping, clean passthrough |
| `tests/test_ingest_dispatch.py` | **Tested** (3 tests) | Sanitize + chunker + HTML together |
| `tests/test_lexical_edges.py` | **Tested** (5 tests) | Overlap, skip, dedup, single |
| `tests/test_semantic_pairs.py` | **Tested** (6 tests) | Cosine pairing, orthogonal, top-K |
| `tests/test_vector_merge.py` | **Tested** (2 tests) | Merge/dedup helper correctness for fan-out search hits |
| `tests/test_embedding_pipeline.py` | **Tested** (4 tests) | Embedding pipeline orchestration with mocked OpenAI/Pinecone, including namespace clear path |
| `tests/test_vectors_api.py` | **Tested** (5 tests) | `/vectors` API success + failure paths, metadata passthrough, namespace clear endpoint |

---

## Test Suite Summary

```
47 passed

tests/test_chunker.py          5 passed
tests/test_ingest_dispatch.py   3 passed
tests/test_jsonutil.py          9 passed
tests/test_lexical_edges.py     5 passed
tests/test_pdf_extract.py       5 passed  (MinerU pipeline integration)
tests/test_postprocess.py       7 passed  (HTML→pipe table, colspan/rowspan, LaTeX passthrough)
tests/test_sanitize.py          4 passed
tests/test_semantic_pairs.py    6 passed
```

Stub test files (no tests yet): `test_auth`, `test_concepts`, `test_edges`, `test_groups`, `test_items`, `test_merge`, `test_traversal`.

---

## 14 — [Obsidian Plugin Integration](14-obsidian-integration.md)

| Component | Status | What it does |
|---|---|---|
| `plugin/manifest.json` | **Completed** | Obsidian plugin metadata (`knowledge-graph` v0.1.0) |
| `plugin/src/main.ts` | **Completed** | Plugin entry — registers ItemGeneratorView + ribbon icon |
| `plugin/src/settings.ts` | **Completed** | Backend URL, auth token, and `vectorUserId` settings for Pinecone namespace alignment |
| `plugin/src/api.ts` | **Completed** | Typed `requestUrl()` wrappers: items/extraction endpoints + vector endpoints (`indexConcepts`, `searchConcepts`, `clearConceptNamespace`) with backend URL validation |
| `plugin/src/types.ts` | **Completed** | Full TypeScript interfaces mirroring all backend Pydantic schemas including `ContextImage`, `PaperSegmentResult` |
| `plugin/src/views/ItemView.ts` | **Completed** | Full item generation panel + semantic workflow enhancements (one-click `Search + Add + Generate`, namespace clear button, index/search/add-to-foundation flow) |
| `plugin/styles.css` | **Completed** | CSS for item generator plus semantic-search result list and compact add buttons |
| `plugin/esbuild.config.mjs` | **Completed** | esbuild production build config |
| CORS middleware (`app/main.py`) | **Completed** | `CORSMiddleware` allowing `app://obsidian.md` origin |
| `plugin/src/views/GraphView.ts` | Planned | Cytoscape.js knowledge graph panel |
| `plugin/src/views/TraversalView.ts` | Planned | Study mode outer fringe panel |
| `plugin/src/views/LandscapeView.ts` | Planned | Group landscape browser |
| `plugin/src/views/DataEntityView.ts` | Planned | Data entity detail + entry appending |
| `plugin/src/commands/publish.ts` | Planned | Three-mode publish: save (private), index (embed), share (landscape) |

### Item Generator Features (implemented)

- **Concept import**: Search vault notes, add active note, import active + linked, import all vault; reads YAML frontmatter for mastery/edges
- **Sample items**: `SampleItems/` folder workflow with template, search/picker, manual creation — fed to generator as `example_items`
- **Context images**: Attach exam paper images (file picker or vault images) as inline visual context for the LLM during generation
- **PDF upload → concept graph**: Upload a PDF paper; MinerU extracts text, LLM segments into concept nodes + directed edges, auto-created as vault notes with YAML frontmatter
- **Session resume**: Dropdown lists existing `Items/*.md` session notes; resumes via stateless `/continue-round` endpoint (survives Obsidian/backend restarts)
- **Answer grading**: "Grade My Answers" reads user answers from markdown callouts, sends to LLM grader, injects feedback back into the note
- **Manual difficulty selection**: 5-tier dropdown (easy → medium → hard → very_hard → expert); hard+ triggers iterative hardening with actor trajectory analysis + extra concept injection
- **Cancel generation**: "Next Round" button toggles to "Cancel Generation" while in-flight; cancelled results are discarded
- **Clean markdown output**: Generated items written as Obsidian notes with collapsible callouts (Your Answer, Solution, Explanation) — no internal AI agent output visible
- **Frontmatter state**: Session notes store `session_id`, `status`, `difficulty`, `requested_type`, `user_requirements` in YAML frontmatter for resume
- **Semantic concept retrieval**: Backend-powered semantic search in ItemView (OpenAI embeddings + Pinecone). Users can index current concepts or vault notes (YAML `id`), search by meaning, and add hits directly into foundation concepts before generation
- **One-click semantic generation**: `Search + Add + Generate` button runs semantic retrieval, auto-imports mapped hits to foundation concepts, then starts item generation in one action
- **Namespace reset**: `Clear vector namespace` button deletes all vectors under `user_{vectorUserId}_concepts` to recover from stale or mismatched mappings

**Skipping** (community plugins): local flashcard review (obsidian-spaced-repetition), real-time collab editing (Relay), vault-link graph (Extended Graph).

---

## 15 — [Observability](15-observability.md)

| File | Status | What it does |
|---|---|---|
| `app/monitoring.py` | **Completed** | `GET /health`, `GET /ready`; when `PROMETHEUS_METRICS_ENABLED=true`, exposes `GET /metrics` (Prometheus text) via `prometheus-fastapi-instrumentator` |
| `tests/test_monitoring.py` | **Tested** | Health/ready on live app; isolated mini-app with metrics enabled |

Full env vars, verification commands, and example Prometheus scrape: see [15-observability.md](15-observability.md).

---

## Offline item generation evaluation (Braintrust-style)

**Location (all under `evals/item_generation/`, not imported by `app.main`):**

| File | Role |
|------|------|
| `eval.py` | CLI: generation phase → Braintrust `Eval()`, scorers, `eval_metrics.json` export |
| `dataset.json` | Golden cases (`InlineItemGenerateRequest`-shaped `request` per case) |
| `proxy_tokens.py` | Tiktoken proxy counts on request JSON + output (cost proxy, not billing) |
| `extra_metrics.py` | Heuristic scorers (length, markdown shape, foundation coverage, etc.) |
| `llm_judge_scorers.py` | `LLMClassifier` judges (`RubricSatisfaction`, `ItemClarity`) using `AsyncOpenAI` → Anthropic |
| `README.md` | Setup, env vars, dataset notes, `ItemStructural` / id pitfalls |

**Run (from repo root):**

```bash
pip install -r requirements.txt -r requirements-eval.txt
python evals/item_generation/eval.py --skip-llm-judges --no-send-logs   # heuristics only
python evals/item_generation/eval.py --no-send-logs                    # + LLM judges (needs ANTHROPIC_API_KEY)
```

**Artifacts:** default metrics file is `evals/item_generation/eval_metrics.json` (listed in `.gitignore` — regenerate locally; commit `dataset.json` / code only).

---

## Priority Queue (suggested next steps)

*Completed items marked with ~~strikethrough~~.*

1. ~~**CORS middleware** — enable Obsidian plugin connections~~
2. ~~**Item generation** — full pipeline: feasibility → tool-calling generation → actors → reflector → grader~~
3. ~~**Obsidian plugin scaffold** — manifest, build config, settings, API client~~
4. ~~**Obsidian ItemView** — item generation, answer grading, session resume, sample items~~
5. **DB clients** — wire Mongo + Postgres + Pinecone connections
6. **Models + Schemas** — concept, edge Pydantic models (item schemas done)
7. **Concept CRUD** — service + API routes + tests
8. **Edge CRUD** — service + DAG cycle detection + API routes
9. **Auth** — JWT + user model + login/register routes
10. ~~**Embedding pipeline** — embed concepts → index in Pinecone~~
11. **Obsidian GraphView + TraversalView** — first visual panels
12. **Merge pipeline** — similarity verifier + canonical node creation
13. **Obsidian publish command** — save / index / share privacy modes
14. **Traversal engine** — KST outer fringe algorithm
15. **ACE playbooks** — playbook CRUD + curator logic
