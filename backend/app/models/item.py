"""Item — hyperedge spanning multiple foundation concepts.

Types: problem/exercise, definition, proof/derivation, code challenge, flashcard.

MongoDB document shape
----------------------
{
    "_id":                    ObjectId,
    "type":                   "problem" | "definition" | "flashcard" | "code_challenge",
    "title":                  str,
    "body_md":                str,        # question / prompt in markdown
    "answer_md":              str,        # solution in markdown
    "explanation_md":         str,        # step-by-step explanation (optional)
    "foundation_concept_ids": [str],      # concept IDs this item tests
    "difficulty":             "easy" | "medium" | "hard",
    "created_by":             str,        # user ID
    "created_at":             datetime,
    "needs_review":           bool,
    "origin":                 "generated" | "manual",
    "session_id":             str | null, # generation session that created it
    "round_number":           int | null,
}

Session document (tracks multi-round generation loop)
-----------------------------------------------------
{
    "_id":                    ObjectId,
    "user_id":                str,
    "foundation_concept_ids": [str],
    "user_requirements":      str,
    "rounds":                 [RoundResult],   # see app.schemas.item
    "status":                 "in_progress" | "completed",
    "current_difficulty":     "easy" | "medium" | "hard",
    "feasibility":            "ABANDON" | "GENERATE_WITH_REVIEW" | "GENERATE",
    "created_at":             datetime,
}

Score/schedule metadata lives in PostgreSQL (see app.models.knowledge_state).
"""
