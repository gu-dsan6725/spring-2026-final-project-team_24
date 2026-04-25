"""Tests for the item generation pipeline.

Covers: view builders, message assembly, Actor trajectories, Reflector
feedback, Grader summaries, item evaluation, feasibility check, loop
orchestration, and end-to-end session flow.

All LLM calls are mocked — no real API keys needed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.ai.pipelines.item_construction import (
    build_concept_view,
    build_edge_view,
    build_example_item_view,
    build_messages,
    build_prior_round_view,
)
from app.ai.pipelines.item_evaluation import (
    coverage_check,
    evaluate,
    structural_check,
)
from app.ai.pipelines.actor import build_actor_messages, build_user_concept_view
from app.schemas.item import (
    ActorTrajectory,
    Difficulty,
    EvalOutcome,
    FeasibilityOutcome,
    GeneratedItem,
    GraderSummary,
    InlineConcept,
    InlineEdge,
    InlineItemGenerateRequest,
    ItemType,
    ReflectorFeedback,
    RoundResult,
    SessionStatus,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def sample_concept_doc():
    return {
        "_id": "c_001",
        "title": "Bayes Theorem",
        "body_md": "P(A|B) = P(B|A)P(A) / P(B)",
        "content_type": "markdown",
        "embedding": [0.1, 0.2, 0.3],
        "created_at": "2026-01-01",
        "owner_id": "user_42",
    }


@pytest.fixture()
def sample_edge_doc():
    return {
        "_id": "e_001",
        "source_title": "Bayes Theorem",
        "target_title": "Conditional Probability",
        "relationship_type": "prerequisite",
        "body_md": "Bayes Theorem requires understanding conditional probability.",
    }


@pytest.fixture()
def sample_generated_item():
    return GeneratedItem(
        type=ItemType.PROBLEM,
        title="Apply Bayes Theorem",
        body_md="Given P(A)=0.3, P(B|A)=0.8, P(B)=0.5, find P(A|B).",
        answer_md="P(A|B) = 0.8 * 0.3 / 0.5 = 0.48",
        foundation_concept_ids=["c_001", "c_002"],
        difficulty=Difficulty.MEDIUM,
        explanation_md="Apply the formula directly.",
    )


@pytest.fixture()
def sample_inline_request():
    return InlineItemGenerateRequest(
        concepts=[
            InlineConcept(
                id="c_001",
                title="Bayes Theorem",
                body_md="P(A|B) = P(B|A)P(A) / P(B)",
                user_mastery=0.4,
            ),
            InlineConcept(
                id="c_002",
                title="Conditional Probability",
                body_md="P(A|B) = P(A and B) / P(B)",
                user_mastery=0.7,
            ),
        ],
        edges=[
            InlineEdge(
                id="e_001",
                source_title="Bayes Theorem",
                target_title="Conditional Probability",
                relationship_type="prerequisite",
            ),
        ],
        requested_type=ItemType.PROBLEM,
        difficulty_preference=Difficulty.MEDIUM,
        user_requirements="Focus on real-world applications of Bayes theorem",
        items_per_round=2,
    )


# ---------------------------------------------------------------------------
# View builder tests
# ---------------------------------------------------------------------------

class TestBuildConceptView:
    def test_strips_embeddings_and_internal_fields(self, sample_concept_doc):
        view = build_concept_view(sample_concept_doc, mastery=0.5)
        assert "embedding" not in view
        assert "_id" not in view
        assert "created_at" not in view
        assert "owner_id" not in view

    def test_includes_title_and_content(self, sample_concept_doc):
        view = build_concept_view(sample_concept_doc)
        assert view["title"] == "Bayes Theorem"
        assert "P(A|B)" in view["content"]
        assert view["content_type"] == "markdown"

    def test_includes_mastery_score(self, sample_concept_doc):
        view = build_concept_view(sample_concept_doc, mastery=0.25)
        assert view["user_mastery"] == 0.25
        assert "Low understanding" in view["mastery_note"]

    def test_mastery_note_partial(self, sample_concept_doc):
        view = build_concept_view(sample_concept_doc, mastery=0.55)
        assert "Partial understanding" in view["mastery_note"]

    def test_mastery_note_strong(self, sample_concept_doc):
        view = build_concept_view(sample_concept_doc, mastery=0.85)
        assert "Strong understanding" in view["mastery_note"]

    def test_no_mastery_when_none(self, sample_concept_doc):
        view = build_concept_view(sample_concept_doc)
        assert "user_mastery" not in view
        assert "mastery_note" not in view

    def test_connected_concepts(self, sample_concept_doc):
        view = build_concept_view(
            sample_concept_doc,
            connected_titles=["Conditional Probability", "Prior Distribution"],
        )
        assert view["connected_concepts"] == ["Conditional Probability", "Prior Distribution"]


class TestBuildEdgeView:
    def test_curates_edge(self, sample_edge_doc):
        view = build_edge_view(sample_edge_doc)
        assert view["source"] == "Bayes Theorem"
        assert view["target"] == "Conditional Probability"
        assert view["relationship_type"] == "prerequisite"
        assert "_id" not in view


class TestBuildExampleItemView:
    def test_curates_item(self):
        doc = {
            "type": "problem",
            "title": "Old Problem",
            "body_md": "What is 2+2?",
            "answer_md": "4",
            "difficulty": "easy",
            "foundation_concept_titles": ["Arithmetic"],
            "embedding": [0.9, 0.1],
        }
        view = build_example_item_view(doc)
        assert view["title"] == "Old Problem"
        assert "embedding" not in view


class TestBuildPriorRoundView:
    def test_curates_round(self):
        round_data = {
            "round_number": 1,
            "items": [
                {"title": "Item A", "type": "problem", "difficulty": "easy", "body_md": "Q1"},
            ],
            "grader_summary": {"learning_summary": "Good progress"},
        }
        view = build_prior_round_view(round_data)
        assert view["round_number"] == 1
        assert len(view["items_produced"]) == 1
        assert view["grader_summary"]["learning_summary"] == "Good progress"


# ---------------------------------------------------------------------------
# Message assembly tests
# ---------------------------------------------------------------------------

class TestBuildMessages:
    def test_structure_has_system_and_user(self):
        msgs = build_messages([], [], [], {"type": "problem"})
        assert msgs[0]["role"] == "system"
        assert msgs[-1]["role"] == "user"

    def test_concepts_injected_as_tool_calls(self, sample_concept_doc):
        concept_view = build_concept_view(sample_concept_doc, mastery=0.5)
        msgs = build_messages([concept_view], [], [], {"type": "problem"})
        tool_msgs = [m for m in msgs if m["role"] == "tool"]
        assert len(tool_msgs) == 1
        assert "Bayes Theorem" in tool_msgs[0]["content"]

    def test_history_injected(self):
        history = [{
            "round_number": 1,
            "items": [{"title": "Prior Item", "type": "problem", "difficulty": "easy", "body_md": "Q"}],
            "reflector_feedback": [{"item_title": "Prior Item", "quality_score": 0.8, "issues": [], "suggestions": [], "approved": True}],
        }]
        msgs = build_messages([], [], [], {"type": "problem"}, history=history)
        tool_msgs = [m for m in msgs if m["role"] == "tool"]
        assert len(tool_msgs) >= 2  # prior round + reflector feedback

    def test_user_requirements_in_system_prompt(self):
        msgs = build_messages(
            [], [], [], {"type": "problem"},
            user_requirements="Focus on proofs",
        )
        assert "Focus on proofs" in msgs[0]["content"]

    def test_n_items_in_system_prompt(self):
        msgs = build_messages(
            [], [], [], {"type": "problem"},
            n_items=5,
        )
        assert "5" in msgs[0]["content"]


# ---------------------------------------------------------------------------
# Actor tests
# ---------------------------------------------------------------------------

class TestActorMessages:
    def test_user_concept_view_has_mastery(self):
        doc = {"title": "Calculus", "body_md": "Limits and derivatives", "user_mastery": 0.2}
        view = build_user_concept_view(doc)
        assert view["user_mastery"] == 0.2
        assert "barely understand" in view["mastery_note"]

    def test_actor_messages_structure(self, sample_generated_item):
        concepts = [
            {"id": "c_001", "title": "Bayes Theorem", "body_md": "...", "user_mastery": 0.4},
        ]
        msgs = build_actor_messages(sample_generated_item, concepts)
        assert msgs[0]["role"] == "system"
        assert "simulating" in msgs[0]["content"].lower()
        tool_msgs = [m for m in msgs if m["role"] == "tool"]
        assert len(tool_msgs) == 1
        assert msgs[-1]["role"] == "user"


# ---------------------------------------------------------------------------
# Item evaluation tests
# ---------------------------------------------------------------------------

class TestItemEvaluation:
    def test_structural_pass(self, sample_generated_item):
        ok, reason = structural_check(sample_generated_item)
        assert ok
        assert reason == ""

    def test_structural_fail_empty_title(self):
        item = GeneratedItem(
            type=ItemType.PROBLEM,
            title="",
            body_md="question",
            answer_md="answer",
            foundation_concept_ids=["c1"],
            difficulty=Difficulty.EASY,
        )
        ok, reason = structural_check(item)
        assert not ok
        assert "title" in reason.lower()

    def test_structural_fail_empty_body(self):
        item = GeneratedItem(
            type=ItemType.PROBLEM,
            title="Title",
            body_md="",
            answer_md="answer",
            foundation_concept_ids=["c1"],
            difficulty=Difficulty.EASY,
        )
        ok, reason = structural_check(item)
        assert not ok
        assert "body" in reason.lower()

    def test_structural_fail_empty_answer(self):
        item = GeneratedItem(
            type=ItemType.PROBLEM,
            title="Title",
            body_md="question",
            answer_md="  ",
            foundation_concept_ids=["c1"],
            difficulty=Difficulty.EASY,
        )
        ok, reason = structural_check(item)
        assert not ok
        assert "answer" in reason.lower()

    def test_structural_fail_no_concepts(self):
        item = GeneratedItem(
            type=ItemType.PROBLEM,
            title="Title",
            body_md="question",
            answer_md="answer",
            foundation_concept_ids=[],
            difficulty=Difficulty.EASY,
        )
        ok, reason = structural_check(item)
        assert not ok
        assert "concept" in reason.lower()

    def test_coverage_pass(self, sample_generated_item):
        ok, reason = coverage_check(sample_generated_item, {"c_001", "c_002", "c_003"})
        assert ok

    def test_coverage_fail_unknown_id(self, sample_generated_item):
        ok, reason = coverage_check(sample_generated_item, {"c_001"})
        assert not ok
        assert "c_002" in reason

    def test_evaluate_accept(self, sample_generated_item):
        outcome, reason = evaluate(sample_generated_item, {"c_001", "c_002"})
        assert outcome == EvalOutcome.ACCEPT

    def test_evaluate_reject_structural(self):
        item = GeneratedItem(
            type=ItemType.PROBLEM,
            title="",
            body_md="q",
            answer_md="a",
            foundation_concept_ids=["c1"],
            difficulty=Difficulty.EASY,
        )
        outcome, reason = evaluate(item, {"c1"})
        assert outcome == EvalOutcome.REJECT

    def test_evaluate_flag_for_review(self, sample_generated_item):
        outcome, reason = evaluate(
            sample_generated_item,
            {"c_001", "c_002"},
            feasibility=FeasibilityOutcome.GENERATE_WITH_REVIEW,
        )
        assert outcome == EvalOutcome.FLAG_FOR_REVIEW


# ---------------------------------------------------------------------------
# Feasibility check tests (mocked LLM)
# ---------------------------------------------------------------------------

class TestFeasibilityCheck:
    @pytest.mark.asyncio
    async def test_abandon(self):
        with patch("app.ai.providers.chat_json_completion", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = '{"outcome": "ABANDON", "reason": "IMO-level proof"}'
            from app.ai.pipelines.feasibility_check import check

            outcome, reason = await check(
                [{"title": "Number Theory", "content_type": "markdown"}],
                "problem",
            )
            assert outcome == FeasibilityOutcome.ABANDON
            assert "IMO" in reason

    @pytest.mark.asyncio
    async def test_generate(self):
        with patch("app.ai.providers.chat_json_completion", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = '{"outcome": "GENERATE", "reason": "recall domain"}'
            from app.ai.pipelines.feasibility_check import check

            outcome, reason = await check(
                [{"title": "History", "content_type": "markdown"}],
                "flashcard",
            )
            assert outcome == FeasibilityOutcome.GENERATE

    @pytest.mark.asyncio
    async def test_generate_with_review(self):
        with patch("app.ai.providers.chat_json_completion", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = '{"outcome": "GENERATE_WITH_REVIEW", "reason": "undergrad math"}'
            from app.ai.pipelines.feasibility_check import check

            outcome, reason = await check(
                [{"title": "Linear Algebra", "content_type": "markdown"}],
                "problem",
            )
            assert outcome == FeasibilityOutcome.GENERATE_WITH_REVIEW

    @pytest.mark.asyncio
    async def test_unparseable_defaults(self):
        with patch("app.ai.providers.chat_json_completion", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "not json"
            from app.ai.pipelines.feasibility_check import check

            outcome, _ = await check(
                [{"title": "Topic", "content_type": "markdown"}],
                "problem",
            )
            assert outcome == FeasibilityOutcome.GENERATE_WITH_REVIEW


# ---------------------------------------------------------------------------
# Reflector tests (mocked LLM)
# ---------------------------------------------------------------------------

class TestReflector:
    @pytest.mark.asyncio
    async def test_evaluate_items(self, sample_generated_item):
        trajectory = ActorTrajectory(
            item_title=sample_generated_item.title,
            solution_md="P(A|B) = 0.48",
            reasoning_steps=["Applied formula"],
            concepts_used=["Bayes Theorem"],
            confidence=0.9,
        )
        mock_response = (
            '{"evaluations": [{"item_title": "Apply Bayes Theorem", '
            '"quality_score": 0.85, "issues": [], "suggestions": [], "approved": true}]}'
        )
        with patch("app.ai.providers.chat_json_completion", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_response
            from app.ai.pipelines.reflector import evaluate

            feedback = await evaluate(
                [sample_generated_item],
                [trajectory],
                [{"title": "Bayes Theorem", "body_md": "P(A|B) = P(B|A)P(A)/P(B)"}],
            )
            assert len(feedback) == 1
            assert feedback[0].approved is True
            assert feedback[0].quality_score == 0.85


# ---------------------------------------------------------------------------
# Grader tests (mocked LLM)
# ---------------------------------------------------------------------------

class TestGrader:
    @pytest.mark.asyncio
    async def test_grade_rounds(self, sample_generated_item):
        round_result = RoundResult(
            round_number=1,
            items=[sample_generated_item],
            trajectories=[ActorTrajectory(
                item_title=sample_generated_item.title,
                solution_md="0.48",
                confidence=0.9,
            )],
            reflector_feedback=[ReflectorFeedback(
                item_title=sample_generated_item.title,
                quality_score=0.8,
                approved=True,
            )],
        )
        mock_response = (
            '{"mastery_delta": {"Bayes Theorem": 0.15}, '
            '"learning_summary": "Good progress on Bayes.", '
            '"requirements_met": false, '
            '"next_difficulty": "hard", '
            '"recommendation": "Continue with harder problems."}'
        )
        with patch("app.ai.providers.chat_json_completion", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_response
            from app.ai.pipelines.grader import grade

            summary = await grade(
                [round_result],
                [{"title": "Bayes Theorem", "user_mastery": 0.4}],
                user_requirements="Master Bayes applications",
            )
            assert summary.mastery_delta.get("Bayes Theorem") == 0.15
            assert summary.next_difficulty == Difficulty.HARD
            assert summary.requirements_met is False


# ---------------------------------------------------------------------------
# Generator tests (mocked LLM)
# ---------------------------------------------------------------------------

class TestGenerator:
    @pytest.mark.asyncio
    async def test_generate_items(self):
        mock_result = {
            "name": "generate_item",
            "arguments": {
                "type": "problem",
                "title": "Test Item",
                "body_md": "What is P(A|B)?",
                "answer_md": "0.48",
                "foundation_concept_ids": ["c_001"],
                "difficulty": "medium",
                "explanation_md": "Apply Bayes.",
            },
        }
        with patch("app.ai.providers.chat_tool_completion", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_result
            from app.ai.pipelines.item_construction import generate

            items = await generate(
                [{"title": "Bayes Theorem", "content": "..."}],
                [],
                [],
                {"requested_type": "problem", "difficulty_preference": "medium"},
                n_items=2,
                provider="groq",
            )
            assert len(items) == 2
            assert items[0].title == "Test Item"
            assert items[0].type == ItemType.PROBLEM


# ---------------------------------------------------------------------------
# Actor tests (mocked LLM)
# ---------------------------------------------------------------------------

class TestActorSolve:
    @pytest.mark.asyncio
    async def test_solve_item(self, sample_generated_item):
        mock_result = {
            "name": "solve_item",
            "arguments": {
                "solution_md": "P(A|B) = 0.48",
                "reasoning_steps": ["Identified values", "Applied formula"],
                "concepts_used": ["Bayes Theorem"],
                "confidence": 0.85,
            },
        }
        with patch("app.ai.providers.chat_tool_completion", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_result
            from app.ai.pipelines.actor import solve

            trajectory = await solve(
                sample_generated_item,
                [{"id": "c_001", "title": "Bayes Theorem", "body_md": "...", "user_mastery": 0.4}],
                provider="groq",
            )
            assert trajectory.item_title == "Apply Bayes Theorem"
            assert trajectory.confidence == 0.85
            assert "Bayes Theorem" in trajectory.concepts_used


# ---------------------------------------------------------------------------
# Loop orchestration tests (mocked LLM)
# ---------------------------------------------------------------------------

class TestItemLoop:
    @pytest.mark.asyncio
    async def test_refine_round(self):
        gen_result = {
            "name": "generate_item",
            "arguments": {
                "type": "problem",
                "title": "Loop Item",
                "body_md": "Question",
                "answer_md": "Answer",
                "foundation_concept_ids": ["c_001"],
                "difficulty": "medium",
            },
        }
        solve_result = {
            "name": "solve_item",
            "arguments": {
                "solution_md": "My answer",
                "reasoning_steps": ["Step 1"],
                "concepts_used": ["Bayes"],
                "confidence": 0.7,
            },
        }
        reflector_response = (
            '{"evaluations": [{"item_title": "Loop Item", '
            '"quality_score": 0.9, "issues": [], "suggestions": [], "approved": true}]}'
        )

        with (
            patch("app.ai.providers.chat_tool_completion", new_callable=AsyncMock) as mock_tool,
            patch("app.ai.providers.chat_json_completion", new_callable=AsyncMock) as mock_json,
        ):
            mock_tool.side_effect = [gen_result, solve_result]
            mock_json.return_value = reflector_response

            from app.ai.pipelines.item_loop import refine_round

            result = await refine_round(
                concept_views=[{"title": "Bayes Theorem", "content": "..."}],
                edge_views=[],
                example_item_views=[],
                request={"requested_type": "problem", "difficulty_preference": "medium"},
                user_concepts=[{"id": "c_001", "title": "Bayes Theorem", "body_md": "...", "user_mastery": 0.4}],
                valid_concept_ids={"c_001"},
                n_items=1,
                provider="groq",
            )
            assert result.round_number == 1
            assert len(result.items) == 1
            assert result.items[0].title == "Loop Item"
            assert len(result.trajectories) == 1
            assert result.reflector_feedback[0].approved is True


# ---------------------------------------------------------------------------
# End-to-end session tests (mocked LLM)
# ---------------------------------------------------------------------------

class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_start_session_abandon(self, sample_inline_request):
        with patch("app.ai.providers.chat_json_completion", new_callable=AsyncMock) as mock_json:
            mock_json.return_value = '{"outcome": "ABANDON", "reason": "too complex"}'

            from app.services.item_service import start_session

            resp = await start_session(sample_inline_request)
            assert resp.feasibility == FeasibilityOutcome.ABANDON
            assert resp.status == SessionStatus.COMPLETED
            assert len(resp.rounds) == 0

    @pytest.mark.asyncio
    async def test_start_session_generates(self, sample_inline_request):
        gen_result = {
            "name": "generate_item",
            "arguments": {
                "type": "problem",
                "title": "E2E Item",
                "body_md": "Q?",
                "answer_md": "A",
                "foundation_concept_ids": ["c_001"],
                "difficulty": "medium",
            },
        }
        solve_result = {
            "name": "solve_item",
            "arguments": {
                "solution_md": "sol",
                "reasoning_steps": ["s1"],
                "concepts_used": ["Bayes Theorem"],
                "confidence": 0.8,
            },
        }
        reflector_resp = (
            '{"evaluations": [{"item_title": "E2E Item", '
            '"quality_score": 0.9, "issues": [], "suggestions": [], "approved": true}]}'
        )

        feasibility_resp = '{"outcome": "GENERATE", "reason": "recall domain"}'

        with (
            patch("app.ai.providers.chat_tool_completion", new_callable=AsyncMock) as mock_tool,
            patch("app.ai.providers.chat_json_completion", new_callable=AsyncMock) as mock_json,
        ):
            mock_tool.side_effect = [gen_result, solve_result] * 4
            mock_json.side_effect = [feasibility_resp, reflector_resp]

            from app.services.item_service import start_session

            resp = await start_session(sample_inline_request)
            assert resp.feasibility == FeasibilityOutcome.GENERATE
            assert resp.status == SessionStatus.IN_PROGRESS
            assert len(resp.rounds) == 1
            assert len(resp.rounds[0].items) >= 1
