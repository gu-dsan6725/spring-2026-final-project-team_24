"""Items — hyperedge study materials (problems, flashcards, definitions, code challenges).

Endpoints:
  POST /generate          — start a generation session, returns first round
  POST /sessions/{id}/next-round — grade + produce next difficulty round
  GET  /sessions/{id}     — get session state
  POST /grade-answer      — grade a user's free-text answer
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.schemas.item import (
    AnswerFeedback,
    AnswerGradeRequest,
    ContinueRoundRequest,
    InlineItemGenerateRequest,
    RoundResult,
    SampleItemAnalysis,
    SampleItemAnalyzeRequest,
    SessionResponse,
)
from app.services import item_service

router = APIRouter()


@router.post("/generate", response_model=SessionResponse)
async def generate_items(req: InlineItemGenerateRequest) -> SessionResponse:
    """Start a new item generation session.

    Accepts inline concept/edge data (no DB fetch needed for POC).
    Returns the first round of generated items with Actor trajectories
    and Reflector evaluations.
    """
    try:
        return await item_service.start_session(req)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


class NextRoundRequest(BaseModel):
    user_scores: list[float] = Field(default_factory=list)


@router.post("/sessions/{session_id}/next-round", response_model=SessionResponse)
async def session_next_round(session_id: str, body: NextRoundRequest | None = None) -> SessionResponse:
    """Generate the next round.  Pass user_scores (0-1) to drive difficulty."""
    scores = body.user_scores if body and body.user_scores else None
    try:
        return await item_service.next_round(session_id, user_scores=scores)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/finish", response_model=SessionResponse)
async def finish_session(session_id: str) -> SessionResponse:
    """Mark session as completed (user-initiated)."""
    return item_service.finish_session(session_id)


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str) -> SessionResponse:
    """Get the current session state with all rounds."""
    return item_service.get_session(session_id)


@router.post("/continue-round", response_model=RoundResult)
async def continue_round(req: ContinueRoundRequest) -> RoundResult:
    """Stateless next-round — the note IS the session. No backend session needed."""
    try:
        return await item_service.continue_round(req)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/grade-answer", response_model=AnswerFeedback)
async def grade_answer(req: AnswerGradeRequest) -> AnswerFeedback:
    """Grade a user's free-text answer against a reference solution."""
    from app.ai.pipelines.answer_grader import grade_answer as _grade

    # Normalize foundation_concepts to [{id, title}] for the grader.
    # Pydantic already split strings vs ConceptRef via Union; iterate
    # once and coerce into plain dicts so the grader's helpers don't
    # need to know about the schema classes.
    foundation: list[dict] | list[str]
    if req.foundation_concepts and isinstance(req.foundation_concepts[0], str):
        foundation = list(req.foundation_concepts)  # type: ignore[arg-type]
    else:
        foundation = [
            {"id": c.id, "title": c.title}
            for c in req.foundation_concepts  # type: ignore[union-attr]
        ]

    try:
        result = await _grade(
            item_title=req.item_title,
            item_body_md=req.item_body_md,
            reference_answer_md=req.reference_answer_md,
            user_answer_md=req.user_answer_md,
            foundation_concepts=foundation,
        )
        return AnswerFeedback(**result)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/analyze-sample", response_model=SampleItemAnalysis)
async def analyze_sample(req: SampleItemAnalyzeRequest) -> SampleItemAnalysis:
    """Pre-analyze a user-uploaded sample item.

    Runs a pedagogy-focused LLM pass that grades the *sample itself*
    (not a student answer) so the Generator can later consume a
    summary of what the sample exercises and why it's a good study
    item. Accepts optional ``context_images`` for multimodal items
    (figures, scanned problems). The analysis is forwarded back to
    the plugin and attached to the sample before it's shipped to the
    Generator via ``example_items``.
    """
    from app.ai.pipelines.sample_analyzer import analyze_sample_item

    catalog = [{"id": c.id, "title": c.title} for c in req.concept_catalog]
    images = [
        {"image_base64": img.image_base64, "media_type": img.media_type}
        for img in req.context_images
    ]

    try:
        result = await analyze_sample_item(
            title=req.title,
            body_md=req.body_md,
            answer_md=req.answer_md,
            concept_catalog=catalog,
            context_images=images,
        )
        return SampleItemAnalysis(**result)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
