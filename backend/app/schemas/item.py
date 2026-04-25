"""Item schemas — generation request/response, loop state, Actor/Reflector/Grader DTOs."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ItemType(StrEnum):
    PROBLEM = "problem"
    DEFINITION = "definition"
    FLASHCARD = "flashcard"
    CODE_CHALLENGE = "code_challenge"


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    VERY_HARD = "very_hard"
    EXPERT = "expert"


class FeasibilityOutcome(StrEnum):
    ABANDON = "ABANDON"
    GENERATE_WITH_REVIEW = "GENERATE_WITH_REVIEW"
    GENERATE = "GENERATE"


class EvalOutcome(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    FLAG_FOR_REVIEW = "FLAG_FOR_REVIEW"


class SessionStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class ScheduleMode(StrEnum):
    """How the generator should pick concepts from the inline pool.

    - ``ALL``: legacy behavior — every concept in the request is visible to
      the LLM each round.
    - ``TOP_DOWN``: hard filter on ``InlineConcept.depth`` — only concepts
      with ``depth <= focus_depth`` reach the prompt; ``focus_depth``
      auto-advances when the user's avg score on the layer crosses the
      ``advance_threshold`` (mirrors the difficulty escalator).
    """
    ALL = "all"
    TOP_DOWN = "top_down"


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------

class ItemGenerateRequest(BaseModel):
    foundation_concept_ids: list[str]
    edge_ids: list[str] = Field(default_factory=list)
    example_item_ids: list[str] = Field(default_factory=list)
    requested_type: ItemType = ItemType.PROBLEM
    difficulty_preference: Difficulty = Difficulty.MEDIUM
    user_requirements: str = ""
    items_per_round: int = Field(default=3, ge=1, le=10)


# ---------------------------------------------------------------------------
# LLM-produced artefacts
# ---------------------------------------------------------------------------

class GeneratedItem(BaseModel):
    type: ItemType
    title: str
    body_md: str
    answer_md: str
    foundation_concept_ids: list[str]
    difficulty: Difficulty
    explanation_md: str = ""
    # Optional pedagogical notes from the sample-item analyzer. When the
    # user uploads a sample as a few-shot reference, the analyzer emits a
    # short summary (strengths, difficulty cues, concepts actually
    # exercised). We attach it to the item so the Generator gets the
    # analysis alongside the sample in the prompt, not just the raw text.
    analysis_notes: str = ""


class ActorTrajectory(BaseModel):
    item_title: str
    solution_md: str
    reasoning_steps: list[str] = Field(default_factory=list)
    concepts_used: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ReflectorFeedback(BaseModel):
    item_title: str
    quality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    approved: bool = False


class GraderSummary(BaseModel):
    round_number: int
    mastery_delta: dict[str, float] = Field(default_factory=dict)
    learning_summary: str = ""
    requirements_met: bool = False
    next_difficulty: Difficulty = Difficulty.MEDIUM
    recommendation: str = ""


# ---------------------------------------------------------------------------
# Round / Session aggregates
# ---------------------------------------------------------------------------

class SchedulerState(BaseModel):
    """Tells the plugin what the depth-aware scheduler actually did this
    round and whether to auto-advance the focus depth next round.

    All fields are advisory: the plugin owns the canonical ``focus_depth``
    across rounds and decides whether to honor ``next_focus_depth``.
    """
    schedule_mode: ScheduleMode = ScheduleMode.ALL
    focus_depth_used: int = 0
    next_focus_depth: int = 0
    advance_triggered: bool = False
    visible_concept_count: int = 0
    filtered_concept_count: int = 0
    max_depth_seen: int = 0


class RoundResult(BaseModel):
    round_number: int
    items: list[GeneratedItem] = Field(default_factory=list)
    trajectories: list[ActorTrajectory] = Field(default_factory=list)
    reflector_feedback: list[ReflectorFeedback] = Field(default_factory=list)
    grader_summary: GraderSummary | None = None
    eval_outcomes: list[EvalOutcome] = Field(default_factory=list)
    scheduler_state: SchedulerState | None = None


class SessionResponse(BaseModel):
    session_id: str
    rounds: list[RoundResult] = Field(default_factory=list)
    current_difficulty: Difficulty = Difficulty.EASY
    status: SessionStatus = SessionStatus.IN_PROGRESS
    feasibility: FeasibilityOutcome = FeasibilityOutcome.GENERATE


# ---------------------------------------------------------------------------
# Inline concept/edge payloads (used while concept CRUD is not yet live)
# ---------------------------------------------------------------------------

class InlineConcept(BaseModel):
    """Concept content passed directly in the generation request.

    ``depth`` is the LLM-built dependency layer (from ``graph_builder``),
    where 0 = "no prerequisites within this paper". The plugin reads this
    from each section's YAML frontmatter (``depth: N``) and echoes it back
    here so the depth-aware scheduler can filter concepts top-down.
    Concepts that don't come from a graphed paper default to depth=0.
    """
    id: str
    title: str
    body_md: str = ""
    content_type: str = "markdown"
    user_mastery: float = Field(default=0.5, ge=0.0, le=1.0)
    connected_concepts: list[str] = Field(default_factory=list)
    depth: int = Field(default=0, ge=0)


class InlineEdge(BaseModel):
    """Edge content passed directly in the generation request."""
    id: str
    source_title: str
    target_title: str
    relationship_type: str = ""
    body_md: str = ""


class ConceptRef(BaseModel):
    """A foundation concept associated with an item, carried through
    grading so the grader can emit per-concept verdicts that the
    plugin can reattach to the right concept id (for mastery updates).
    Keeping ``id`` optional lets older clients that only send titles
    keep working — the grader just won't be able to credit specific
    concepts in that case."""
    id: str | None = None
    title: str


class ConceptVerdictStatus(StrEnum):
    """Outcome of a concept within a single graded answer.

    The split solves two real problems with a single global score:
    - ``alternative_path`` — student solved the problem without using
      the listed concept (e.g. QDA with MLE instead of Bayes'). They
      still deserve credit and mastery shouldn't drop.
    - ``misapplied`` — student used the concept but got it wrong in a
      way that specifically signals misunderstanding. That should
      *reduce* mastery for that concept without dragging unrelated
      concepts down.
    """
    CORRECTLY_APPLIED = "correctly_applied"
    ALTERNATIVE_PATH = "alternative_path"
    MISAPPLIED = "misapplied"
    NOT_DEMONSTRATED = "not_demonstrated"


class ConceptVerdict(BaseModel):
    """Grader's per-concept call on one item. The plugin maps each
    verdict to a signed mastery delta (see ``applyVerdicts`` in
    ItemView). ``confidence`` scales the magnitude of that delta, so
    a "probably misapplied" verdict doesn't tank mastery the way a
    confident misapplication does."""
    concept_id: str
    status: ConceptVerdictStatus
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    note: str = ""


class AnswerGradeRequest(BaseModel):
    """Grade a user's answer against a generated item.

    ``foundation_concepts`` now accepts EITHER plain titles (legacy)
    OR ``ConceptRef`` objects carrying ``{id, title}``. Passing the id
    is strongly preferred — without it, ``per_concept`` verdicts in
    the response will have synthetic ids and the plugin won't be able
    to reattach mastery updates to real concepts."""
    item_title: str
    item_body_md: str
    reference_answer_md: str
    user_answer_md: str
    foundation_concepts: list[ConceptRef] | list[str] = Field(default_factory=list)


class AnswerFeedback(BaseModel):
    """Grading result for a single user answer."""
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    correct: bool = False
    strengths: list[str] = Field(default_factory=list)
    mistakes: list[str] = Field(default_factory=list)
    suggestions: str = ""
    mastery_estimate: float = Field(default=0.5, ge=0.0, le=1.0)
    per_concept: list[ConceptVerdict] = Field(default_factory=list)


class ContextImage(BaseModel):
    """An image attached as inline visual context for the LLM."""
    image_base64: str
    media_type: str = "image/png"


class InlineItemGenerateRequest(BaseModel):
    """Full request with inline concept/edge data (no DB fetch needed)."""
    concepts: list[InlineConcept]
    edges: list[InlineEdge] = Field(default_factory=list)
    example_items: list[GeneratedItem] = Field(default_factory=list)
    context_images: list[ContextImage] = Field(default_factory=list)
    requested_type: ItemType = ItemType.PROBLEM
    difficulty_preference: Difficulty = Difficulty.MEDIUM
    user_requirements: str = ""
    items_per_round: int = Field(default=3, ge=1, le=10)

    # Depth-aware scheduling (no-op when ``schedule_mode == ALL``).
    schedule_mode: ScheduleMode = ScheduleMode.ALL
    focus_depth: int = Field(
        default=0,
        ge=0,
        description=(
            "Cap concept depth visible to the LLM when schedule_mode=top_down. "
            "Auto-advances on next_round when avg score >= advance_threshold."
        ),
    )
    advance_threshold: float = Field(default=0.7, ge=0.0, le=1.0)


class ContinueRoundRequest(BaseModel):
    """Stateless next-round request — the note IS the session state."""
    concepts: list[InlineConcept]
    edges: list[InlineEdge] = Field(default_factory=list)
    example_items: list[GeneratedItem] = Field(default_factory=list)
    context_images: list[ContextImage] = Field(default_factory=list)
    user_scores: list[float] = Field(default_factory=list)
    prior_round_count: int = Field(default=0, ge=0)
    current_difficulty: Difficulty = Difficulty.MEDIUM
    override_difficulty: Difficulty | None = None
    requested_type: ItemType = ItemType.PROBLEM
    user_requirements: str = ""
    items_per_round: int = Field(default=3, ge=1, le=10)

    # Depth-aware scheduling. The plugin owns the focus_depth state across
    # rounds and decides whether to honor the auto-advance suggestion in
    # the response (see RoundResult.scheduler_state).
    schedule_mode: ScheduleMode = ScheduleMode.ALL
    focus_depth: int = Field(default=0, ge=0)
    advance_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    override_focus_depth: int | None = Field(default=None, ge=0)


# ---------------------------------------------------------------------------
# PDF extraction / paper segmentation
# ---------------------------------------------------------------------------

class SegmentedConcept(BaseModel):
    """A concept extracted from a paper by the segmenter."""
    title: str
    body_md: str = ""
    content_type: str = "markdown"


class SegmentedEdge(BaseModel):
    """A directed edge between concepts extracted from a paper."""
    source_title: str
    target_title: str
    relationship_type: str = "prerequisite"
    note: str = ""


class PaperSegmentResult(BaseModel):
    """Result of segmenting a paper into concepts and edges."""
    concepts: list[SegmentedConcept] = Field(default_factory=list)
    edges: list[SegmentedEdge] = Field(default_factory=list)
    raw_md: str = ""


# ---------------------------------------------------------------------------
# Sample-item pre-analysis (feeds pedagogical notes into the Generator)
# ---------------------------------------------------------------------------

class SampleItemAnalysis(BaseModel):
    """Structured feedback on a user-uploaded sample item.

    The analyzer runs once, before the sample is used as a few-shot
    reference, and reports what the sample actually exercises, how hard
    it is, what makes it pedagogically effective, and any quality
    issues. The Generator sees this alongside the sample so it can
    emulate the intent, not just the surface form.
    """
    summary: str = ""  # one-liner shown in the plugin UI
    item_type_guess: ItemType = ItemType.PROBLEM
    estimated_difficulty: Difficulty = Difficulty.MEDIUM
    # Titles (not ids) of catalog concepts the sample genuinely
    # exercises. The analyzer matches against the concept catalog
    # passed in the request and will not hallucinate new concepts.
    concepts_covered: list[str] = Field(default_factory=list)
    # Free-form concepts the sample exercises that aren't in the
    # session's catalog — useful to flag gaps in the concept set.
    concepts_missing_from_catalog: list[str] = Field(default_factory=list)
    pedagogical_notes: str = ""
    strengths: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class SampleItemAnalyzeRequest(BaseModel):
    """Ask the analyzer to grade-like evaluate a sample item.

    ``context_images`` lets callers attach scanned/rendered figures
    that are part of the problem statement (e.g. a photographed
    whiteboard). When present and the configured provider supports
    multimodal input, they're inlined into the analyzer prompt.
    """
    title: str
    body_md: str
    answer_md: str = ""
    concept_catalog: list[ConceptRef] = Field(default_factory=list)
    context_images: list[ContextImage] = Field(default_factory=list)
