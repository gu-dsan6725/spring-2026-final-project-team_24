import { requestUrl, RequestUrlParam } from "obsidian";
import type {
	AnswerFeedback,
	AnswerGradeRequest,
	BatchIndexConceptsResponse,
	ClearNamespaceResponse,
	ConceptIndexEntry,
	ConceptSearchResponse,
	ContinueRoundRequest,
	DocChunkSearchResponse,
	IngestPaperRequest,
	IngestPaperResponse,
	InlineItemGenerateRequest,
	PaperSegmentResult,
	RoundResult,
	SampleItemAnalysis,
	SampleItemAnalyzeRequest,
	SessionResponse,
} from "./types";

export class BackendAPI {
	private baseUrl: string;
	private authToken: string;

	constructor(baseUrl: string, authToken: string) {
		this.baseUrl = BackendAPI.normalizeBaseUrl(baseUrl);
		this.authToken = authToken;
	}

	updateConfig(baseUrl: string, authToken: string): void {
		this.baseUrl = BackendAPI.normalizeBaseUrl(baseUrl);
		this.authToken = authToken;
	}

	/** Trim trailing slashes; caller should trim whitespace before passing. */
	static normalizeBaseUrl(raw: string): string {
		return (raw || "").trim().replace(/\/+$/, "");
	}

	private assertBaseUrl(): void {
		const u = this.baseUrl;
		if (!u) {
			throw new Error(
				"Backend URL is empty. Open Settings → Community plugins → Knowledge Graph → Backend URL and set e.g. http://127.0.0.1:8000"
			);
		}
		if (!/^https?:\/\//i.test(u)) {
			throw new Error(
				`Backend URL must be an absolute URL starting with http:// or https:// (current: "${u.slice(0, 80)}")`
			);
		}
	}

	private buildHeaders(): Record<string, string> {
		const headers: Record<string, string> = {
			"Content-Type": "application/json",
		};
		if (this.authToken) {
			headers["Authorization"] = `Bearer ${this.authToken}`;
		}
		return headers;
	}

	private async request<T>(params: RequestUrlParam): Promise<T> {
		this.assertBaseUrl();
		const resp = await requestUrl(params);
		if (resp.status >= 400) {
			const detail = resp.json?.detail || resp.text || `HTTP ${resp.status}`;
			throw new Error(`Backend error (${resp.status}): ${detail}`);
		}
		return resp.json as T;
	}

	async generateItems(req: InlineItemGenerateRequest): Promise<SessionResponse> {
		return this.request<SessionResponse>({
			url: `${this.baseUrl}/api/v1/items/generate`,
			method: "POST",
			headers: this.buildHeaders(),
			body: JSON.stringify(req),
		});
	}

	async nextRound(sessionId: string, userScores?: number[]): Promise<SessionResponse> {
		return this.request<SessionResponse>({
			url: `${this.baseUrl}/api/v1/items/sessions/${sessionId}/next-round`,
			method: "POST",
			headers: this.buildHeaders(),
			body: JSON.stringify({ user_scores: userScores ?? [] }),
		});
	}

	async finishSession(sessionId: string): Promise<SessionResponse> {
		return this.request<SessionResponse>({
			url: `${this.baseUrl}/api/v1/items/sessions/${sessionId}/finish`,
			method: "POST",
			headers: this.buildHeaders(),
		});
	}

	async getSession(sessionId: string): Promise<SessionResponse> {
		return this.request<SessionResponse>({
			url: `${this.baseUrl}/api/v1/items/sessions/${sessionId}`,
			method: "GET",
			headers: this.buildHeaders(),
		});
	}

	async continueRound(req: ContinueRoundRequest): Promise<RoundResult> {
		return this.request<RoundResult>({
			url: `${this.baseUrl}/api/v1/items/continue-round`,
			method: "POST",
			headers: this.buildHeaders(),
			body: JSON.stringify(req),
		});
	}

	async gradeAnswer(req: AnswerGradeRequest): Promise<AnswerFeedback> {
		return this.request<AnswerFeedback>({
			url: `${this.baseUrl}/api/v1/items/grade-answer`,
			method: "POST",
			headers: this.buildHeaders(),
			body: JSON.stringify(req),
		});
	}

	/** Pre-analyze a sample item (pedagogy check, not student grading).
	 *  Returns a SampleItemAnalysis the caller should attach to the
	 *  sample via ``analysis_notes`` before sending to the Generator. */
	async analyzeSample(req: SampleItemAnalyzeRequest): Promise<SampleItemAnalysis> {
		return this.request<SampleItemAnalysis>({
			url: `${this.baseUrl}/api/v1/items/analyze-sample`,
			method: "POST",
			headers: this.buildHeaders(),
			body: JSON.stringify(req),
		});
	}

	async uploadPaper(pdfBase64: string, filename: string, hint?: string): Promise<PaperSegmentResult> {
		return this.request<PaperSegmentResult>({
			url: `${this.baseUrl}/api/v1/extract/upload`,
			method: "POST",
			headers: this.buildHeaders(),
			body: JSON.stringify({ pdf_base64: pdfBase64, filename, hint: hint || "" }),
		});
	}

	async indexConcepts(userId: string, entries: ConceptIndexEntry[]): Promise<BatchIndexConceptsResponse> {
		return this.request<BatchIndexConceptsResponse>({
			url: `${this.baseUrl}/api/v1/vectors/concepts/index`,
			method: "POST",
			headers: this.buildHeaders(),
			body: JSON.stringify({ user_id: userId, entries }),
		});
	}

	async searchConcepts(userId: string, query: string, topK = 10): Promise<ConceptSearchResponse> {
		return this.request<ConceptSearchResponse>({
			url: `${this.baseUrl}/api/v1/vectors/concepts/search`,
			method: "POST",
			headers: this.buildHeaders(),
			body: JSON.stringify({ user_id: userId, query, top_k: topK }),
		});
	}

	async clearConceptNamespace(userId: string): Promise<ClearNamespaceResponse> {
		return this.request<ClearNamespaceResponse>({
			url: `${this.baseUrl}/api/v1/vectors/concepts/clear`,
			method: "POST",
			headers: this.buildHeaders(),
			body: JSON.stringify({ user_id: userId }),
		});
	}

	/**
	 * Run the full paper ingestion pipeline: MinerU extract → section split →
	 * sub-chunk → embed → persist locally → Pinecone upsert → optional export.
	 * Note: may take 30–120s for a typical paper; caller should show progress UI.
	 */
	async ingestPaper(req: IngestPaperRequest): Promise<IngestPaperResponse> {
		return this.request<IngestPaperResponse>({
			url: `${this.baseUrl}/api/v1/extract/ingest-paper`,
			method: "POST",
			headers: this.buildHeaders(),
			body: JSON.stringify(req),
		});
	}

	async searchDocChunks(userId: string, query: string, topK = 10): Promise<DocChunkSearchResponse> {
		return this.request<DocChunkSearchResponse>({
			url: `${this.baseUrl}/api/v1/vectors/docs/search`,
			method: "POST",
			headers: this.buildHeaders(),
			body: JSON.stringify({ user_id: userId, query, top_k: topK }),
		});
	}

	async clearDocNamespace(userId: string): Promise<ClearNamespaceResponse> {
		return this.request<ClearNamespaceResponse>({
			url: `${this.baseUrl}/api/v1/vectors/docs/clear`,
			method: "POST",
			headers: this.buildHeaders(),
			body: JSON.stringify({ user_id: userId }),
		});
	}
}
