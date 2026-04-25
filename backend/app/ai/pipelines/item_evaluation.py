"""Item evaluation pipeline — structural and coverage quality gate.

Validates generated items before they enter the item pool.

POC scope:
  - Structural integrity: all required fields present and non-empty.
  - Coverage check: every foundation_concept_id in the item must be in
    the input concept list.

Deferred:
  - Dedup against existing items (needs Pinecone item pool).
  - Answer correctness verification (needs Meta-Harness Actor).
"""

from __future__ import annotations

import logging

from app.schemas.item import EvalOutcome, FeasibilityOutcome, GeneratedItem

logger = logging.getLogger(__name__)


def structural_check(item: GeneratedItem) -> tuple[bool, str]:
    """Verify that the item has all required non-empty fields."""
    if not item.title.strip():
        return False, "Item title is empty."
    if not item.body_md.strip():
        return False, "Item body is empty."
    if not item.answer_md.strip():
        return False, "Item answer is empty."
    if not item.foundation_concept_ids:
        return False, "No foundation concept IDs specified."
    return True, ""


def coverage_check(
    item: GeneratedItem,
    valid_concept_ids: set[str],
) -> tuple[bool, str]:
    """Verify that every concept ID in the item is in the input set."""
    unknown = [
        cid for cid in item.foundation_concept_ids
        if cid not in valid_concept_ids
    ]
    if unknown:
        return False, f"Item references unknown concept IDs: {unknown}"
    return True, ""


def evaluate(
    item: GeneratedItem,
    valid_concept_ids: set[str],
    feasibility: FeasibilityOutcome = FeasibilityOutcome.GENERATE,
) -> tuple[EvalOutcome, str]:
    """Run all checks and return (outcome, reason).

    If feasibility was GENERATE_WITH_REVIEW and the item passes structural
    checks, it is flagged for review rather than accepted outright.
    """
    ok, reason = structural_check(item)
    if not ok:
        logger.info("Item %r rejected: %s", item.title, reason)
        return EvalOutcome.REJECT, reason

    ok, reason = coverage_check(item, valid_concept_ids)
    if not ok:
        logger.info("Item %r rejected: %s", item.title, reason)
        return EvalOutcome.REJECT, reason

    if feasibility == FeasibilityOutcome.GENERATE_WITH_REVIEW:
        return EvalOutcome.FLAG_FOR_REVIEW, "Domain requires review before acceptance."

    return EvalOutcome.ACCEPT, ""
