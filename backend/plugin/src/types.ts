/* TypeScript interfaces mirroring backend Pydantic schemas (app/schemas/item.py). */

export type ItemType = "problem" | "definition" | "flashcard" | "code_challenge";
export type Difficulty = "easy" | "medium" | "hard" | "very_hard" | "expert";
export type FeasibilityOutcome = "ABANDON" | "GENERATE_WITH_REVIEW" | "GENERATE";
export type EvalOutcome = "ACCEPT" | "REJECT" | "FLAG_FOR_REVIEW";
export type SessionStatus = "in_progress" | "completed";
export type ScheduleMode = "all" | "top_down";

export interface InlineConcept {
	id: string;
	title: string;
	body_md?: string;
	content_type?: string;
	user_mastery?: number;
	connected_concepts?: string[];
	/** LLM-built dependency layer; 0 = no prerequisites within the paper.
	 * Read from each section MD's YAML frontmatter ``depth: N``. Concepts
	 * imported from non-graphed sources default to 0. */
	depth?: number;
}

export interface InlineEdge {
	id: string;
	source_title: string;
	target_title: string;
	relationship_type?: string;
	body_md?: string;
}

export interface GeneratedItem {
	type: ItemType;
	title: string;
	body_md: string;
	answer_md: string;
	foundation_concept_ids: string[];
	difficulty: Difficulty;
	explanation_md?: string;
	/** Pedagogical summary produced by the sample-item analyzer.
	 *  When set, the Generator receives it alongside the sample so it
	 *  can emulate the sample's intent, not just its surface form. */
	analysis_notes?: string;
}

export interface ContextImage {
	image_base64: string;
	media_type: string;
}

export interface InlineItemGenerateRequest {
	concepts: InlineConcept[];
	edges?: InlineEdge[];
	example_items?: GeneratedItem[];
	context_images?: ContextImage[];
	requested_type?: ItemType;
	difficulty_preference?: Difficulty;
	user_requirements?: string;
	items_per_round?: number;
	/** Depth-aware scheduling. Defaults to ``all`` (legacy behavior). */
	schedule_mode?: ScheduleMode;
	focus_depth?: number;
	advance_threshold?: number;
}

/** Mirrors ``app.schemas.item.SchedulerState`` — advisory only; the plugin
 * decides whether to honor ``next_focus_depth`` on the next request. */
export interface SchedulerState {
	schedule_mode: ScheduleMode;
	focus_depth_used: number;
	next_focus_depth: number;
	advance_triggered: boolean;
	visible_concept_count: number;
	filtered_concept_count: number;
	max_depth_seen: number;
}

export interface ActorTrajectory {
	item_title: string;
	solution_md: string;
	reasoning_steps: string[];
	concepts_used: string[];
	confidence: number;
}

export interface ReflectorFeedback {
	item_title: string;
	quality_score: number;
	issues: string[];
	suggestions: string[];
	approved: boolean;
}

export interface GraderSummary {
	round_number: number;
	mastery_delta: Record<string, number>;
	learning_summary: string;
	requirements_met: boolean;
	next_difficulty: Difficulty;
	recommendation: string;
}

export interface RoundResult {
	round_number: number;
	items: GeneratedItem[];
	trajectories: ActorTrajectory[];
	reflector_feedback: ReflectorFeedback[];
	grader_summary: GraderSummary | null;
	eval_outcomes: EvalOutcome[];
	scheduler_state?: SchedulerState | null;
}

export interface SessionResponse {
	session_id: string;
	rounds: RoundResult[];
	current_difficulty: Difficulty;
	status: SessionStatus;
	feasibility: FeasibilityOutcome;
}

export interface ContinueRoundRequest {
	concepts: InlineConcept[];
	edges?: InlineEdge[];
	example_items?: GeneratedItem[];
	context_images?: ContextImage[];
	user_scores?: number[];
	prior_round_count: number;
	current_difficulty: Difficulty;
	override_difficulty?: Difficulty | null;
	requested_type?: ItemType;
	user_requirements?: string;
	items_per_round?: number;
	/** Depth-aware scheduling — see ``InlineItemGenerateRequest``. */
	schedule_mode?: ScheduleMode;
	focus_depth?: number;
	advance_threshold?: number;
	/** Manual depth override; bypasses score-based auto-advance. */
	override_focus_depth?: number | null;
}

