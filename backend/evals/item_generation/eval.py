# Offline evaluations for item generation (Lab 1 pattern: Braintrust Eval + scorers).
#
# Does not import from FastAPI startup — run from repo root:
#   pip install -r requirements.txt -r requirements-eval.txt
#   cp evals/item_generation/.env.example evals/item_generation/.env  # optional
#   python evals/item_generation/eval.py
#   python evals/item_generation/eval.py --no-send-logs --skip-llm-judges
#
# Item generation uses ``app.config.settings.ITEM_GENERATION_PROVIDER`` (default: anthropic).
# Set the matching key in repo root ``.env`` (e.g. ``ANTHROPIC_API_KEY``, or ``GROQ_API_KEY`` + ``ITEM_GENERATION_PROVIDER=groq``).
# LLM judges (optional): ``RubricSatisfaction`` + ``ItemClarity`` via autoevals ``LLMClassifier`` — see ``--skip-llm-judges``.

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

# Repo root on sys.path (so `import app` works when not installed as package)
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Sibling modules in this directory (``python evals/item_generation/eval.py``)
_IGEN = Path(__file__).resolve().parent
if str(_IGEN) not in sys.path:
    sys.path.insert(0, str(_IGEN))

from extra_metrics import (  # noqa: E402
    answer_length_scorer,
    body_length_band_scorer,
    foundation_coverage_scorer,
    markdown_structure_scorer,
    problem_has_prompt_scorer,
    proxy_token_efficiency_scorer,
)
from llm_judge_scorers import build_output_only_llm_scorers, combined_rubric_expected  # noqa: E402
from proxy_tokens import estimate_proxy_tokens  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s,p%(process)s,{%(filename)s:%(lineno)d},%(levelname)s,%(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_DATASET_PATH = Path(__file__).resolve().parent / "dataset.json"
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parent / "eval_metrics.json"
BRAINTRUST_PROJECT_NAME = os.getenv("BRAINTRUST_PROJECT", "finalproj-item-generation")
EVAL_JUDGE_MODEL = os.getenv("EVAL_JUDGE_MODEL", "claude-sonnet-4-6")
ANTHROPIC_OPENAI_BASE_URL = "https://api.anthropic.com/v1/"


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(_ROOT / ".env")
    load_dotenv(Path(__file__).resolve().parent / ".env")


def _create_judge_client():
    """Async client — Braintrust runs scorers with ``await``; sync ``OpenAI()`` breaks."""
    from openai import AsyncOpenAI

    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise ValueError("ANTHROPIC_API_KEY not set (needed for LLM-as-judge scorers)")
    return AsyncOpenAI(api_key=key, base_url=ANTHROPIC_OPENAI_BASE_URL)


def _load_dataset(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    logger.info("Loaded %d cases from %s", len(data), path)
    return data


def _session_output_and_meta(
    case: dict[str, Any],
    resp: Any,
    latency_seconds: float,
    error: Optional[str],
) -> tuple[str, dict[str, Any]]:
    """Build Braintrust `output` string and scorer metadata."""
    from app.schemas.item import SessionResponse

    if error:
        return f"[error] {error}", {
            "category": case.get("category", ""),
            "latency_seconds": latency_seconds,
            "feasibility": "ERROR",
            "items": [],
            "valid_concept_ids": [],
            "expect_abandon": case.get("expect_abandon", False),
            "run_error": error,
        }

    assert isinstance(resp, SessionResponse)
    feas = resp.feasibility.value if hasattr(resp.feasibility, "value") else str(resp.feasibility)
    req = case["request"]
    valid_ids = {c["id"] for c in req.get("concepts", [])}

    if feas == "ABANDON" or not resp.rounds or not resp.rounds[0].items:
        text = f"[feasibility={feas}]\n"
        if resp.rounds and resp.rounds[0].items:
            text += _items_to_text(resp.rounds[0].items)
        else:
            text += "No items in first round."
        meta = {
            "category": case.get("category", ""),
            "latency_seconds": latency_seconds,
            "feasibility": feas,
            "items": [it.model_dump() for it in (resp.rounds[0].items if resp.rounds else [])],
            "valid_concept_ids": list(valid_ids),
            "expect_abandon": case.get("expect_abandon", False),
        }
        return text, meta

    items = resp.rounds[0].items
    text = _items_to_text(items)
    meta = {
        "category": case.get("category", ""),
        "latency_seconds": latency_seconds,
        "feasibility": feas,
        "items": [it.model_dump() for it in items],
        "valid_concept_ids": list(valid_ids),
        "expect_abandon": case.get("expect_abandon", False),
    }
    return text, meta


def _items_to_text(items: list[Any]) -> str:
    parts: list[str] = []
    for it in items:
        parts.append(
            f"## {it.title}\n{it.body_md}\n### Answer\n{it.answer_md}\n### Explanation\n{it.explanation_md}"
        )
    return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# Custom scorers (Braintrust-compatible callables)
# ---------------------------------------------------------------------------


def latency_scorer(
    input: str,
    output: str,
    expected: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> Optional[dict]:
    if not metadata:
        return None
    latency = metadata.get("latency_seconds")
    if latency is None:
        return None
    if latency < 15:
        score = 1.0
    elif latency < 45:
        score = 0.75
    elif latency < 90:
        score = 0.5
    elif latency < 180:
        score = 0.25
    else:
        score = 0.0
    return {
        "name": "Latency",
        "score": score,
        "metadata": {"latency_seconds": round(float(latency), 2)},
    }


def no_run_error_scorer(
    input: str,
    output: str,
    expected: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> dict:
    if not metadata:
        return {"name": "NoRunError", "score": 0.0, "metadata": {"reason": "no metadata"}}
    err = metadata.get("run_error")
    if err:
        return {"name": "NoRunError", "score": 0.0, "metadata": {"error": err[:500]}}
    return {"name": "NoRunError", "score": 1.0, "metadata": {}}


def feasibility_alignment_scorer(
    input: str,
    output: str,
    expected: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> Optional[dict]:
    """If expect_abandon, reward ABANDON; otherwise reward non-ABANDON."""
    if not metadata:
        return None
    expect_abandon = metadata.get("expect_abandon", False)
    feas = metadata.get("feasibility", "")
    if feas == "ERROR":
        return {"name": "FeasibilityAlign", "score": 0.0, "metadata": {"feasibility": feas}}
    is_abandon = feas == "ABANDON"
    if expect_abandon:
        score = 1.0 if is_abandon else 0.0
    else:
        score = 0.0 if is_abandon else 1.0
    return {
        "name": "FeasibilityAlign",
        "score": score,
        "metadata": {"feasibility": feas, "expect_abandon": expect_abandon},
    }


def item_structural_scorer(
    input: str,
    output: str,
    expected: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> Optional[dict]:
    """Reuse app item_evaluation on the first generated item."""
    if not metadata or metadata.get("run_error"):
        return None
    raw_items = metadata.get("items") or []
    if not raw_items:
        return None
    from app.ai.pipelines import item_evaluation
    from app.schemas.item import (
        EvalOutcome,
        FeasibilityOutcome,
        GeneratedItem,
    )

    item = GeneratedItem.model_validate(raw_items[0])
    valid = set(metadata.get("valid_concept_ids") or [])
    feas_raw = metadata.get("feasibility", "GENERATE")
    try:
        feas = FeasibilityOutcome(feas_raw)
    except ValueError:
        feas = FeasibilityOutcome.GENERATE_WITH_REVIEW
    outcome, reason = item_evaluation.evaluate(item, valid, feas)
    if outcome == EvalOutcome.ACCEPT:
        score = 1.0
    elif outcome == EvalOutcome.FLAG_FOR_REVIEW:
        score = 0.7
    else:
        score = 0.0
    return {
        "name": "ItemStructural",
        "score": score,
        "metadata": {"outcome": outcome.value, "reason": reason[:300]},
    }


def output_non_empty_scorer(
    input: str,
    output: str,
    expected: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> dict:
    if metadata and metadata.get("expect_abandon"):
        return {"name": "OutputNonEmpty", "score": 1.0, "metadata": {"skipped": True}}
    ok = bool(output and len(output.strip()) > 20 and not output.startswith("[error]"))
    return {"name": "OutputNonEmpty", "score": 1.0 if ok else 0.0, "metadata": {"length": len(output or "")}}


async def _generate_all_cases_async(
    dataset: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Run ``start_session`` for every case (must run outside Braintrust's event loop)."""
    from app.schemas.item import InlineItemGenerateRequest
    from app.services.item_service import start_session

    results_cache: dict[str, dict[str, Any]] = {}
    for case in dataset:
        case_id = case["id"]
        logger.info("Running item generation for case %s", case_id)
        req = InlineItemGenerateRequest.model_validate(case["request"])
        t0 = time.time()
        try:
            resp = await start_session(req)
            latency = time.time() - t0
            out, meta = _session_output_and_meta(case, resp, latency, error=None)
        except Exception as e:  # noqa: BLE001 — eval harness captures all failures
            latency = time.time() - t0
            out, meta = _session_output_and_meta(
                case, None, latency, error=f"{type(e).__name__}: {e}"
            )
        pm = estimate_proxy_tokens(case["request"], out)
        meta.update(pm)
        results_cache[case_id] = {"output": out, "metadata": meta}
    return results_cache


def _run_generation_phase(dataset: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Single top-level ``asyncio.run`` — Braintrust ``Eval()`` also uses asyncio internally."""
    return asyncio.run(_generate_all_cases_async(dataset))


def _log_generation_failures(results_cache: dict[str, dict[str, Any]]) -> None:
    """If generation failed before the LLM, scorers will look 'broken' — surface the real error."""
    from app.config import settings

    failed = False
    for cid, entry in results_cache.items():
        err = (entry.get("metadata") or {}).get("run_error")
        if err:
            failed = True
            logger.error("Generation failed for case %r: %s", cid, err if isinstance(err, str) else str(err))
    if failed:
        logger.error(
            "Configured ITEM_GENERATION_PROVIDER is %r (see app/config.py). "
            "Set the matching API key in the repo root .env — e.g. ANTHROPIC_API_KEY for "
            "'anthropic', or GROQ_API_KEY plus ITEM_GENERATION_PROVIDER=groq. "
            "``--skip-llm-judges`` only disables judge models; it does not replace the generation provider.",
            settings.ITEM_GENERATION_PROVIDER,
        )


def _create_wrapped_task(
    dataset: list[dict[str, Any]],
    results_cache: dict[str, dict[str, Any]],
):
    """Braintrust ``data``/``task`` read precomputed cache (no asyncio inside callbacks)."""

    def data():
        rows = []
        for case in dataset:
            cid = case["id"]
            cached = results_cache[cid]
            req = case.get("request") or {}
            rows.append({
                "input": cid,
                "expected": combined_rubric_expected(case),
                "metadata": {
                    **cached["metadata"],
                    "case_description": case.get("description", ""),
                    "expected_rubric_short": (case.get("expected_output") or "")[:400],
                    "requested_type": str(req.get("requested_type", "problem")),
                },
            })
        return rows

    def task(input: str) -> str:
        if input in results_cache:
            return results_cache[input]["output"]
        raise KeyError(f"Unknown case id: {input!r}")

    return task, data


def _print_eval_summary(eval_result: Any, dataset: list[dict[str, Any]]) -> None:
    results = eval_result.results
    if not results:
        logger.warning("No evaluation results")
        return

    id_to_category = {c["id"]: c.get("category", "unknown") for c in dataset}
    scorer_scores: dict[str, list[float]] = {}
    category_scores: dict[str, list[float]] = {}
    errors: list[dict[str, str]] = []

    for r in results:
        inp = str(r.input) if r.input else ""
        cat = id_to_category.get(inp, "unknown")
        if r.error:
            errors.append({"input": inp, "error": str(r.error)})
            continue
        for name, val in (r.scores or {}).items():
            if val is None:
                continue
            scorer_scores.setdefault(name, []).append(float(val))
            category_scores.setdefault(f"{cat}/{name}", []).append(float(val))

    print("\n" + "=" * 72)
    print("ITEM GENERATION EVAL SUMMARY")
    print("=" * 72)
    print(f"Cases: {len(results)}  Errors: {len(errors)}\n")
    print(f"{'Scorer':<28} {'Avg':>10} {'Min':>8} {'Max':>8} {'N':>6}")
    print("-" * 72)
    for name in sorted(scorer_scores.keys()):
        xs = scorer_scores[name]
        print(
            f"{name:<28} {sum(xs)/len(xs):>10.2%} {min(xs):>8.2f} {max(xs):>8.2f} {len(xs):>6}"
        )
    print("=" * 72 + "\n")
    for e in errors:
        print("ERROR", e)


def _export_eval_metrics(
    eval_result: Any,
    dataset: list[dict[str, Any]],
    output_path: Path,
    results_cache: dict[str, dict[str, Any]] | None = None,
) -> None:
    results = eval_result.results
    id_to_category = {c["id"]: c.get("category", "unknown") for c in dataset}
    per_case: list[dict[str, Any]] = []
    scorer_scores: dict[str, list[float]] = {}

    for r in results:
        inp = str(r.input) if r.input else ""
        row: dict[str, Any] = {
            "case_id": inp,
            "category": id_to_category.get(inp, "unknown"),
            "scores": {},
            "error": str(r.error) if r.error else None,
        }
        if results_cache and inp in results_cache:
            meta = results_cache[inp].get("metadata") or {}
            ge = meta.get("run_error")
            if ge:
                row["generation_error"] = ge if isinstance(ge, str) else str(ge)
            lat = meta.get("latency_seconds")
            if lat is not None:
                row["timings"] = {"wall_ms": round(float(lat) * 1000.0, 2)}
            pm_keys = (
                "proxy_prompt_tokens",
                "proxy_completion_tokens",
                "proxy_total_tokens",
                "proxy_encoding",
            )
            pm = {k: meta[k] for k in pm_keys if meta.get(k) is not None}
            if pm:
                row["proxy_metrics"] = pm
        if not r.error and r.scores:
            for k, v in r.scores.items():
                if v is None:
                    continue
                fv = round(float(v), 4)
                row["scores"][k] = fv
                scorer_scores.setdefault(k, []).append(float(v))
        per_case.append(row)

    overall = {
        k: {
            "average": round(sum(v) / len(v), 4),
            "min": round(min(v), 4),
            "max": round(max(v), 4),
            "count": len(v),
        }
        for k, v in sorted(scorer_scores.items())
    }

    payload = {
        "total_cases": len(results),
        "overall_scores": overall,
        "per_case": per_case,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    logger.info("Wrote metrics to %s", output_path)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Braintrust-style offline evals for item generation")
    p.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    p.add_argument("--no-send-logs", action="store_true", help="Do not send results to Braintrust")
    p.add_argument(
        "--skip-llm-judges",
        action="store_true",
        help="Skip LLM judges (RubricSatisfaction, ItemClarity); keep heuristics only",
    )
    p.add_argument("--experiment-name", type=str, default=None)
    p.add_argument("--debug", action="store_true")
    return p.parse_args()


def main() -> None:
    _load_dotenv()
    args = _parse_args()
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        from braintrust import Eval
    except ImportError as e:
        raise SystemExit(
            "Missing eval dependencies. Install with:\n"
            "  pip install -r requirements.txt -r requirements-eval.txt\n"
            f"Import error: {e}"
        ) from e

    dataset = _load_dataset(args.dataset)
    logger.info("Generation phase (%d cases, before Braintrust Eval)...", len(dataset))
    results_cache = _run_generation_phase(dataset)
    _log_generation_failures(results_cache)
    task_fn, data_fn = _create_wrapped_task(dataset, results_cache)

    judge_client = None
    all_scorers: list[Any] = []
    if not args.skip_llm_judges:
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise SystemExit(
                "ANTHROPIC_API_KEY is not set, but LLM-as-judge scorers (RubricSatisfaction, ItemClarity) are enabled.\n\n"
                "Fix one of:\n"
                "  1) Add ANTHROPIC_API_KEY to the repo root .env (same as the course lab judge), or\n"
                "  2) Run without judges:\n"
                "       python evals/item_generation/eval.py --skip-llm-judges --no-send-logs\n\n"
                "Note: --no-send-logs only skips uploading to Braintrust; it does not skip judges."
            )
        judge_client = _create_judge_client()
        # Output+expected-only judges (datum.input stays case id for ``task`` caching).
        all_scorers.extend(build_output_only_llm_scorers(judge_client, EVAL_JUDGE_MODEL))
    all_scorers.extend([
        latency_scorer,
        no_run_error_scorer,
        feasibility_alignment_scorer,
        item_structural_scorer,
        output_non_empty_scorer,
        proxy_token_efficiency_scorer,
        body_length_band_scorer,
        answer_length_scorer,
        markdown_structure_scorer,
        problem_has_prompt_scorer,
        foundation_coverage_scorer,
    ])

    eval_kwargs: dict[str, Any] = {
        "data": data_fn,
        "task": task_fn,
        "scores": all_scorers,
    }
    if args.experiment_name:
        eval_kwargs["experiment_name"] = args.experiment_name
    if args.no_send_logs:
        eval_kwargs["no_send_logs"] = True

    t0 = time.time()
    logger.info("Starting Eval (%s)...", BRAINTRUST_PROJECT_NAME)
    eval_result = Eval(BRAINTRUST_PROJECT_NAME, **eval_kwargs)
    _print_eval_summary(eval_result, dataset)
    _export_eval_metrics(eval_result, dataset, args.output, results_cache=results_cache)
    logger.info("Done in %.1fs", time.time() - t0)


if __name__ == "__main__":
    main()
