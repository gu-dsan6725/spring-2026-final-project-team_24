# DSAN 6725 — Team 24 Final Project

**Dependency-aware, multi-agent item generation for personalized study inside Obsidian.**

An Obsidian plugin + FastAPI backend that turns a learner's own notes into
scheduled practice items. A multi-agent pipeline builds a dependency
graph over the learner's concepts, generates problems that respect that
graph, grades the learner's answers at concept-level granularity, and
updates per-concept mastery so the next round combines mastered concepts
into harder integration items instead of re-drilling them.

## What's in this repo

```
team_24/
├── backend/        FastAPI app + AI pipelines + Obsidian plugin source
│   ├── app/        Schemas, API, AI pipelines (graph agents, generator,
│   │               grader, sample analyzer), provider adapters
│   ├── plugin/     Obsidian plugin (TypeScript, esbuild)
│   ├── tests/      Pytest suite (pipeline unit tests, fixture-driven
│   │               evals)
│   ├── evals/      Offline item-evaluation harness
│   ├── notes/      Architecture design docs referenced by the paper
│   └── references/ Citations used in the paper
├── slides/         Presentation slides (Quarto → PDF/RevealJS)
├── paper/          Conference-style paper (PDF + source)
├── poster/         Conference poster (PDF)
└── docs/           Project website (Quarto, GitHub Pages)
```

## Feature highlights (what's implemented and in this submission)

- **Dependency-aware scheduling.** Backend agents (`app/ai/pipelines/graph/`)
  build a concept dependency graph; items are generated top-down so
  prerequisites are exercised before their dependents. A depth-aware
  scheduler auto-advances `focus_depth` when mastery thresholds are hit.
- **Per-concept grading.** `app/ai/pipelines/answer_grader.py` returns a
  verdict per concept (`correct` / `alt_path` / `misunderstood` /
  `untested`), not just a scalar — alternate solutions still credit the
  concept, and a single wrong answer never punishes concepts the
  learner didn't even touch.
- **Elo-style mastery tracking.** The plugin updates per-concept mastery
  from the verdicts and sends `user_mastery` back to the generator, so
  mastered concepts graduate to *integration* items instead of
  re-drilling.
- **Multimodal sample analyzer.** Learners drop a markdown sample *or an
  image of an exam problem*; `app/ai/pipelines/sample_analyzer.py`
  sends it to a multimodal LLM (OpenAI / Anthropic) and returns
  structured pedagogical feedback (covered concepts, catalog gaps,
  estimated difficulty, pedagogical notes). The analysis is threaded
  back into the generator prompt as `analysis_notes` so few-shot
  samples carry intent, not just text.
- **Coverage visualization.** A single dense row in the Obsidian view
  where each cell is a concept ordered by dependency depth; cell color
  tracks the highest difficulty the learner has exercised that concept
  at, with tick marks for depth boundaries and the current focus
  cutoff.
- **PDF → concepts ingest.** MinerU-backed paper ingest splits a PDF
  into per-section markdown with image references; each section
  becomes a concept candidate, and the backend can embed and persist
  vectors for retrieval.

See `backend/README.md` for a deeper architectural walkthrough and
`backend/notes/` for per-module design specs.

## Running it

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env   # fill in OPENAI_API_KEY / ANTHROPIC_API_KEY / GROQ_API_KEY
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Obsidian plugin

```bash
cd backend/plugin
npm install
OBSIDIAN_VAULT_PLUGIN_DIR="/path/to/YourVault" npm run deploy
```

Reload Obsidian. The plugin's settings tab asks for the backend URL
(defaults to `http://127.0.0.1:8000`).

### Tests

```bash
cd backend
pytest -q
```

## Deliverables

| Deliverable | Location | Status |
|---|---|---|
| Code repository | `backend/` | Included |
| Paper (8-12 pp, conference format) | `paper/` | Draft forthcoming |
| Slides | `slides/plugin-demo.qmd` | Draft included |
| Poster (48" × 36") | `poster/` | Forthcoming |
| Project website | `docs/` | Forthcoming |
| Demo video / link | `docs/demo.md` | Forthcoming |

## Team

Team 24 — DSAN 6725 Applied GenAI, Spring 2026.

## License

MIT. See [`LICENSE`](LICENSE).
