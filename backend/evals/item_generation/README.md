# Item generation offline evals (Lab 1 pattern)

Uses **Braintrust `Eval()`** + **autoevals** + **custom scorers** — all under `evals/item_generation/` only (not imported by `app.main`).

### Scorers (current)

| Group | Names |
|-------|--------|
| **(1) Proxy cost / time** | `ProxyTokenEfficiency` (tiktoken `cl100k_base` on request JSON + output text — **not** API billing), `Latency` (wall-clock band from generation phase) |
| **(2) Heuristics** | `BodyLengthBand`, `AnswerLength`, `MarkdownStructure`, `ProblemPromptShape` (for `problem` type), `FoundationCoverage` |
| **(3) LLM judges** (unless `--skip-llm-judges`) | `RubricSatisfaction`, `ItemClarity` — `LLMClassifier` prompts that use only `{{expected}}` + `{{output}}` so `input` can stay the case id for caching |
| **Existing gates** | `NoRunError`, `FeasibilityAlign`, `ItemStructural` (`item_evaluation`), `OutputNonEmpty` |

`expected` passed to Braintrust is a **packed block** (`[RUBRIC]`, `[USER_REQUIREMENTS]`, `[CASE]`) built in `llm_judge_scorers.combined_rubric_expected()` so judges do not rely on `input` being prose.

## Setup

**Use a project virtualenv** (`python -m venv .venv` then `source .venv/bin/activate`), not Anaconda **base**. Installing `requirements.txt` into base conda upgrades/downgrades many unrelated packages (torch, pytest, httpx, …) and can break other tools.

```bash
cd /path/to/finalproj-backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-eval.txt
```

Set API keys in the **repository root** `.env` (same as the app):

| What | Env vars |
|------|-----------|
| **Item generation** (always runs first) | Default `ITEM_GENERATION_PROVIDER` is **`anthropic`** → set `ANTHROPIC_API_KEY`. To use Groq instead: `ITEM_GENERATION_PROVIDER=groq` and `GROQ_API_KEY`. |
| **LLM judges** (on unless `--skip-llm-judges`) | `ANTHROPIC_API_KEY`; judge uses **`AsyncOpenAI`** against Anthropic’s OpenAI-compatible base URL (Braintrust awaits scorer calls). |
| **Braintrust** (optional if you use cloud logging) | `BRAINTRUST_API_KEY`; override project with `BRAINTRUST_PROJECT`. |

`--skip-llm-judges` only skips **judge** calls. It does **not** switch the generation provider; if generation fails (missing key), you will see `NoRunError` / `OutputNonEmpty` / `FeasibilityAlign` at **0%** and `generation_error` in `eval_metrics.json` — check the console **ERROR** lines after the generation phase.

`--no-send-logs` only disables **uploading** traces to Braintrust; it does **not** turn off LLM judges.

## Run

From repo root:

```bash
python evals/item_generation/eval.py
python evals/item_generation/eval.py --no-send-logs
python evals/item_generation/eval.py --skip-llm-judges --no-send-logs
python evals/item_generation/eval.py --dataset evals/item_generation/dataset.json --output evals/item_generation/eval_metrics.json
```

Implementation note: item generation runs **before** Braintrust `Eval()` so we never call `asyncio.run()` inside Braintrust’s own event loop (which would raise `RuntimeError: asyncio.run() cannot be called from a running event loop`).

## Dataset format

`dataset.json` is a list of cases. Each case needs:

| Field | Meaning |
|--------|--------|
| `id` | Stable id (used as Braintrust `input` and cache key). |
| `category` | For your own breakdowns in the printed summary. |
| `expected_output` | Rubric text; folded into the packed `expected` for LLM judges + kept as `expected_rubric_short` in row metadata. |
| `request` | JSON matching **`InlineItemGenerateRequest`** (`app.schemas.item`). |

Optional: `expect_abandon: true` if the case is meant to trigger **ABANDON** (then `FeasibilityAlign` expects that outcome).

### `ItemStructural` / coverage rejections

`item_evaluation.coverage_check` requires every `foundation_concept_id` on the generated item to match an **`id` from the inline `concepts` list** in that case’s `request`. LLMs often wrongly emit titles or slug-like names instead of ids (e.g. `Arithmetic mean` instead of `c_mean`). Use an explicit sentence in `user_requirements` listing the allowed id strings, as in the default `dataset.json`.

## Outputs

- Console summary (per-scorer averages).
- **`eval_metrics.json`** — per case includes **`timings.wall_ms`**, **`proxy_metrics`** (`proxy_*_tokens`, `proxy_encoding`), **`generation_error`** when present, plus Braintrust scores.

Add `eval_metrics*.json` to `.gitignore` locally if you do not want runs committed.