export interface SegmentedConcept {
	title: string;
	body_md: string;
	content_type: string;
}

export interface SegmentedEdge {
	source_title: string;
	target_title: string;
	relationship_type: string;
	note: string;
}

export interface PaperSegmentResult {
	concepts: SegmentedConcept[];
	edges: SegmentedEdge[];
	raw_md: string;
}

/** Mirrors app/schemas/vectors.py — Pinecone concept index rows. */
export interface ConceptIndexEntry {
	concept_id: string;
	text: string;
	vault_path?: string;
	title?: string;
}

export interface BatchIndexConceptsResponse {
	indexed: number;
	namespace: string;
}

export interface ConceptSearchHit {
	concept_id: string;
	score: number;
	metadata: Record<string, unknown>;
}

export interface ConceptSearchResponse {
	hits: ConceptSearchHit[];
	namespace: string;
}

export interface ClearNamespaceResponse {
	namespace: string;
	cleared: boolean;
}

/** A concept attached to a graded item. Passing ``id`` alongside
 * ``title`` is preferred — without it, per-concept verdicts come
 * back with synthetic ids and the plugin can't reattach mastery
 * updates to real concepts. */
export interface ConceptRef {
	id?: string;
	title: string;
}

export type ConceptVerdictStatus =
	| "correctly_applied"
	| "alternative_path"
	| "misapplied"
	| "not_demonstrated";

/** Grader's per-concept call on one graded answer. The plugin maps
 * each verdict to a signed mastery delta via ``applyVerdicts``; see
 * ``answer_grader.py`` for the status semantics. */
export interface ConceptVerdict {
	concept_id: string;
	status: ConceptVerdictStatus;
	confidence: number;
	note: string;
}

export interface AnswerGradeRequest {
	item_title: string;
	item_body_md: string;
	reference_answer_md: string;
	user_answer_md: string;
	foundation_concepts?: ConceptRef[] | string[];
}

export interface AnswerFeedback {
	score: number;
	correct: boolean;
	strengths: string[];
	mistakes: string[];
	suggestions: string;
	mastery_estimate: number;
	per_concept?: ConceptVerdict[];
}

/* ------------------------------------------------------------------ */
/* Sample-item analyzer — pedagogy check before using an item as a    */
/* few-shot reference. Mirrors app.schemas.item.SampleItemAnalysis.   */
/* ------------------------------------------------------------------ */

export interface SampleItemAnalyzeRequest {
	title: string;
	body_md: string;
	answer_md?: string;
	concept_catalog?: ConceptRef[];
	/** Inline images for multimodal analysis (figures, scans). */
	context_images?: ContextImage[];
}

export interface SampleItemAnalysis {
	summary: string;
	item_type_guess: ItemType;
	estimated_difficulty: Difficulty;
	concepts_covered: string[];
	concepts_missing_from_catalog: string[];
	pedagogical_notes: string;
	strengths: string[];
	issues: string[];
}

/* ------------------------------------------------------------------ */
/* Paper ingestion + document-chunk search                             */
/* Mirrors app/schemas/vectors.py (IngestPaper* + DocChunk*).         */
/* ------------------------------------------------------------------ */

export interface IngestPaperRequest {
	user_id: string;
	pdf_base64: string;
	filename: string;
	export_path?: string | null;
	force?: boolean;
}

export interface IngestPaperSectionSummary {
	section_id: string;
	order: number;
	title: string;
	filename: string;
	image_refs: string[];
	chunk_count: number;
}

export interface IngestPaperResponse {
	doc_id: string;
	stem: string;
	paper_dir: string;
	section_count: number;
	chunk_count: number;
	sections: IngestPaperSectionSummary[];
	pinecone_namespace?: string | null;
	pinecone_indexed: number;
	exported_to?: string | null;
	already_ingested?: boolean;
}

export interface DocChunkSearchHit {
	vector_id: string;
	doc_id?: string | null;
	section_id?: string | null;
	chunk_index?: number | null;
	score: number;
	metadata: Record<string, unknown>;
}

export interface DocChunkSearchResponse {
	hits: DocChunkSearchHit[];
	namespace: string;
}
