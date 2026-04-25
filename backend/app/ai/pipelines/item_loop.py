"""Item generation loop orchestrator — inner refinement + outer progression.

Inner loop (refinement):
  Generator -> Actors solve -> Reflector evaluates -> feedback -> re-generate
  Up to MAX_REFINEMENT_ITERATIONS if quality is insufficient.

Outer loop (difficulty progression):
  Managed by the service layer.  After the user completes a round:
  Grader evaluates -> accumulate context -> Generator produces harder items.

Iterative hardening (hard / very_hard / expert):
  For difficulties above medium, items are first generated at medium, then
  a hardening reflector produces "make harder" directives + pulls in random
  extra concepts from the user's knowledge graph.  The generator re-generates
  with those directives up to 3 times, producing progressively harder items
  that remain solvable because they draw on knowledge the user actually has.

All context is accumulated as tool-calling JSON across rounds.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.ai.pipelines import actor, item_evaluation, reflector
from app.ai.pipelines.item_construction import (
    build_concept_view,
    generate as generate_items,
)
from app.config import settings
from app.schemas.item import (
    Difficulty,
    EvalOutcome,
    FeasibilityOutcome,
    GeneratedItem,
    ReflectorFeedback,
    RoundResult,
)

logger = logging.getLogger(__name__)

_HARDENING_TIERS: dict[str, int] = {
    Difficulty.HARD: 1,
    Difficulty.VERY_HARD: 2,
    Difficulty.EXPERT: 3,
}


def _needs_hardening(difficulty: str) -> int:
    """Return the number of hardening iterations needed, or 0 for standard."""
    return _HARDENING_TIERS.get(difficulty, 0)


async def refine_round(
    concept_views: list[dict[str, Any]],
    edge_views: list[dict[str, Any]],
    example_item_views: list[dict[str, Any]],
    request: dict[str, Any],
    user_concepts: list[dict[str, Any]],
    valid_concept_ids: set[str],
    *,
    history: list[dict[str, Any]] | None = None,
    n_items: int | None = None,
    user_requirements: str = "",
    difficulty: str = "medium",
    feasibility: FeasibilityOutcome = FeasibilityOutcome.GENERATE,
    provider: str | None = None,
    round_number: int = 1,
    context_images: list[dict[str, Any]] | None = None,
    all_user_concepts: list[dict[str, Any]] | None = None,
) -> RoundResult:
    """Execute the inner refinement loop for one round.

    For easy/medium:
      Standard path — generate → actors solve → reflector evaluates → refine.

    For hard/very_hard/expert:
      1. Generate items at *medium* difficulty first.
      2. Hardening loop (1-3 iterations depending on tier):
         a. Hardening reflector reviews items + random extra user concepts →
            produces "make harder" directives + extra concept titles.
         b. Extra concepts are injected into the generator context.
         c. Generator re-generates with hardening directives appended to
            user_requirements.
      3. Final items go through the normal actor→reflector quality gate.
    """
    items_per_round = n_items or settings.ITEMS_PER_ROUND
    max_iters = settings.MAX_REFINEMENT_ITERATIONS
    prov = provider or settings.ITEM_GENERATION_PROVIDER
    hardening_iters = min(
        _needs_hardening(difficulty),
        settings.MAX_HARDENING_ITERATIONS,
    )

    # For hardened difficulties, start at medium
    gen_difficulty = "medium" if hardening_iters > 0 else difficulty

    all_items: list[GeneratedItem] = []
    all_trajectories = []
    all_feedback: list[ReflectorFeedback] = []
    all_eval_outcomes: list[EvalOutcome] = []

    generation_request = dict(request)
    generation_request["difficulty_preference"] = gen_difficulty

    refinement_history = list(history or [])

    # Track which concept titles are already in the generation context
    current_concept_titles = {c.get("title", "") for c in concept_views}

    # Mutable copies — hardening may expand these
    active_concept_views = list(concept_views)
    active_user_requirements = user_requirements

    # ------------------------------------------------------------------
    # Phase 1: initial generation + quality refinement (standard path)
    # ------------------------------------------------------------------

    for iteration in range(max_iters):
        logger.info(
            "Round %d, refinement iteration %d/%d",
            round_number, iteration + 1, max_iters,
        )

        items = await generate_items(
            active_concept_views,
            edge_views,
            example_item_views,
            generation_request,
            history=refinement_history,
            n_items=items_per_round,
            user_requirements=active_user_requirements,
            provider=prov,
            context_images=context_images,
        )

        if not items:
            logger.warning("Generator produced no items in iteration %d", iteration + 1)
            break

        trajectories = await asyncio.gather(*[
            actor.solve(item, user_concepts, provider=prov)
            for item in items
        ])

        feedback = await reflector.evaluate(
            items,
            list(trajectories),
            user_concepts,
            user_requirements=active_user_requirements,
            provider=prov,
        )

        approved_items = []
        for item, fb in zip(items, feedback):
            if fb.approved:
                approved_items.append(item)

        all_items = list(approved_items) if approved_items else list(items)
        all_trajectories = list(trajectories)
        all_feedback = list(feedback)

        approval_rate = len(approved_items) / len(items) if items else 0

        if approval_rate >= 0.5 or iteration + 1 >= max_iters:
            break

        logger.info(
            "Only %.0f%% approved; refining (iteration %d)",
            approval_rate * 100, iteration + 1,
        )
        refinement_history.append({
            "round_number": round_number,
            "items": [i.model_dump() for i in items],
            "reflector_feedback": [f.model_dump() for f in feedback],
        })

    # ------------------------------------------------------------------
    # Phase 2: iterative hardening (hard / very_hard / expert only)
    # ------------------------------------------------------------------

    if hardening_iters > 0 and all_items:
        pool = all_user_concepts if all_user_concepts else user_concepts
        logger.info(
            "Entering hardening phase: %d iteration(s) for difficulty=%s",
            hardening_iters, difficulty,
        )

        # Snapshot the pre-hardening history; hardening uses a single-slot
        # context that is *replaced* each iteration (not accumulated) so
        # the generator only sees item(i), not item(0)+item(1)+...+item(i).
        base_history = list(refinement_history)

        for h_iter in range(1, hardening_iters + 1):
            logger.info(
                "Round %d, hardening iteration %d/%d",
                round_number, h_iter, hardening_iters,
            )

            hardening_results = await reflector.hardening_evaluate(
                all_items,
                all_trajectories,
                pool,
                current_concept_titles,
                iteration=h_iter,
                provider=prov,
            )

            extra_titles: set[str] = set()
            directives_text_parts: list[str] = []
            for hr in hardening_results:
                extra_titles.update(hr.get("extra_concept_titles", []))
                for d in hr.get("hardening_directives", []):
                    directives_text_parts.append(d)

            for uc in pool:
                title = uc.get("title", "")
                if title in extra_titles and title not in current_concept_titles:
                    view = build_concept_view(
                        {"title": title, "body_md": uc.get("body_md", ""), "content_type": uc.get("content_type", "markdown")},
                        mastery=uc.get("user_mastery"),
                        connected_titles=None,
                    )
                    view["relationship_to_request"] = "additional concept (hardening: user knows this)"
                    active_concept_views.append(view)
                    current_concept_titles.add(title)

            hardening_instruction = (
                f"\n\n[HARDENING ITERATION {h_iter}/{hardening_iters}] "
                "You MUST make each item SIGNIFICANTLY harder than the previous version. "
                "Specific directives from the reflector:\n"
                + "\n".join(f"- {d}" for d in directives_text_parts)
            )
            if extra_titles:
                hardening_instruction += (
                    f"\n\nAdditional concepts the user knows (weave into problems): "
                    + ", ".join(sorted(extra_titles))
                )

            hardened_requirements = active_user_requirements + hardening_instruction

            # Single-slot replacement: base_history + ONE entry for the
            # current items to harden.  item(i+1) = f(item(i)), no accumulation.
            # Includes actor trajectories so the generator sees HOW the actor
            # solved each item and can target the easy parts.
            hardening_history = base_history + [{
                "round_number": round_number,
                "items": [i.model_dump() for i in all_items],
                "actor_trajectories": [t.model_dump() for t in all_trajectories],
                "reflector_feedback": [
                    {
                        "item_title": hr_item.title,
                        "quality_score": 0.6,
                        "issues": ["Difficulty too low — needs hardening"],
                        "suggestions": hardening_results[idx].get("hardening_directives", []),
                        "approved": False,
                    }
                    for idx, hr_item in enumerate(all_items)
                ],
            }]

            generation_request["difficulty_preference"] = difficulty

            items = await generate_items(
                active_concept_views,
                edge_views,
                example_item_views,
                generation_request,
                history=hardening_history,
                n_items=items_per_round,
                user_requirements=hardened_requirements,
                provider=prov,
                context_images=context_images,
            )

            if not items:
                logger.warning("Hardening iteration %d produced no items", h_iter)
                break

            trajectories = await asyncio.gather(*[
                actor.solve(item, user_concepts, provider=prov)
                for item in items
            ])

            feedback = await reflector.evaluate(
                items,
                list(trajectories),
                user_concepts,
                user_requirements=hardened_requirements,
                provider=prov,
            )

            all_items = list(items)
            all_trajectories = list(trajectories)
            all_feedback = list(feedback)

            logger.info(
                "Hardening iteration %d complete — %d items produced",
                h_iter, len(items),
            )

    # ------------------------------------------------------------------
    # Phase 3: structural/coverage evaluation on final items
    # ------------------------------------------------------------------

    for item in all_items:
        outcome, reason = item_evaluation.evaluate(
            item, valid_concept_ids, feasibility,
        )
        all_eval_outcomes.append(outcome)
        if outcome == EvalOutcome.REJECT:
            logger.info("Item %r rejected by evaluation: %s", item.title, reason)

    return RoundResult(
        round_number=round_number,
        items=all_items,
        trajectories=all_trajectories,
        reflector_feedback=all_feedback,
        eval_outcomes=all_eval_outcomes,
    )
