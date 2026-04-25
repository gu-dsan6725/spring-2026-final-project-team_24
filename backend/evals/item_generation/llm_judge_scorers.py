"""LLM-as-judge scorers (3) that only need ``output`` + ``expected`` (case id stays ``input`` for ``task``)."""

from __future__ import annotations

from typing import Any


def build_output_only_llm_scorers(client: Any, model: str) -> list[Any]:
    """Two rubrics: alignment with combined rubric+requirements text, and clarity."""
    from autoevals.llm import LLMClassifier

    rubric = LLMClassifier(
        name="RubricSatisfaction",
        prompt_template=(
            "You grade ONE generated study item in markdown.\n"
            "The text in EXPECTED has markers [RUBRIC], [USER_REQUIREMENTS], and [CASE] — "
            "use ONLY that text as the authority (no outside facts).\n\n"
            "EXPECTED:\n{{expected}}\n\n"
            "GENERATED ITEM:\n{{output}}\n\n"
            "Does the item satisfy the rubric and user requirements well enough to ship to students?"
        ),
        choice_scores={"strong_yes": 1.0, "yes": 0.82, "mixed": 0.45, "no": 0.0},
        model=model,
        client=client,
        use_cot=False,
        max_tokens=512,
        temperature=0.0,
    )

    clarity = LLMClassifier(
        name="ItemClarity",
        prompt_template=(
            "Rate structural clarity of this study item only (organization, readability, "
            "not whether facts are correct).\n\n{{output}}\n\n"
            "Choose the best label."
        ),
        choice_scores={"excellent": 1.0, "good": 0.76, "weak": 0.38, "confusing": 0.0},
        model=model,
        client=client,
        use_cot=False,
        max_tokens=384,
        temperature=0.0,
    )

    return [rubric, clarity]


def combined_rubric_expected(case: dict[str, Any]) -> str:
    """Pack rubric + requirements into ``expected`` for output-only judges."""
    req = case.get("request") or {}
    parts = [
        "[RUBRIC]",
        (case.get("expected_output") or "").strip(),
        "",
        "[USER_REQUIREMENTS]",
        (req.get("user_requirements") or "").strip(),
        "",
        "[CASE]",
        (case.get("description") or "").strip(),
    ]
    return "\n".join(parts).strip()
