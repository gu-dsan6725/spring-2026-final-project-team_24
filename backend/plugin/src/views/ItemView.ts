import {
	ItemView,
	WorkspaceLeaf,
	Notice,
	TFile,
	TFolder,
	FuzzySuggestModal,
	Menu,
	normalizePath,
} from "obsidian";
import type KnowledgeGraphPlugin from "../main";
import { ingestPdfFile, vaultBasePath } from "../commands/paper_ingest";
import type { PickedPdf } from "../commands/paper_ingest";
import type {
	InlineConcept,
	InlineItemGenerateRequest,
	ContinueRoundRequest,
	ContextImage,
	SessionResponse,
	GeneratedItem,
	AnswerGradeRequest,
	AnswerFeedback,
	ConceptRef,
	ConceptVerdict,
	RoundResult,
	Difficulty,
	ItemType,
	SampleItemAnalysis,
	ScheduleMode,
	SchedulerState,
} from "../types";

/**
 * Launch the native OS file picker for ``.md`` + ``.pdf`` uploads and
 * resolve with the selected ``File`` objects (or ``null`` on cancel).
 * Uses a transient hidden ``<input>`` to get Electron's native dialog
 * — same pattern used for the PDF-only picker in ``paper_ingest.ts``.
 */
function pickFilesFromOS(): Promise<File[] | null> {
	return new Promise((resolve) => {
		const input = document.createElement("input");
		input.type = "file";
		input.accept = ".md,.pdf,application/pdf,text/markdown";
		input.multiple = true;
		input.style.display = "none";
		document.body.appendChild(input);

		let settled = false;
		const cleanup = () => {
			if (input.parentNode) input.parentNode.removeChild(input);
		};

		input.addEventListener(
			"change",
			() => {
				if (settled) return;
				settled = true;
				const files = input.files ? Array.from(input.files) : [];
				cleanup();
				resolve(files.length ? files : null);
			},
			{ once: true }
		);

		input.addEventListener(
			"cancel",
			() => {
				if (settled) return;
				settled = true;
				cleanup();
				resolve(null);
			},
			{ once: true }
		);

		input.click();
	});
}

/**
 * OS file picker tuned for sample-item uploads: images (png/jpg/gif/webp)
 * and plain markdown. PDFs are intentionally excluded — a PDF is almost
 * never a single-problem sample and the top "Upload" section already
 * routes it through the paper-ingest pipeline that turns it into
 * concepts.
 */
function pickSampleUploadFromOS(): Promise<File[] | null> {
	return new Promise((resolve) => {
		const input = document.createElement("input");
		input.type = "file";
		input.accept = "image/png,image/jpeg,image/gif,image/webp,.md,text/markdown";
		input.multiple = true;
		input.style.display = "none";
		document.body.appendChild(input);

		let settled = false;
		const cleanup = () => {
			if (input.parentNode) input.parentNode.removeChild(input);
		};
		input.addEventListener(
			"change",
			() => {
				if (settled) return;
				settled = true;
				const files = input.files ? Array.from(input.files) : [];
				cleanup();
				resolve(files.length ? files : null);
			},
			{ once: true }
		);
		input.addEventListener(
			"cancel",
			() => {
				if (settled) return;
				settled = true;
				cleanup();
				resolve(null);
			},
			{ once: true }
		);
		input.click();
	});
}

/** Read a browser ``File`` as base64 without the data-URI prefix. */
async function fileToBase64(file: File): Promise<string> {
	const buf = await file.arrayBuffer();
	const bytes = new Uint8Array(buf);
	let binary = "";
	const chunk = 0x8000;
	for (let i = 0; i < bytes.length; i += chunk) {
		binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
	}
	return window.btoa(binary);
}

/**
 * Obsidian fuzzy folder picker. Presented via command-palette UX so the
 * user navigates their vault folder tree by typing — much more ergonomic
 * than a custom dropdown for vaults with hundreds of folders.
 */
class VaultFolderSuggestModal extends FuzzySuggestModal<TFolder> {
	constructor(
		app: import("obsidian").App,
		private readonly onPick: (folder: TFolder) => void
	) {
		super(app);
		this.setPlaceholder("Pick a folder — every .md inside becomes a concept");
	}

	getItems(): TFolder[] {
		const folders: TFolder[] = [];
		const root = this.app.vault.getRoot();
		const walk = (f: TFolder) => {
			folders.push(f);
			for (const child of f.children) {
				if (child instanceof TFolder) walk(child);
			}
		};
		walk(root);
		return folders;
	}

	getItemText(item: TFolder): string {
		return item.path || "/";
	}

	onChooseItem(item: TFolder): void {
		this.onPick(item);
	}
}

export const VIEW_TYPE_ITEM_GENERATOR = "knowledge-graph-item-generator";

/**
 * One "thing the user picked" — displayed as a single row in the upload
 * panel. The concept list visible to the backend is reconstructed from
 * the union of ``conceptIds`` across all sources, so removing a source
 * cleanly removes everything it contributed.
 */
type SourceKind = "file" | "folder" | "pdf";

interface ConceptSource {
	id: string;
	label: string;
	kind: SourceKind;
	meta: string;
	conceptIds: string[];
}

/** All known difficulties, ordered easiest → hardest. Drives the rows of
 * the coverage matrix and the color palette below. */
const DIFFICULTY_ORDER: Difficulty[] = [
	"easy",
	"medium",
	"hard",
	"very_hard",
	"expert",
];

/** Background colors used when a concept slot has been filled by an item
 * generated at that difficulty. Greens for foundational, warming through
 * yellow → orange → red for harder layers — matches the user's spec. */
const DIFFICULTY_COLORS: Record<Difficulty, string> = {
	easy: "#22c55e",       // green-500
	medium: "#16a34a",     // green-600 (dark green)
	hard: "#eab308",       // yellow-500
	very_hard: "#f97316",  // orange-500
	expert: "#ef4444",     // red-500
};

/** Per-concept usage tally across the whole session, keyed by concept id.
 * Each value maps difficulty → count of items at that difficulty that
 * cited the concept in ``foundation_concept_ids``. Used by the coverage
 * matrix to color cells. */
type CoverageMap = Record<string, Partial<Record<Difficulty, number>>>;

/** Per-concept mastery state. ``value`` is the current estimated
 * mastery in ``[0, 1]``; ``updates`` counts how many graded answers
 * have contributed (used for tooltips + "only show mastered if we
 * have at least N datapoints" heuristics). Updates come from
 * per-concept grader verdicts (Elo-style pull toward 1 or 0), with
 * a fallback uniform update when the grader didn't emit verdicts. */
type MasteryMap = Record<string, { value: number; updates: number }>;

/** Average score at or above which a concept is treated as "mastered" —
 * the LLM gets a high ``user_mastery`` for it, which biases the generator
 * toward synthesis/integration items rather than fresh drills. */
const MASTERY_THRESHOLD = 0.7;

/** Base learning rate for Elo-style mastery updates. Each graded
 * verdict pulls ``mastery`` toward its target (1 for positive, 0 for
 * negative) by ``lr * confidence * |target − mastery|``. Tuned so one
 * confident verdict nudges mastery ~0.2, and three consistent verdicts
 * land it near the target. */
const MASTERY_LR = 0.3;

/** Starting mastery for a never-rated concept. Matches the backend
 * default on ``InlineConcept.user_mastery`` so the LLM sees the same
 * "neutral" signal whether or not the plugin has graded the concept yet. */
const MASTERY_DEFAULT = 0.5;

export class ItemGeneratorView extends ItemView {
	plugin: KnowledgeGraphPlugin;
	private session: SessionResponse | null = null;
	private sessionFile: TFile | null = null;
	private sources: ConceptSource[] = [];
	private concepts: InlineConcept[] = [];
	private sampleItems: GeneratedItem[] = [];
	/** ``sample.title -> analysis`` — pedagogy feedback from the
	 *  sample-item analyzer, shown inline in the sample list and
	 *  serialized into ``analysis_notes`` on the GeneratedItem we
	 *  send to the backend. Lives outside ``sampleItems`` so removing
	 *  a sample doesn't orphan its analysis entry (cleaned up on
	 *  removal and on New Session). */
	private sampleAnalyses: Record<string, SampleItemAnalysis> = {};
	/** ``sample.title -> "pending" | "failed"`` UI state while the
	 *  analyzer is running so the list can show a spinner / error
	 *  badge without reaching into ``sampleAnalyses``. */
	private sampleAnalysisStatus: Record<string, "pending" | "failed"> = {};
	/** ``sample.title -> error message`` when analysis failed, so the
	 *  failure badge can surface the actual reason (wrong URL, 404,
	 *  upstream LLM error, etc.) via tooltip + inline text instead of
	 *  forcing the user to open DevTools. */
	private sampleAnalysisErrors: Record<string, string> = {};
	/** Per-sample inline images (photographed exam papers, figure
	 *  clips, etc.). When set, the analyzer receives them as the
	 *  multimodal ``context_images`` so OpenAI / Anthropic actually
	 *  "see" the sample instead of just its title. Kept off
	 *  ``GeneratedItem`` because the backend Generator schema doesn't
	 *  carry raw images on items — we fan them into ``context_images``
	 *  on the generation request when the sample is included. */
	private sampleImages: Record<string, ContextImage[]> = {};
	private contextImages: ContextImage[] = [];
	private generationCancelled = false;

	/** User-controlled cap on concept depth visible to the LLM. Bumped
	 * automatically when the backend signals ``advance_triggered`` after
	 * a strong-score round; the user can also drag the slider manually. */
	private focusDepth = 0;
	private scheduleMode: ScheduleMode = "all";
	/** ``concept_id -> { difficulty -> count }`` accumulated across rounds. */
	private coverage: CoverageMap = {};
	/** Per-concept mastery, updated live from per-concept verdicts at
	 * grading time. Fed back to the backend as ``user_mastery`` on
	 * subsequent requests so the generator combines mastered concepts
	 * instead of re-drilling them. */
	private mastery: MasteryMap = {};
	/** Items from the most recently generated round. Kept so the
	 * title → foundation_concept_ids map in ``buildTitleToFoundationMap``
	 * includes the fresh round too — important when the user answers
	 * and grades within the same session view, before next-round runs. */
	private lastRoundItems: GeneratedItem[] = [];
	/** Live reference to the coverage panel so we can rerender after a
	 * round without rebuilding the whole form. ``null`` when the form
	 * isn't currently mounted (e.g. session-controls view active). */
	private coverageEl: HTMLElement | null = null;
	/** Live reference to the sample-items list so the async analyzer
	 *  can trigger a re-render when a sample's analysis status
	 *  transitions pending → ready without touching the whole form. */
	private sampleListEl: HTMLElement | null = null;

	constructor(leaf: WorkspaceLeaf, plugin: KnowledgeGraphPlugin) {
		super(leaf);
		this.plugin = plugin;
	}

	getViewType(): string {
		return VIEW_TYPE_ITEM_GENERATOR;
	}

	getDisplayText(): string {
		return "Item Generator";
	}

	getIcon(): string {
		return "wand-sparkles";
	}

	async onOpen(): Promise<void> {
		this.renderForm();
	}

	async onClose(): Promise<void> {
		this.contentEl.empty();
	}

	/* ------------------------------------------------------------------ */
	/* Form rendering                                                      */
	/* ------------------------------------------------------------------ */

	private renderForm(): void {
		const el = this.contentEl;
		el.empty();
		el.addClass("kg-item-generator");
		let runGeneration: (() => Promise<void>) | null = null;
		// Stored references so post-action hooks can rerender just the
		// coverage panel without rebuilding the entire form.
		this.coverageEl = null;

		el.createEl("h2", { text: "Item Generator" });

		// --- Foundation Concepts (unified upload + sources panel) ---
		// Three entry points; all append to ``this.sources`` and indirectly
		// to ``this.concepts``. The UI shows one row per *source* (files,
		// folders, ingested PDFs) instead of per-concept — simpler to
		// reason about at scale. Removing a source drops every concept it
		// contributed via stored ``conceptIds``.
		const conceptSection = el.createDiv({ cls: "kg-section" });
		conceptSection.createEl("h3", { text: "Foundation Concepts" });
		const conceptSummary = conceptSection.createDiv({ cls: "kg-concept-summary" });
		const sourceList = conceptSection.createDiv({ cls: "kg-source-list" });

		const refresh = () => {
			this.renderSourceSummary(conceptSummary);
			this.renderSourceList(sourceList, refresh);
			// Coverage matrix depends on which concepts are present, so
			// refresh it whenever a source is added or removed.
			if (this.coverageEl) this.renderCoveragePanel(this.coverageEl);
		};

		// Single "Upload…" entry point. Tapping opens an Obsidian Menu
		// with the two concrete actions (OS file picker vs vault folder
		// picker). Collapsing both into one button keeps the primary
		// flow visually simple — users see ONE call to action — while
		// still exposing the folder path for power users.
		const uploadRow = conceptSection.createDiv({ cls: "kg-import-row" });
		const uploadBtn = uploadRow.createEl("button", {
			text: "Upload Files or Folder…",
			cls: "kg-btn kg-btn-primary kg-btn-full",
		});
		uploadBtn.addEventListener("click", (evt) => {
			const menu = new Menu();
			menu.addItem((it) =>
				it
					.setTitle("Choose .md / .pdf files…")
					.setIcon("file-text")
					.onClick(async () => {
						const picked = await pickFilesFromOS();
						if (!picked || picked.length === 0) return;
						uploadBtn.disabled = true;
						try {
							await this.handleUploadedFiles(picked);
							refresh();
						} finally {
							uploadBtn.disabled = false;
						}
					}),
			);
			menu.addItem((it) =>
				it
					.setTitle("Pick vault folder…")
					.setIcon("folder")
					.onClick(() => {
						new VaultFolderSuggestModal(this.app, async (folder) => {
							await this.addFolderSource(folder);
							refresh();
						}).open();
					}),
			);
			menu.showAtMouseEvent(evt);
		});

		const hint = conceptSection.createDiv({ cls: "kg-hint" });
		hint.textContent =
			"Upload .md / .pdf — PDFs are converted into a concept folder of " +
			"section notes. Or pick a vault folder to add every .md inside. " +
			"Duplicates auto-skipped.";

		// Fuzzy vault-note search for quick single-note adds.
		const searchWrap = conceptSection.createDiv({ cls: "kg-search-wrap" });
		const searchInput = searchWrap.createEl("input", {
			cls: "kg-input kg-search-input",
			attr: { type: "text", placeholder: "…or quick-add a vault note" },
		});
		const dropdown = searchWrap.createDiv({ cls: "kg-search-dropdown" });
		dropdown.style.display = "none";

		searchInput.addEventListener("input", () => {
			const query = searchInput.value.toLowerCase().trim();
			dropdown.empty();
			if (!query) { dropdown.style.display = "none"; return; }

			const files = this.app.vault.getMarkdownFiles()
				.filter((f) => f.basename.toLowerCase().includes(query))
				.slice(0, 10);

			if (files.length === 0) { dropdown.style.display = "none"; return; }
			dropdown.style.display = "block";

			for (const file of files) {
				const alreadyAdded = this.hasSourceForPath(file.path);
				const item = dropdown.createDiv({
					cls: `kg-search-item${alreadyAdded ? " kg-search-item-added" : ""}`,
				});
				item.createEl("span", { text: file.basename });
				if (alreadyAdded) {
					item.createEl("span", { cls: "kg-search-check", text: " (added)" });
				}
				item.addEventListener("click", async () => {
					if (!alreadyAdded) {
						await this.addVaultFileSource(file);
						refresh();
					}
					searchInput.value = "";
					dropdown.style.display = "none";
				});
			}
		});

		searchInput.addEventListener("blur", () => {
			setTimeout(() => { dropdown.style.display = "none"; }, 200);
		});
		searchInput.addEventListener("focus", () => {
			if (searchInput.value.trim()) searchInput.dispatchEvent(new Event("input"));
		});

		refresh();

		// --- Coverage panel (depth-aware schedule + concept usage map) ---
		// Hidden until at least one concept is loaded; the renderer itself
		// short-circuits to a hint if no graphed concepts are present, so
		// it's always safe to mount.
		const coverageSection = el.createDiv({ cls: "kg-section kg-coverage-section" });
		coverageSection.createEl("h3", { text: "Concept Coverage (Schedule)" });
		this.coverageEl = coverageSection.createDiv({ cls: "kg-coverage-panel" });
		this.renderCoveragePanel(this.coverageEl);

		// --- Sample Items ---
		// Unified affordance: one search input with a trailing "+" button
		// that opens a menu (Create new / Add all from SampleItems/). The
		// search dropdown still autocompletes existing samples as the
		// user types. Mirrors the Upload unification: one visual lane,
		// discoverable extra actions behind the button.
		const sampleSection = el.createDiv({ cls: "kg-section" });
		sampleSection.createEl("h3", { text: "Sample Items (optional reference)" });

		const sampleSearchRow = sampleSection.createDiv({ cls: "kg-search-row" });
		const sampleSearchWrap = sampleSearchRow.createDiv({ cls: "kg-search-wrap" });
		const sampleInput = sampleSearchWrap.createEl("input", {
			cls: "kg-input kg-search-input",
			attr: { type: "text", placeholder: "Search or add sample items…" },
		});
		const sampleDropdown = sampleSearchWrap.createDiv({ cls: "kg-search-dropdown" });
		sampleDropdown.style.display = "none";

		const sampleList = sampleSection.createDiv({ cls: "kg-concept-list" });
		this.sampleListEl = sampleList;
		this.renderSampleList(sampleList);

		const reRenderSampleList = () => {
			if (this.sampleListEl) this.renderSampleList(this.sampleListEl);
		};

		sampleInput.addEventListener("input", () => {
			const query = sampleInput.value.toLowerCase().trim();
			sampleDropdown.empty();
			if (!query) { sampleDropdown.style.display = "none"; return; }

			const files = this.app.vault.getMarkdownFiles()
				.filter((f) => f.path.startsWith("SampleItems/") && f.basename.toLowerCase().includes(query) && !f.basename.startsWith("_"))
				.slice(0, 10);

			if (files.length === 0) { sampleDropdown.style.display = "none"; return; }
			sampleDropdown.style.display = "block";

			for (const file of files) {
				const alreadyAdded = this.sampleItems.some((s) => s.title === file.basename);
				const item = sampleDropdown.createDiv({ cls: `kg-search-item${alreadyAdded ? " kg-search-item-added" : ""}` });
				item.createEl("span", { text: file.basename });
				if (alreadyAdded) item.createEl("span", { cls: "kg-search-check", text: " (added)" });
				item.addEventListener("click", async () => {
					if (!alreadyAdded) {
						await this.importSampleItem(file);
						reRenderSampleList();
						new Notice(`Sample added: ${file.basename}`);
					}
					sampleInput.value = "";
					sampleDropdown.style.display = "none";
				});
			}
		});

		sampleInput.addEventListener("blur", () => { setTimeout(() => { sampleDropdown.style.display = "none"; }, 200); });
		sampleInput.addEventListener("focus", () => { if (sampleInput.value.trim()) sampleInput.dispatchEvent(new Event("input")); });

		// Trailing add button — menu popover with the two actions that
		// used to live as separate full-width buttons.
		const sampleAddBtn = sampleSearchRow.createEl("button", {
			text: "+",
			cls: "kg-btn kg-btn-secondary kg-search-add-btn",
			attr: { "aria-label": "Add sample item" },
		});
		sampleAddBtn.addEventListener("click", (evt: MouseEvent) => {
			const menu = new Menu();
			menu.addItem((mi) =>
				mi
					.setTitle("Upload image / markdown as sample…")
					.setIcon("image-plus")
					.onClick(async () => {
						const files = await pickSampleUploadFromOS();
						if (files && files.length) {
							await this.importSampleUploadFiles(files);
						}
					})
			);
			menu.addItem((mi) =>
				mi
					.setTitle("Create new sample item…")
					.setIcon("file-plus")
					.onClick(async () => {
						await this.createSampleItemNote();
					})
			);
			menu.addItem((mi) =>
				mi
					.setTitle("Add all from SampleItems/")
					.setIcon("folder-plus")
					.onClick(async () => {
						const files = this.app.vault
							.getMarkdownFiles()
							.filter(
								(f) =>
									f.path.startsWith("SampleItems/") &&
									!f.basename.startsWith("_")
							);
						let added = 0;
						for (const f of files) {
							if (!this.sampleItems.some((s) => s.title === f.basename)) {
								await this.importSampleItem(f);
								added += 1;
							}
						}
						reRenderSampleList();
						new Notice(
							added
								? `Added ${added} sample item(s) from SampleItems/.`
								: "No new samples to add."
						);
					})
			);
			menu.addSeparator();
			menu.addItem((mi) =>
				mi
					.setTitle("Ingest PDF as paper (→ concepts, not sample)")
					.setIcon("file-text")
					.onClick(async () => {
						new Notice(
							"PDFs become a concept folder, not a sample. Use the Upload section above."
						);
					})
			);
			menu.showAtMouseEvent(evt);
		});

		// --- Context Images (inline visual context for LLM) ---
		const imageSection = el.createDiv({ cls: "kg-section" });
		imageSection.createEl("h3", { text: "Context Images (optional)" });

		const imageList = imageSection.createDiv({ cls: "kg-concept-list" });
		this.renderImageList(imageList);

		const imageBtnRow = imageSection.createDiv({ cls: "kg-import-row" });
		const attachImageBtn = imageBtnRow.createEl("button", { text: "Attach Image", cls: "kg-btn kg-btn-secondary" });
		attachImageBtn.addEventListener("click", () => {
			const input = document.createElement("input");
			input.type = "file";
			input.accept = "image/png,image/jpeg,image/gif,image/webp";
			input.multiple = true;
			input.addEventListener("change", async () => {
				if (!input.files) return;
				for (const file of Array.from(input.files)) {
					const buf = await file.arrayBuffer();
					const bytes = new Uint8Array(buf);
					let binary = "";
					for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
					const b64 = window.btoa(binary);
					const mediaType = file.type || "image/png";
					this.contextImages.push({ image_base64: b64, media_type: mediaType });
				}
				this.renderImageList(imageList);
				new Notice(`${input.files.length} image(s) attached.`);
			});
			input.click();
		});

		const attachVaultImgBtn = imageBtnRow.createEl("button", { text: "From Vault", cls: "kg-btn kg-btn-secondary" });
		attachVaultImgBtn.addEventListener("click", async () => {
			const imgFiles = this.app.vault.getFiles().filter((f) =>
				/\.(png|jpe?g|gif|webp)$/i.test(f.extension));
			if (imgFiles.length === 0) { new Notice("No image files found in vault."); return; }

			const picker = imageSection.createDiv({ cls: "kg-search-dropdown", attr: { style: "position:relative;display:block;max-height:200px;overflow-y:auto;" } });
			for (const img of imgFiles.slice(0, 30)) {
				const row = picker.createDiv({ cls: "kg-search-item" });
				row.createEl("span", { text: img.path });
				row.addEventListener("click", async () => {
					const buf = await this.app.vault.readBinary(img);
					const bytes = new Uint8Array(buf);
					let binary = "";
					for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
					const b64 = window.btoa(binary);
					const ext = img.extension.toLowerCase();
					const mediaType = ext === "png" ? "image/png" : ext === "gif" ? "image/gif" : ext === "webp" ? "image/webp" : "image/jpeg";
					this.contextImages.push({ image_base64: b64, media_type: mediaType });
					this.renderImageList(imageList);
					picker.remove();
					new Notice(`Attached: ${img.name}`);
				});
			}
		});

		// --- Generation options ---
		const optSection = el.createDiv({ cls: "kg-section" });
		optSection.createEl("h3", { text: "Generation Options" });

		const typeSelect = this.createSelect(optSection, "Item Type", [
			["problem", "Problem"],
			["definition", "Definition"],
			["flashcard", "Flashcard"],
			["code_challenge", "Code Challenge"],
		]);

		const diffSelect = this.createSelect(optSection, "Difficulty", [
			["easy", "Easy"],
			["medium", "Medium"],
			["hard", "Hard"],
			["very_hard", "Very Hard"],
			["expert", "Expert"],
		]);
		(diffSelect as HTMLSelectElement).value = "medium";

		const itemsInput = this.createNumberInput(optSection, "Items per round", 3, 1, 10);

		const reqField = optSection.createDiv({ cls: "kg-field" });
		reqField.createEl("label", { text: "User Requirements" });
		const reqTextarea = reqField.createEl("textarea", {
			cls: "kg-textarea",
			attr: { rows: "3", placeholder: "e.g., Focus on real-world applications..." },
		});

		// --- Generate button ---
		const actions = el.createDiv({ cls: "kg-actions" });
		const generateBtn = actions.createEl("button", { text: "Generate Items", cls: "kg-btn kg-btn-primary" });
		runGeneration = async () => {
			const validConcepts = this.concepts.filter((c) => c.title.trim());
			if (validConcepts.length === 0) {
				new Notice("Add at least one concept first.");
				return;
			}
			generateBtn.disabled = true;
			generateBtn.textContent = "Generating...";
			try {
				const combinedImages = this.collectAllImagesForGenerator();
				const req: InlineItemGenerateRequest = {
					concepts: validConcepts,
					edges: [],
					example_items: this.sampleItems.length > 0 ? this.sampleItems : undefined,
					context_images: combinedImages.length > 0 ? combinedImages : undefined,
					requested_type: typeSelect.value as ItemType,
					difficulty_preference: diffSelect.value as Difficulty,
					user_requirements: reqTextarea.value.trim(),
					items_per_round: parseInt(itemsInput.value) || 3,
					schedule_mode: this.scheduleMode,
					focus_depth: this.focusDepth,
				};
				this.lastRequestedType = req.requested_type || "problem";
				this.lastUserRequirements = req.user_requirements || "";
				this.session = await this.plugin.api.generateItems(req);
				// Pull in coverage from the freshly-created round so the
				// matrix paints right when the user opens the session.
				if (this.session.rounds.length > 0) {
					const last = this.session.rounds[this.session.rounds.length - 1];
					this.updateCoverageFromRound(last);
					this.syncFocusDepthFromState(last.scheduler_state);
					// Seed lastRoundItems so the next "Next Round" knows
					// which items to credit when scores come in.
					this.lastRoundItems = last.items;
				}
				await this.writeSessionFile();
				this.renderSessionControls();
			} catch (err) {
				new Notice(`Generation failed: ${(err as Error).message}`);
			} finally {
				generateBtn.disabled = false;
				generateBtn.textContent = "Generate Items";
			}
		};
		generateBtn.addEventListener("click", async () => {
			await runGeneration?.();
		});

		// --- Resume Session (moved to bottom — secondary flow) ---
		const resumeSection = el.createDiv({ cls: "kg-section" });
		resumeSection.createEl("h3", { text: "Resume Session" });
		const resumeWrap = resumeSection.createDiv({ cls: "kg-search-wrap" });
		const resumeSelect = resumeWrap.createEl("select", { cls: "kg-select" });
		resumeSelect.createEl("option", {
			text: "— select an existing session note —",
			attr: { value: "" },
		});

		const sessionFiles = this.app.vault.getMarkdownFiles()
			.filter((f) => f.path.startsWith("Items/"))
			.sort((a, b) => b.stat.mtime - a.stat.mtime);
		for (const f of sessionFiles) {
			resumeSelect.createEl("option", { text: f.basename, attr: { value: f.path } });
		}

		const resumeBtn = resumeSection.createEl("button", {
			text: "Resume",
			cls: "kg-btn kg-btn-secondary",
			attr: { disabled: "true" },
		});
		resumeSelect.addEventListener("change", () => {
			(resumeBtn as HTMLButtonElement).disabled = !resumeSelect.value;
		});
		resumeBtn.addEventListener("click", async () => {
			const path = resumeSelect.value;
			if (!path) return;
			const file = this.app.vault.getAbstractFileByPath(path);
			if (!(file instanceof TFile)) { new Notice("File not found."); return; }
			(resumeBtn as HTMLButtonElement).disabled = true;
			resumeBtn.textContent = "Loading...";
			try {
				await this.resumeFromFile(file);
				this.renderSessionControls();
			} catch (err) {
				new Notice(`Resume failed: ${(err as Error).message}`);
			} finally {
				(resumeBtn as HTMLButtonElement).disabled = false;
				resumeBtn.textContent = "Resume";
			}
		});

		// If we already have an active session, show controls
		if (this.session) {
			this.renderSessionControls();
		}
	}

	/* ------------------------------------------------------------------ */
	/* Dynamic list renderers                                              */
	/* ------------------------------------------------------------------ */

	/**
	 * One-line scale hint above the source list. Counts sources and the
	 * total number of concepts they contributed so the user always sees
	 * both "what I picked" and "how much the LLM will see".
	 */
	private renderSourceSummary(container: HTMLElement): void {
		container.empty();
		const s = this.sources.length;
		const c = this.concepts.length;
		container.createEl("div", {
			cls: "kg-hint",
			text: s === 0
				? "No sources added yet. Upload .md / .pdf files or pick a folder."
				: `${s} source${s === 1 ? "" : "s"} · ${c} concept${c === 1 ? "" : "s"} total · duplicates auto-skipped.`,
		});
	}

	/**
	 * Source-row list. One row per file/folder/PDF the user picked —
	 * not per concept. Removing a row removes every concept that source
	 * contributed.
	 */
	private renderSourceList(container: HTMLElement, refresh: () => void): void {
		container.empty();
		if (this.sources.length === 0) return;

		this.sources.forEach((source) => {
			const row = container.createDiv({ cls: "kg-source-row" });
			const icon = source.kind === "pdf" ? "📄"
				: source.kind === "folder" ? "📁"
				: "📝";
			row.createEl("span", { cls: "kg-source-icon", text: icon });
			row.createEl("span", { cls: "kg-source-label", text: source.label });
			row.createEl("span", { cls: "kg-source-meta", text: source.meta });

			const removeBtn = row.createEl("button", { text: "×", cls: "kg-btn-remove" });
			removeBtn.addEventListener("click", () => {
				this.removeSource(source.id);
				refresh();
			});
		});
	}

	/**
	 * Drop every concept the given source contributed, then drop the
	 * source row itself. Concepts contributed by *other* sources are
	 * preserved — each concept id is owned by the first source that
	 * imported it (set via ``importFile``'s added=true path).
	 */
	private removeSource(sourceId: string): void {
		const src = this.sources.find((s) => s.id === sourceId);
		if (!src) return;
		const kill = new Set(src.conceptIds);
		this.concepts = this.concepts.filter((c) => !kill.has(c.id));
		this.sources = this.sources.filter((s) => s.id !== sourceId);
	}

	private hasSourceForPath(path: string): boolean {
		return this.sources.some((s) => s.id === this.syntheticIdForPath(path));
	}

	/* ------------------------------------------------------------------ */
	/* Coverage matrix (depth-aware schedule + per-difficulty fill)        */
	/* ------------------------------------------------------------------ */

	/** Group ``this.concepts`` by depth, preserving the input order
	 * inside each layer so the matrix reads left-to-right ≈ paper order
	 * within a layer, top-down by depth across layers. */
	private groupConceptsByDepth(): { depth: number; concepts: InlineConcept[] }[] {
		const buckets = new Map<number, InlineConcept[]>();
		for (const c of this.concepts) {
			const d = c.depth ?? 0;
			if (!buckets.has(d)) buckets.set(d, []);
			buckets.get(d)!.push(c);
		}
		return Array.from(buckets.entries())
			.sort((a, b) => a[0] - b[0])
			.map(([depth, concepts]) => ({ depth, concepts }));
	}

	/** Top difficulty among items that referenced this concept this
	 * session — that's the color we paint the cell. Returns ``null`` if
	 * the concept has never been used. */
	private dominantDifficultyFor(conceptId: string): Difficulty | null {
		const usage = this.coverage[conceptId];
		if (!usage) return null;
		// Prefer the *highest* difficulty cited so the cell color signals
		// "this concept was actually exercised at level X" rather than
		// being washed out by an early easy round.
		for (let i = DIFFICULTY_ORDER.length - 1; i >= 0; i--) {
			const d = DIFFICULTY_ORDER[i];
			if ((usage[d] ?? 0) > 0) return d;
		}
		return null;
	}

	/**
	 * Render the coverage panel: a focus-depth slider on top, then one
	 * row per concept layer (c0 … cN) where each cell is a single
	 * concept. Cells are colored by the highest difficulty an item using
	 * that concept was generated at; unused cells stay neutral.
	 *
	 * The matrix doubles as a study plan: as the user clears a layer at
	 * a given difficulty, the row fills with that color; when they
	 * advance focus_depth, the next row starts coloring in too.
	 */
	private renderCoveragePanel(container: HTMLElement): void {
		container.empty();

		if (this.concepts.length === 0) {
			container.createEl("div", {
				cls: "kg-hint",
				text: "Add concept sources above to enable depth-aware scheduling.",
			});
			return;
		}

		const groups = this.groupConceptsByDepth();
		const maxDepth = groups[groups.length - 1]?.depth ?? 0;
		const hasGraph = maxDepth > 0;

		// Schedule mode toggle. ``top_down`` only makes sense when we
		// actually have multiple depth layers; we still let users toggle
		// it on a single-layer pool but warn that it'll be a no-op.
		const controls = container.createDiv({ cls: "kg-coverage-controls" });

		const modeRow = controls.createDiv({ cls: "kg-coverage-row" });
		modeRow.createEl("label", { text: "Schedule:" });
		const modeSelect = modeRow.createEl("select", { cls: "kg-select" });
		modeSelect.createEl("option", { text: "All concepts at once", attr: { value: "all" } });
		modeSelect.createEl("option", { text: "Top-down by dependency", attr: { value: "top_down" } });
		modeSelect.value = this.scheduleMode;
		modeSelect.addEventListener("change", () => {
			this.scheduleMode = modeSelect.value as ScheduleMode;
			this.renderCoveragePanel(container);
		});

		// Focus-depth slider. Only meaningful in top_down mode; we still
		// render it in ``all`` so users see how it would clamp when they
		// switch — keeps the UI predictable.
		const depthRow = controls.createDiv({ cls: "kg-coverage-row" });
		depthRow.createEl("label", { text: `Focus depth: c${this.focusDepth}` });
		const slider = depthRow.createEl("input", {
			cls: "kg-input kg-focus-slider",
			attr: {
				type: "range",
				min: "0",
				max: String(Math.max(0, maxDepth)),
				step: "1",
				value: String(Math.min(this.focusDepth, maxDepth)),
				disabled: hasGraph ? null : "true",
			} as Record<string, string | null>,
		}) as HTMLInputElement;
		slider.addEventListener("input", () => {
			this.focusDepth = parseInt(slider.value, 10) || 0;
			this.renderCoveragePanel(container);
		});

		if (!hasGraph) {
			container.createEl("div", {
				cls: "kg-hint",
				text:
					"All concepts share depth 0 (graph not built or single-layer source). " +
					"Top-down scheduling is a no-op until you ingest a paper with " +
					"INGEST_BUILD_GRAPH enabled.",
			});
		}

		// Single fixed-width bar. One slot per concept — denser when
		// there are more concepts, always same total width. Concepts
		// are laid out left→right in dependency order (c0 first, then
		// c1, …) but the depth boundaries are NOT separated by gaps or
		// labels: they're just thin ticks painted on the cell that
		// starts a new depth layer. Focus-depth boundary is a thicker
		// accent-colored tick in the same space.
		//
		// Color rule per slot: ``dominantDifficultyFor`` (harder
		// overrules easier across rounds). Mastered concepts (avg ≥
		// MASTERY_THRESHOLD) still get the ✓ overlay.
		const flatConcepts: { c: InlineConcept; depth: number; startsDepth: boolean; crossesFocus: boolean }[] = [];
		let prevDepth = -1;
		for (const g of groups) {
			const nextLayerCrossesFocus =
				this.scheduleMode === "top_down" &&
				hasGraph &&
				prevDepth <= this.focusDepth &&
				g.depth > this.focusDepth;
			for (let i = 0; i < g.concepts.length; i++) {
				flatConcepts.push({
					c: g.concepts[i],
					depth: g.depth,
					startsDepth: i === 0 && prevDepth !== -1 && g.depth !== prevDepth,
					crossesFocus: i === 0 && nextLayerCrossesFocus,
				});
			}
			prevDepth = g.depth;
		}

		const bar = container.createDiv({ cls: "kg-coverage-bar" });
		bar.setAttribute("data-count", String(flatConcepts.length));

		for (const entry of flatConcepts) {
			const { c, depth, startsDepth, crossesFocus } = entry;
			const cell = bar.createDiv({ cls: "kg-coverage-cell" });

			const inScope =
				this.scheduleMode !== "top_down" || depth <= this.focusDepth;
			const dom = this.dominantDifficultyFor(c.id);
			const totalHits = this.coverage[c.id]
				? Object.values(this.coverage[c.id]).reduce((a, b) => a + (b ?? 0), 0)
				: 0;

			if (dom) {
				cell.style.background = DIFFICULTY_COLORS[dom];
				cell.style.opacity = "1";
			} else {
				cell.style.background = inScope
					? "var(--background-modifier-border)"
					: "transparent";
				cell.style.opacity = inScope ? "0.45" : "0.15";
			}

			if (!inScope) cell.classList.add("kg-coverage-cell-out");
			if (startsDepth) cell.classList.add("kg-coverage-cell-depth-tick");
			if (crossesFocus) cell.classList.add("kg-coverage-cell-focus-tick");
			if (totalHits > 0) cell.setAttribute("data-hits", String(totalHits));

			const avg = this.masteryAvgFor(c.id);
			if (avg !== null && avg >= MASTERY_THRESHOLD) {
				cell.classList.add("kg-coverage-cell-mastered");
				cell.createEl("span", { cls: "kg-coverage-cell-check", text: "✓" });
			}

			const breakdown = DIFFICULTY_ORDER
				.map((d) => `${d}=${this.coverage[c.id]?.[d] ?? 0}`)
				.filter((s) => !s.endsWith("=0"))
				.join(", ");
			const masteryNote =
				avg !== null
					? ` · mastery=${(avg * 100).toFixed(0)}%${
						avg >= MASTERY_THRESHOLD ? " (mastered → combined)" : ""
					}`
					: "";
			cell.title =
				`${c.title} · depth=c${depth}` +
				(dom ? ` · max=${dom}` : " · unused") +
				masteryNote +
				(breakdown ? ` (${breakdown})` : "") +
				(inScope ? "" : " · out of scope");
		}

		// Readout line: concept count + scope summary. Replaces the old
		// per-layer "c0 (7) c1 (7)" header — same info, one line, no
		// visual real estate cost.
		const ann = container.createDiv({ cls: "kg-coverage-annotation" });
		const depthBreakdown = groups.map((g) => `c${g.depth}:${g.concepts.length}`).join(" · ");
		const scopeText = hasGraph
			? this.scheduleMode === "top_down"
				? `focus_depth=${this.focusDepth} (only c0…c${this.focusDepth} injected)`
				: `focus_depth=${this.focusDepth} (ignored — schedule is "all")`
			: "single-layer pool — top-down is a no-op";
		ann.textContent = `${flatConcepts.length} concepts — ${depthBreakdown} · ${scopeText}`;

		// Legend: concise reminder of the color → difficulty mapping.
		const legend = container.createDiv({ cls: "kg-coverage-legend" });
		for (const d of DIFFICULTY_ORDER) {
			const swatch = legend.createDiv({ cls: "kg-coverage-swatch" });
			swatch.style.background = DIFFICULTY_COLORS[d];
			legend.createEl("span", { cls: "kg-coverage-swatch-label", text: d });
		}
	}

	/**
	 * Increment the per-concept usage counts using the items the LLM
	 * just produced. Each generated item carries
	 * ``foundation_concept_ids`` (set by the Generator) so we know
	 * exactly which concepts were exercised at which difficulty.
	 */
	private updateCoverageFromRound(round: RoundResult): void {
		for (const item of round.items) {
			const diff = item.difficulty;
			for (const cid of item.foundation_concept_ids || []) {
				if (!this.coverage[cid]) this.coverage[cid] = {};
				this.coverage[cid][diff] = (this.coverage[cid][diff] ?? 0) + 1;
			}
		}
	}

	/** Current mastery estimate for a concept in ``[0, 1]``, or ``null``
	 * if it's never been graded this session. Values ≥
	 * ``MASTERY_THRESHOLD`` drive the "✓ mastered → combine" behavior
	 * (both in the coverage UI and in the backend generator via the
	 * ``user_mastery`` field). */
	private masteryAvgFor(conceptId: string): number | null {
		const m = this.mastery[conceptId];
		if (!m || m.updates === 0) return null;
		return m.value;
	}

	/** Pull a concept's mastery toward ``target`` (0 or 1) by
	 * ``MASTERY_LR * strength``. Clipped to ``[0, 1]``. Starting value
	 * is ``MASTERY_DEFAULT`` if the concept hasn't been seen before —
	 * this matches the backend's default so the first update lands on
	 * "neutral" rather than on zero. */
	private bumpMastery(conceptId: string, target: number, strength: number): void {
		const prev = this.mastery[conceptId] ?? {
			value: MASTERY_DEFAULT,
			updates: 0,
		};
		const delta = MASTERY_LR * Math.max(0, Math.min(1, strength)) * (target - prev.value);
		const next = Math.max(0, Math.min(1, prev.value + delta));
		this.mastery[conceptId] = { value: next, updates: prev.updates + 1 };
	}

	/**
	 * Apply per-concept verdicts from the grader to our local mastery
	 * state. Signed updates by verdict:
	 *
	 * - ``correctly_applied``  → pull toward 1 by ``score * conf``.
	 *   The student used the concept and got it right.
	 * - ``alternative_path``   → pull toward 1 by ``score * conf``.
	 *   The student solved it another way; we don't want to penalize
	 *   just because the listed concept wasn't invoked.
	 * - ``misapplied``         → pull toward 0 by ``conf``. Clear
	 *   misunderstanding; mastery should specifically drop for this
	 *   concept without dragging unrelated concepts down.
	 * - ``not_demonstrated``   → no update. The answer didn't touch
	 *   this concept, so we have no new signal either direction.
	 *
	 * ``globalScore`` is the item's overall correctness; positive
	 * verdicts are scaled by it so "barely correct (0.5)" contributes
	 * less than "fully correct (1.0)", even when the grader is confident.
	 */
	private applyVerdicts(verdicts: ConceptVerdict[], globalScore: number): void {
		for (const v of verdicts) {
			switch (v.status) {
				case "correctly_applied":
				case "alternative_path":
					this.bumpMastery(v.concept_id, 1, globalScore * v.confidence);
					break;
				case "misapplied":
					this.bumpMastery(v.concept_id, 0, v.confidence);
					break;
				case "not_demonstrated":
					// No signal either direction.
					break;
			}
		}
	}

	/** Legacy fallback for when the grader didn't emit ``per_concept``
	 * (old prompt, parse failure, etc.). Distribute the global score
	 * uniformly over the item's foundation concepts as a best effort
	 * — better than no update, worse than a real verdict. */
	private applyGlobalScoreFallback(conceptIds: string[], score: number): void {
		for (const cid of conceptIds) {
			this.bumpMastery(cid, score >= 0.5 ? 1 : 0, Math.abs(score - 0.5) * 2);
		}
	}

	/** Returns a copy of the concept list with ``user_mastery`` set to
	 * the current mastery value for every graded concept. Concepts
	 * without any update keep their original mastery, so freshly added
	 * sources still get full drill treatment. */
	private applyMasteryToConcepts(concepts: InlineConcept[]): InlineConcept[] {
		return concepts.map((c) => {
			const avg = this.masteryAvgFor(c.id);
			if (avg === null) return c;
			return { ...c, user_mastery: avg };
		});
	}

	/** Build a title → foundation_concept_ids lookup from the session's
	 * known rounds + the most recent round. Used at grade-time to tell
	 * the backend *exactly* which concepts this specific item was built
	 * on, so per-concept verdicts can reference real ids (not just the
	 * whole session-wide concept pool). */
	private buildTitleToFoundationMap(): Map<string, string[]> {
		const map = new Map<string, string[]>();
		const push = (items: GeneratedItem[] | undefined) => {
			for (const it of items ?? []) {
				if (!it.title) continue;
				// Last writer wins — more recent items tend to have
				// the best-groomed foundation list.
				map.set(it.title.trim(), it.foundation_concept_ids ?? []);
			}
		};
		for (const r of this.session?.rounds ?? []) push(r.items);
		push(this.lastRoundItems);
		return map;
	}

	/**
	 * Honor ``scheduler_state.next_focus_depth`` from the backend after a
	 * scoring round: when the user crossed the advance threshold, the
	 * next request will already be one layer deeper without them having
	 * to touch the slider. Capped at the deepest concept in scope.
	 */
	private syncFocusDepthFromState(state: SchedulerState | null | undefined): void {
		if (!state) return;
		if (state.advance_triggered) {
			const maxD = Math.max(
				state.max_depth_seen,
				...this.concepts.map((c) => c.depth ?? 0),
				0,
			);
			this.focusDepth = Math.min(state.next_focus_depth, maxD);
		}
	}

	/* ------------------------------------------------------------------ */
	/* Session controls (side panel — items live in the .md file)           */
	/* ------------------------------------------------------------------ */

	private renderSessionControls(): void {
		const el = this.contentEl;
		el.empty();
		el.addClass("kg-item-generator");

		if (!this.session) return;

		el.createEl("h2", { text: "Session Active" });

		const meta = el.createDiv({ cls: "kg-session-meta" });
		meta.createEl("div", { text: `Difficulty: ${this.session.current_difficulty}` });
		meta.createEl("div", { text: `Rounds: ${this.session.rounds.length}` });
		meta.createEl("div", { text: `Status: ${this.session.status}` });

		// Schedule snapshot: what the backend told us about the last
		// round's depth-aware scheduling. Surfacing this in-session
		// makes the auto-advance behavior visible — without it the
		// slider just silently moves between rounds.
		const lastRound = this.session.rounds[this.session.rounds.length - 1];
		const schedState = lastRound?.scheduler_state;
		if (schedState && schedState.schedule_mode === "top_down") {
			const cls = schedState.advance_triggered
				? "kg-notice kg-notice-success"
				: "kg-notice";
			const advanceMsg = schedState.advance_triggered
				? ` → advanced to c${schedState.next_focus_depth}`
				: "";
			el.createDiv({
				cls,
				text:
					`Schedule: top-down @ c${schedState.focus_depth_used} ` +
					`(${schedState.visible_concept_count} visible, ` +
					`${schedState.filtered_concept_count} held back)${advanceMsg}`,
			});
		}

		if (this.session.feasibility === "ABANDON") {
			el.createDiv({ cls: "kg-notice kg-notice-warn", text: "Topic declined — requires expert-authored items." });
			this.addBackButton(el);
			return;
		}

		if (this.sessionFile) {
			const openBtn = el.createEl("button", { text: "Open Session Note", cls: "kg-btn kg-btn-secondary" });
			openBtn.style.marginBottom = "12px";
			openBtn.addEventListener("click", () => {
				if (this.sessionFile) {
					this.app.workspace.getLeaf(false).openFile(this.sessionFile);
				}
			});
		}

		// Step 1: Grade answers
		const actions = el.createDiv({ cls: "kg-actions-stack" });

		const gradeBtn = actions.createEl("button", { text: "1. Grade My Answers", cls: "kg-btn kg-btn-accent kg-btn-full" });
		gradeBtn.addEventListener("click", async () => {
			if (!this.sessionFile || !this.session) {
				new Notice("No session file to grade.");
				return;
			}
			gradeBtn.disabled = true;
			gradeBtn.textContent = "Grading...";
			try {
				const result = await this.gradeAllAnswers();
				if (result === 0) {
					new Notice("No answers to grade. Write your answers first.");
				} else {
					new Notice(`Graded ${result} answer(s) — check your note for feedback.`);
				}
			} catch (err) {
				new Notice(`Grading failed: ${(err as Error).message}`);
			} finally {
				gradeBtn.disabled = false;
				gradeBtn.textContent = "1. Grade My Answers";
			}
		});

		// Difficulty selector for next round
		const diffField = actions.createDiv({ cls: "kg-field" });
		diffField.createEl("label", { text: "Next Round Difficulty" });
		const diffSelect = diffField.createEl("select", { cls: "kg-select" });
		for (const [val, label] of [["easy", "Easy"], ["medium", "Medium"], ["hard", "Hard"], ["very_hard", "Very Hard"], ["expert", "Expert"]] as const) {
			const opt = diffSelect.createEl("option", { text: label, attr: { value: val } });
			if (this.session && val === this.session.current_difficulty) {
				opt.selected = true;
			}
		}

		// Step 2: Generate next round via stateless continue-round
		const nextBtn = actions.createEl("button", { text: "2. Next Round", cls: "kg-btn kg-btn-primary kg-btn-full" });
		let generating = false;
		nextBtn.addEventListener("click", async () => {
			if (generating) {
				this.generationCancelled = true;
				nextBtn.textContent = "Cancelling...";
				nextBtn.disabled = true;
				return;
			}

			generating = true;
			this.generationCancelled = false;
			nextBtn.textContent = "Cancel Generation";
			nextBtn.classList.remove("kg-btn-primary");
			nextBtn.classList.add("kg-btn-cancel");
			try {
				const priorRoundCount = await this.countRoundsInFile();
				const chosenDiff = diffSelect.value as Difficulty;

				// Mastery is already up-to-date here — gradeAllAnswers()
				// applied per-concept verdicts at grading time. All we
				// need to do is collect the per-item scores for the
				// backend's difficulty/focus-depth auto-advance.
				const allScores = await this.collectGradingScoresAsync();

				const req: ContinueRoundRequest = {
					concepts: this.applyMasteryToConcepts(
						this.concepts.filter((c) => c.title.trim()),
					),
					edges: [],
					example_items: this.sampleItems.length > 0 ? this.sampleItems : undefined,
					context_images: (() => {
						const all = this.collectAllImagesForGenerator();
						return all.length > 0 ? all : undefined;
					})(),
					user_scores: allScores,
					prior_round_count: priorRoundCount,
					current_difficulty: chosenDiff,
					override_difficulty: chosenDiff,
					requested_type: (await this.readFrontmatterField("requested_type") as ItemType) || "problem",
					user_requirements: (await this.readFrontmatterField("user_requirements") as string) || "",
					items_per_round: 3,
					schedule_mode: this.scheduleMode,
					focus_depth: this.focusDepth,
				};

				const roundResult = await this.plugin.api.continueRound(req);
				this.updateCoverageFromRound(roundResult);
				this.syncFocusDepthFromState(roundResult.scheduler_state);
				this.lastRoundItems = roundResult.items;

				if (this.generationCancelled) {
					new Notice("Generation cancelled — result discarded.");
					this.generationCancelled = false;
					generating = false;
					nextBtn.disabled = false;
					nextBtn.textContent = "2. Next Round";
					nextBtn.classList.remove("kg-btn-cancel");
					nextBtn.classList.add("kg-btn-primary");
					return;
				}

				await this.appendRoundResult(roundResult);
				await this.updateFrontmatterInFile({ difficulty: chosenDiff });

				if (this.session) {
					this.session.rounds.push(roundResult);
					this.session.current_difficulty = chosenDiff;
				}

				this.renderSessionControls();
				new Notice(`Round ${priorRoundCount + 1} generated — difficulty: ${chosenDiff}`);
			} catch (err) {
				if (this.generationCancelled) {
					new Notice("Generation cancelled.");
				} else {
					new Notice(`Next round failed: ${(err as Error).message}`);
				}
				this.generationCancelled = false;
				generating = false;
				nextBtn.disabled = false;
				nextBtn.textContent = "2. Next Round";
				nextBtn.classList.remove("kg-btn-cancel");
				nextBtn.classList.add("kg-btn-primary");
			}
		});

		const hint = actions.createDiv({ cls: "kg-hint" });
		hint.textContent = "Pick your difficulty — hard+ triggers iterative hardening with extra concepts.";

		// Finish session
		const bottomRow = actions.createDiv({ cls: "kg-import-row" });

		const finishBtn = bottomRow.createEl("button", { text: "Finish Session", cls: "kg-btn kg-btn-secondary" });
		finishBtn.addEventListener("click", async () => {
			if (this.session) {
				this.session.status = "completed";
				await this.updateFrontmatterInFile({ status: "completed" });
				this.renderSessionControls();
				new Notice("Session finished.");
			}
		});

		this.addBackButton(bottomRow);

		if (this.session.status === "completed") {
			el.createDiv({ cls: "kg-notice kg-notice-success", text: "Session marked as complete. Click 'Next Round' to continue or 'New Session' to start fresh." });
		}
	}

	/* ------------------------------------------------------------------ */
	/* Markdown file generation                                            */
	/* ------------------------------------------------------------------ */

	private async writeSessionFile(): Promise<void> {
		if (!this.session) return;

		const topics = this.concepts.map((c) => c.title).join(", ");
		const date = new Date().toISOString().slice(0, 10);
		const fileName = `Items/${date} ${topics.slice(0, 40)}.md`;

		const dir = "Items";
		if (!this.app.vault.getAbstractFileByPath(dir)) {
			await this.app.vault.createFolder(dir);
		}

		const md = this.buildFullSessionMd();

		const existing = this.app.vault.getAbstractFileByPath(fileName);
		if (existing instanceof TFile) {
			await this.app.vault.modify(existing, md);
			this.sessionFile = existing;
		} else {
			this.sessionFile = await this.app.vault.create(fileName, md);
		}

		const leaf = this.app.workspace.getLeaf(false);
		await leaf.openFile(this.sessionFile);
		new Notice(`Session note created: ${fileName}`);
	}

	private async appendNewRounds(prevCount: number): Promise<void> {
		if (!this.session || !this.sessionFile) return;

		const newRounds = this.session.rounds.slice(prevCount);
		if (newRounds.length === 0) return;

		let appendMd = "";

		const lastPrev = prevCount > 0 ? this.session.rounds[prevCount - 1] : null;
		if (lastPrev?.grader_summary) {
			appendMd += this.graderSummaryToMd(lastPrev.grader_summary);
		}

		for (const round of newRounds) {
			appendMd += this.roundToMd(round);
		}

		const current = await this.app.vault.read(this.sessionFile);
		await this.app.vault.modify(this.sessionFile, current + "\n" + appendMd);

		const leaf = this.app.workspace.getLeaf(false);
		await leaf.openFile(this.sessionFile);
	}

	private lastRequestedType: ItemType = "problem";
	private lastUserRequirements: string = "";

	private buildFullSessionMd(): string {
		if (!this.session) return "";

		const topics = this.concepts.map((c) => `[[${c.title}]]`).join(", ");
		const lines: string[] = [];

		lines.push(`---`);
		lines.push(`session_id: "${this.session.session_id}"`);
		lines.push(`type: item-session`);
		lines.push(`status: ${this.session.status}`);
		lines.push(`difficulty: ${this.session.current_difficulty}`);
		lines.push(`requested_type: ${this.lastRequestedType}`);
		lines.push(`user_requirements: "${this.lastUserRequirements}"`);
		lines.push(`created: ${new Date().toISOString()}`);
		lines.push(`---`);
		lines.push(``);
		lines.push(`# Item Session`);
		lines.push(``);
		lines.push(`**Topics:** ${topics}`);
		lines.push(`**Difficulty:** ${this.session.current_difficulty} | **Status:** ${this.session.status}`);
		lines.push(``);

		for (const round of this.session.rounds) {
			lines.push(this.roundToMd(round));
		}

		return lines.join("\n");
	}

	private roundToMd(round: RoundResult): string {
		const lines: string[] = [];

		lines.push(`---`);
		lines.push(``);
		lines.push(`## Round ${round.round_number}`);
		lines.push(``);

		for (let i = 0; i < round.items.length; i++) {
			const item = round.items[i];
			const num = i + 1;

			lines.push(`### ${num}. ${item.title}`);
			lines.push(`\`${item.type}\` | \`${item.difficulty}\``);
			lines.push(``);
			lines.push(item.body_md);
			lines.push(``);

			lines.push(`#### Your Answer`);
			lines.push(``);
			lines.push(`> [!quote]- Write your answer here`);
			lines.push(`> `);
			lines.push(`> `);
			lines.push(`> `);
			lines.push(``);

			lines.push(`> [!success]- Solution`);
			for (const line of item.answer_md.split("\n")) {
				lines.push(`> ${line}`);
			}
			lines.push(``);

			if (item.explanation_md) {
				lines.push(`> [!info]- Explanation`);
				for (const line of item.explanation_md.split("\n")) {
					lines.push(`> ${line}`);
				}
				lines.push(``);
			}
		}

		return lines.join("\n");
	}

	private graderSummaryToMd(grader: import("../types").GraderSummary): string {
		const lines: string[] = [];
		lines.push(`### Grader Summary (Round ${grader.round_number})`);
		lines.push(``);
		lines.push(`> [!abstract] Learning Assessment`);
		lines.push(`> ${grader.learning_summary}`);
		lines.push(`>`);
		lines.push(`> **Next difficulty:** ${grader.next_difficulty} | **Requirements met:** ${grader.requirements_met ? "Yes" : "No"}`);
		if (grader.recommendation) {
			lines.push(`>`);
			lines.push(`> *${grader.recommendation}*`);
		}
		const entries = Object.entries(grader.mastery_delta);
		if (entries.length > 0) {
			lines.push(`>`);
			lines.push(`> **Mastery changes:**`);
			for (const [concept, delta] of entries) {
				const sign = delta >= 0 ? "+" : "";
				lines.push(`> - ${concept}: ${sign}${delta.toFixed(2)}`);
			}
		}
		lines.push(``);
		return lines.join("\n");
	}

	/* ------------------------------------------------------------------ */
	/* Answer grading                                                      */
	/* ------------------------------------------------------------------ */

	private async gradeAllAnswers(): Promise<number> {
		if (!this.sessionFile || !this.session) return 0;

		const content = await this.app.vault.read(this.sessionFile);
		const parsed = this.parseItemsAndAnswers(content);

		let gradedCount = 0;
		let updatedContent = content;

		// title → foundation_concept_ids from the session's rounds, so
		// each graded item passes the *right* concept subset to the
		// grader (not every concept in the whole session). Also gives
		// us ids to reattach per-concept verdicts to our mastery map.
		const titleToFoundations = this.buildTitleToFoundationMap();
		const conceptById = new Map(this.concepts.map((c) => [c.id, c]));

		for (const entry of parsed) {
			if (!entry.userAnswer || entry.userAnswer.trim().length === 0) continue;
			if (entry.alreadyGraded) continue;

			// Look up this item's foundation concepts — fall back to
			// the whole session pool only when we don't have a mapping
			// (e.g. resumed session without round metadata). That keeps
			// grading functional even in degraded cases.
			const foundationIds = titleToFoundations.get(entry.title.trim()) ?? [];
			const conceptRefs: ConceptRef[] =
				foundationIds.length > 0
					? foundationIds
						.map((id) => conceptById.get(id))
						.filter((c): c is InlineConcept => !!c)
						.map((c) => ({ id: c.id, title: c.title }))
					: this.concepts.map((c) => ({ id: c.id, title: c.title }));

			const req: AnswerGradeRequest = {
				item_title: entry.title,
				item_body_md: entry.bodyMd,
				reference_answer_md: entry.solutionMd,
				user_answer_md: entry.userAnswer,
				foundation_concepts: conceptRefs,
			};

			const feedback = await this.plugin.api.gradeAnswer(req);

			// Update mastery HERE — right after each grading, so the
			// user sees the coverage row change before the next round.
			// Prefer per-concept verdicts; fall back to a uniform
			// global-score update over foundationIds if the grader
			// returned no verdicts.
			if (feedback.per_concept && feedback.per_concept.length > 0) {
				this.applyVerdicts(feedback.per_concept, feedback.score);
			} else if (foundationIds.length > 0) {
				this.applyGlobalScoreFallback(foundationIds, feedback.score);
			}

			const feedbackMd = this.feedbackToMd(feedback);

			updatedContent = updatedContent.replace(
				entry.answerBlock,
				entry.answerBlock + "\n" + feedbackMd,
			);
			gradedCount++;
		}

		if (gradedCount > 0) {
			await this.app.vault.modify(this.sessionFile, updatedContent);
			// Repaint coverage so the freshly-updated mastery (and
			// ✓ marks for any concept that crossed the threshold)
			// is visible without forcing a next-round.
			if (this.coverageEl) this.renderCoveragePanel(this.coverageEl);
		}

		return gradedCount;
	}

	private parseItemsAndAnswers(content: string): Array<{
		title: string;
		bodyMd: string;
		solutionMd: string;
		userAnswer: string;
		answerBlock: string;
		alreadyGraded: boolean;
	}> {
		const results: Array<{
			title: string;
			bodyMd: string;
			solutionMd: string;
			userAnswer: string;
			answerBlock: string;
			alreadyGraded: boolean;
		}> = [];

		const itemPattern = /### \d+\. (.+)\n`[^`]+` \| `[^`]+`\n\n([\s\S]*?)(?=### \d+\.|## Round|---|\n$)/g;
		let match;

		while ((match = itemPattern.exec(content)) !== null) {
			const title = match[1].trim();
			const block = match[2];

			const answerCalloutRe = /#### Your Answer\n\n(> \[!quote\][^\n]*\n(?:> [^\n]*\n)*)/;
			const answerMatch = block.match(answerCalloutRe);
			if (!answerMatch) continue;

			const answerBlock = "#### Your Answer\n\n" + answerMatch[1].trimEnd();

			const answerLines = answerMatch[1].split("\n")
				.filter((l) => l.startsWith("> "))
				.map((l) => l.replace(/^> /, ""))
				.filter((l) => !l.startsWith("[!quote]"));
			const userAnswer = answerLines.join("\n").trim();

			const solutionRe = /> \[!success\][^\n]*\n((?:> [^\n]*\n)*)/;
			const solMatch = block.match(solutionRe);
			const solutionMd = solMatch
				? solMatch[1].split("\n").map((l) => l.replace(/^> /, "")).join("\n").trim()
				: "";

			const bodyEnd = block.indexOf("#### Your Answer");
			const bodyMd = bodyEnd > 0 ? block.slice(0, bodyEnd).trim() : "";

			const alreadyGraded = block.includes("> [!warning] Grading Feedback") || block.includes("> [!check] Grading Feedback");

			results.push({ title, bodyMd, solutionMd, userAnswer, answerBlock, alreadyGraded });
		}

		return results;
	}

	private feedbackToMd(fb: AnswerFeedback): string {
		const icon = fb.correct ? "check" : "warning";
		const label = fb.correct ? "Correct" : "Incorrect";
		const pct = (fb.score * 100).toFixed(0);
		const mastery = (fb.mastery_estimate * 100).toFixed(0);

		const lines: string[] = [];
		lines.push(`> [!${icon}] Grading Feedback — ${label} (${pct}%)`);

		if (fb.strengths.length > 0) {
			lines.push(`> **Strengths:**`);
			for (const s of fb.strengths) {
				lines.push(`> - ${s}`);
			}
		}
		if (fb.mistakes.length > 0) {
			lines.push(`> **Mistakes:**`);
			for (const m of fb.mistakes) {
				lines.push(`> - ${m}`);
			}
		}
		if (fb.suggestions) {
			lines.push(`>`);
			lines.push(`> **Suggestion:** ${fb.suggestions}`);
		}
		lines.push(`>`);
		lines.push(`> *Estimated mastery: ${mastery}%*`);
		lines.push(``);

		return lines.join("\n");
	}

	/**
	 * Pull all per-item grading scores out of the current session note.
	 * Pattern is the percentage embedded by ``feedbackToMd`` — keep the
	 * regex in sync with that emitter. Used to feed ``user_scores`` into
	 * the depth-aware scheduler so auto-advance can fire.
	 *
	 * Async because Obsidian's ``vault.adapter.readSync`` isn't a public
	 * API — the prior sync version always silently returned [], which
	 * meant ``user_scores`` was empty for every continue-round request
	 * and auto-advance never triggered.
	 */
	private async collectGradingScoresAsync(): Promise<number[]> {
		if (!this.sessionFile) return [];
		const content = await this.app.vault.read(this.sessionFile);
		if (!content) return [];

		const scores: number[] = [];
		const re = /> \[!(?:check|warning)\] Grading Feedback — (?:Correct|Incorrect) \((\d+)%\)/g;
		let match;
		while ((match = re.exec(content)) !== null) {
			scores.push(parseInt(match[1]) / 100);
		}
		return scores;
	}

	/** @deprecated Sync wrapper kept for backward compat — currently
	 * unused by the next-round path. Returns [] when the platform
	 * doesn't expose ``readSync`` (i.e. always on the public API). */
	private collectGradingScores(): number[] {
		const adapter = this.app.vault.adapter as unknown as {
			readSync?: (path: string) => string;
		};
		if (!this.sessionFile || typeof adapter.readSync !== "function") return [];
		const content = adapter.readSync(this.sessionFile.path);
		if (!content) return [];

		const scores: number[] = [];
		const re = /> \[!(?:check|warning)\] Grading Feedback — (?:Correct|Incorrect) \((\d+)%\)/g;
		let match;
		while ((match = re.exec(content)) !== null) {
			scores.push(parseInt(match[1]) / 100);
		}
		return scores;
	}

	/* ------------------------------------------------------------------ */
	/* Vault import                                                        */
	/* ------------------------------------------------------------------ */

	/** Stable concept id derived from the vault path so the same note
	 * always collapses to a single concept across imports. */
	private syntheticIdForPath(path: string): string {
		let h = 2166136261;
		for (let i = 0; i < path.length; i++) {
			h ^= path.charCodeAt(i);
			h = Math.imul(h, 16777619);
		}
		return `p${(h >>> 0).toString(36)}`;
	}

	/**
	 * Read a vault note and add it to ``this.concepts`` if not present.
	 * Returns ``{ added, conceptId }`` so callers can attribute the
	 * concept to the source row they're building.
	 */
	private async importFile(file: TFile): Promise<{ added: boolean; conceptId: string }> {
		const conceptId = this.syntheticIdForPath(file.path);
		if (this.concepts.find((c) => c.id === conceptId)) {
			return { added: false, conceptId };
		}

		const cache = this.app.metadataCache.getFileCache(file);
		const fm = cache?.frontmatter || {};
		const raw = await this.app.vault.cachedRead(file);
		const bodyMd = this.stripFrontmatter(raw);

		// ``depth`` lands in section MD frontmatter when the backend
		// graph builder runs (INGEST_BUILD_GRAPH=true). For non-graphed
		// notes (regular vault files, ungraphed papers) we default to 0
		// so the depth-aware scheduler treats them as a single root layer.
		const fmDepth = fm["depth"];
		const depth =
			typeof fmDepth === "number"
				? Math.max(0, Math.floor(fmDepth))
				: 0;

		this.concepts.push({
			id: conceptId,
			title: file.basename,
			body_md: bodyMd,
			content_type: (fm["content_type"] as string) || "markdown",
			user_mastery: typeof fm["mastery"] === "number" ? fm["mastery"] : 0.5,
			connected_concepts: this.extractLinkedTitles(file),
			depth,
		});
		return { added: true, conceptId };
	}

	private stripFrontmatter(raw: string): string {
		const match = raw.match(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/);
		return match ? raw.slice(match[0].length).trim() : raw.trim();
	}

	private extractLinkedTitles(file: TFile): string[] {
		const cache = this.app.metadataCache.getFileCache(file);
		if (!cache?.links) return [];
		return cache.links
			.map((l) => {
				const dest = this.app.metadataCache.getFirstLinkpathDest(l.link, file.path);
				return dest ? dest.basename : l.link;
			})
			.filter((v, i, arr) => arr.indexOf(v) === i);
	}

	/* ------------------------------------------------------------------ */
	/* Source-level adders (file / folder / pdf)                           */
	/* ------------------------------------------------------------------ */

	/** Add a single vault ``.md`` file as its own source row. */
	private async addVaultFileSource(file: TFile): Promise<void> {
		const sid = this.syntheticIdForPath(file.path);
		if (this.sources.find((s) => s.id === sid)) {
			new Notice(`Already added: ${file.basename}`);
			return;
		}
		const { added, conceptId } = await this.importFile(file);
		this.sources.push({
			id: sid,
			label: file.basename,
			kind: "file",
			meta: added ? "1 concept" : "duplicate",
			conceptIds: added ? [conceptId] : [],
		});
		new Notice(added ? `Added: ${file.basename}` : `Skipped (duplicate): ${file.basename}`);
	}

	/**
	 * Recursively import every ``.md`` under the given vault folder and
	 * attach all newly-added concept ids to a single folder source row.
	 */
	private async addFolderSource(folder: TFolder): Promise<void> {
		const sid = `folder:${folder.path || "/"}`;
		if (this.sources.find((s) => s.id === sid)) {
			new Notice(`Folder already added: ${folder.path || "/"}`);
			return;
		}

		const conceptIds: string[] = [];
		let total = 0;
		let skipped = 0;

		const walk = async (f: TFolder) => {
			for (const child of f.children) {
				if (child instanceof TFile && child.extension === "md") {
					total += 1;
					const { added, conceptId } = await this.importFile(child);
					if (added) conceptIds.push(conceptId);
					else skipped += 1;
				} else if (child instanceof TFolder) {
					await walk(child);
				}
			}
		};
		await walk(folder);

		this.sources.push({
			id: sid,
			label: folder.path || "/",
			kind: "folder",
			meta: skipped > 0
				? `${conceptIds.length}/${total} .md (${skipped} dupes)`
				: `${total} .md`,
			conceptIds,
		});
		new Notice(
			`Folder "${folder.path || "/"}": added ${conceptIds.length} · ` +
			`skipped ${skipped} (duplicates) · ${this.concepts.length} total concepts`
		);
	}

	/**
	 * Run the backend ingest pipeline for a native PDF ``File``, then
	 * locate the resulting ``sections/`` folder inside the vault and
	 * import every section as a concept under a single pdf source row.
	 */
	private async addPdfSource(pdfFile: File): Promise<void> {
		const userId = this.plugin.settings.vectorUserId.trim();
		if (!userId) {
			new Notice("Set 'Vector user id' in Knowledge Graph settings before uploading PDFs.");
			return;
		}

		const picked: PickedPdf = {
			name: pdfFile.name,
			readBytes: () => pdfFile.arrayBuffer(),
		};
		const resp = await ingestPdfFile(this.plugin, picked, userId);
		if (!resp) return; // ingestPdfFile already surfaced an error Notice

		const sid = `pdf:${resp.doc_id}`;
		if (this.sources.find((s) => s.id === sid)) {
			new Notice(`"${pdfFile.name}" already in sources list — nothing new imported.`);
			return;
		}

		// The backend writes the paper folder into the export path, which
		// defaults to ``<vault>/Papers``. We need a vault-relative path to
		// look up the TFolder through Obsidian's metadata cache.
		const base = vaultBasePath(this.app);
		const paperDirAbs = resp.paper_dir; // posix absolute
		let sectionsRelPath: string | null = null;
		if (base) {
			const baseNorm = base.replace(/\\/g, "/").replace(/\/$/, "");
			if (paperDirAbs.startsWith(baseNorm + "/")) {
				sectionsRelPath = normalizePath(
					`${paperDirAbs.slice(baseNorm.length + 1)}/sections`
				);
			}
		}

		const conceptIds: string[] = [];
		let sectionCount = 0;
		if (sectionsRelPath) {
			const folder = this.app.vault.getAbstractFileByPath(sectionsRelPath);
			if (folder instanceof TFolder) {
				for (const child of folder.children) {
					if (child instanceof TFile && child.extension === "md") {
						sectionCount += 1;
						const { added, conceptId } = await this.importFile(child);
						if (added) conceptIds.push(conceptId);
					}
				}
			}
		}

		this.sources.push({
			id: sid,
			label: pdfFile.name,
			kind: "pdf",
			meta: sectionCount > 0
				? `${conceptIds.length}/${sectionCount} sections`
				: `${resp.section_count} sections (not found in vault)`,
			conceptIds,
		});

		if (sectionCount === 0) {
			new Notice(
				`PDF ingested but no section MDs found under ` +
				`${sectionsRelPath ?? resp.paper_dir} — concepts not added.`,
				8000
			);
		}
	}

	/**
	 * Handle a batch of OS-picked files: route PDFs through the ingest
	 * pipeline, and add vault-resident ``.md`` files as file sources.
	 * OS-picked ``.md`` files that are NOT already in the vault are
	 * skipped with a hint — indexing them would require a copy into the
	 * vault and we don't silently touch the user's filesystem.
	 */
	private async handleUploadedFiles(files: File[]): Promise<void> {
		for (const file of files) {
			const name = file.name.toLowerCase();
			if (name.endsWith(".pdf")) {
				await this.addPdfSource(file);
			} else if (name.endsWith(".md")) {
				const vaultFile = this.findVaultFileByName(file.name);
				if (vaultFile) {
					await this.addVaultFileSource(vaultFile);
				} else {
					new Notice(
						`"${file.name}" is not in your vault — copy it in first, ` +
						`then add it via the search bar.`,
						8000
					);
				}
			} else {
				new Notice(`Skipped unsupported file: ${file.name}`);
			}
		}
	}

	/** Best-effort lookup: find a vault ``.md`` whose basename matches. */
	private findVaultFileByName(name: string): TFile | null {
		const base = name.replace(/\.md$/i, "");
		const hit = this.app.vault.getMarkdownFiles().find((f) => f.basename === base);
		return hit || null;
	}

	/* ------------------------------------------------------------------ */
	/* Resume / Continue helpers                                           */
	/* ------------------------------------------------------------------ */

	private async resumeFromFile(file: TFile): Promise<void> {
		this.sessionFile = file;
		const content = await this.app.vault.read(file);
		const fm = this.parseFrontmatterRaw(content);

		const sessionId = fm["session_id"] || file.basename;
		const difficulty = (fm["difficulty"] as Difficulty) || "medium";
		const status = fm["status"] || "in_progress";
		const roundCount = this.countRoundsInContent(content);

		this.session = {
			session_id: sessionId,
			rounds: Array.from({ length: roundCount }, (_, i) => ({
				round_number: i + 1,
				items: [],
				trajectories: [],
				reflector_feedback: [],
				grader_summary: null,
				eval_outcomes: [],
			})),
			current_difficulty: difficulty,
			status: status as "in_progress" | "completed",
			feasibility: "GENERATE",
		};

		await this.importConceptsFromContent(content);
	}

	private async importConceptsFromContent(content: string): Promise<void> {
		const topicsMatch = content.match(/\*\*Topics:\*\*\s*(.+)/);
		if (!topicsMatch) return;

		const wikilinks = topicsMatch[1].match(/\[\[([^\]]+)\]\]/g) || [];
		for (const wl of wikilinks) {
			const title = wl.replace(/\[\[|\]\]/g, "").trim();
			if (this.concepts.some((c) => c.title === title)) continue;
			const linked = this.app.metadataCache.getFirstLinkpathDest(title, "");
			if (linked instanceof TFile) {
				await this.importFile(linked);
			} else {
				this.concepts.push({
					id: `c_${title.toLowerCase().replace(/\s+/g, "-")}`,
					title,
					body_md: "",
					user_mastery: 0.5,
				});
			}
		}
	}

	private countRoundsInContent(content: string): number {
		const matches = content.match(/## Round \d+/g);
		return matches ? matches.length : 0;
	}

	private async countRoundsInFile(): Promise<number> {
		if (!this.sessionFile) return 0;
		const content = await this.app.vault.read(this.sessionFile);
		return this.countRoundsInContent(content);
	}

	private parseFrontmatterRaw(content: string): Record<string, string> {
		const m = content.match(/^---\r?\n([\s\S]*?)\r?\n---/);
		if (!m) return {};
		const result: Record<string, string> = {};
		for (const line of m[1].split("\n")) {
			const idx = line.indexOf(":");
			if (idx < 0) continue;
			const key = line.slice(0, idx).trim();
			let val = line.slice(idx + 1).trim();
			if (val.startsWith('"') && val.endsWith('"')) val = val.slice(1, -1);
			result[key] = val;
		}
		return result;
	}

	private async readFrontmatterField(key: string): Promise<string | undefined> {
		if (!this.sessionFile) return undefined;
		const content = await this.app.vault.read(this.sessionFile);
		const fm = this.parseFrontmatterRaw(content);
		return fm[key];
	}

	private async updateFrontmatterInFile(updates: Record<string, string | number>): Promise<void> {
		if (!this.sessionFile) return;
		let content = await this.app.vault.read(this.sessionFile);

		const fmMatch = content.match(/^---\r?\n([\s\S]*?)\r?\n---/);
		if (!fmMatch) return;

		let fmBlock = fmMatch[1];
		for (const [key, val] of Object.entries(updates)) {
			const lineRe = new RegExp(`^${key}:\\s*.*$`, "m");
			if (lineRe.test(fmBlock)) {
				fmBlock = fmBlock.replace(lineRe, `${key}: ${val}`);
			} else {
				fmBlock += `\n${key}: ${val}`;
			}
		}

		content = content.replace(fmMatch[0], `---\n${fmBlock}\n---`);
		await this.app.vault.modify(this.sessionFile, content);
	}

	private async appendRoundResult(round: RoundResult): Promise<void> {
		if (!this.sessionFile) return;
		const current = await this.app.vault.read(this.sessionFile);
		const md = this.roundToMd(round);
		await this.app.vault.modify(this.sessionFile, current + "\n" + md);

		const leaf = this.app.workspace.getLeaf(false);
		await leaf.openFile(this.sessionFile);
	}

	/* ------------------------------------------------------------------ */
	/* Sample Items                                                        */
	/* ------------------------------------------------------------------ */

	private renderSampleList(container: HTMLElement): void {
		container.empty();
		if (this.sampleItems.length === 0) {
			container.createEl("div", { cls: "kg-hint", text: "No sample items selected." });
			return;
		}
		this.sampleItems.forEach((sample, idx) => {
			const row = container.createDiv({ cls: "kg-concept-card" });
			const header = row.createDiv({ cls: "kg-concept-row" });

			// Image samples get a thumbnail so the user can see which
			// attachment maps to which row. Multi-image samples show
			// the first image only — click-to-preview could be added
			// later if there's demand.
			const imgs = this.sampleImages[sample.title];
			if (imgs && imgs.length) {
				const thumb = header.createEl("img", { cls: "kg-sample-thumb" });
				thumb.src = `data:${imgs[0].media_type};base64,${imgs[0].image_base64}`;
				thumb.alt = sample.title;
			}

			header.createEl("span", { text: `${sample.title}` });
			header.createEl("span", { cls: "kg-badge", text: `${sample.type} | ${sample.difficulty}` });

			// Status badge: pending / failed / analyzed. The analyzer runs
			// async so a freshly-added sample starts as "Analyzing…" and
			// transitions to a compact summary when the LLM returns.
			const status = this.sampleAnalysisStatus[sample.title];
			const analysis = this.sampleAnalyses[sample.title];
			if (status === "pending") {
				header.createEl("span", { cls: "kg-badge kg-badge-pending", text: "Analyzing…" });
			} else if (status === "failed") {
				const errMsg = this.sampleAnalysisErrors[sample.title] || "Unknown error";
				const failBadge = header.createEl("button", {
					cls: "kg-badge kg-badge-warn kg-badge-clickable",
					text: "Analysis failed — retry",
				});
				failBadge.setAttr("title", errMsg);
				failBadge.addEventListener("click", (e) => {
					e.stopPropagation();
					this.sampleAnalysisStatus[sample.title] = "pending";
					delete this.sampleAnalysisErrors[sample.title];
					if (this.sampleListEl) this.renderSampleList(this.sampleListEl);
					void this.triggerSampleAnalysis(sample);
				});
			} else if (analysis) {
				header.createEl("span", {
					cls: "kg-badge kg-badge-ok",
					text: `✓ ${analysis.estimated_difficulty}`,
				});
			}

			const removeBtn = header.createEl("button", { text: "×", cls: "kg-btn-remove" });
			removeBtn.addEventListener("click", () => {
				const removed = this.sampleItems.splice(idx, 1)[0];
				if (removed) {
					delete this.sampleAnalyses[removed.title];
					delete this.sampleAnalysisStatus[removed.title];
					delete this.sampleAnalysisErrors[removed.title];
					delete this.sampleImages[removed.title];
				}
				this.renderSampleList(container);
			});

			if (analysis) this.renderSampleAnalysis(row, analysis);
			else if (status === "failed") {
				const errMsg = this.sampleAnalysisErrors[sample.title];
				if (errMsg) {
					const errEl = row.createDiv({ cls: "kg-sample-analysis kg-sample-analysis-error" });
					errEl.createEl("div", { cls: "kg-sample-analysis-summary", text: "Analyzer error" });
					errEl.createEl("div", { cls: "kg-sample-analysis-issues", text: errMsg });
				}
			}
		});
	}

	/** Inline analysis card — summary + pedagogical notes + issues.
	 *  Rendered under a sample once the analyzer returns. Kept
	 *  lightweight (no collapsibles) so the user sees every signal in
	 *  one glance and can decide whether to keep the sample. */
	private renderSampleAnalysis(row: HTMLElement, analysis: SampleItemAnalysis): void {
		const card = row.createDiv({ cls: "kg-sample-analysis" });

		if (analysis.summary) {
			card.createEl("div", { cls: "kg-sample-analysis-summary", text: analysis.summary });
		}

		const meta: string[] = [];
		meta.push(`type: ${analysis.item_type_guess}`);
		meta.push(`difficulty: ${analysis.estimated_difficulty}`);
		if (analysis.concepts_covered.length) {
			meta.push(`covers: ${analysis.concepts_covered.slice(0, 4).join(", ")}${analysis.concepts_covered.length > 4 ? "…" : ""}`);
		}
		card.createEl("div", { cls: "kg-sample-analysis-meta", text: meta.join(" · ") });

		if (analysis.pedagogical_notes) {
			card.createEl("div", { cls: "kg-sample-analysis-notes", text: analysis.pedagogical_notes });
		}

		if (analysis.concepts_missing_from_catalog.length) {
			const missing = card.createDiv({ cls: "kg-sample-analysis-missing" });
			missing.createEl("strong", { text: "Not in your catalog: " });
			missing.createSpan({
				text: analysis.concepts_missing_from_catalog.slice(0, 4).join(", "),
			});
		}

		if (analysis.issues.length) {
			const issues = card.createDiv({ cls: "kg-sample-analysis-issues" });
			issues.createEl("strong", { text: "Issues: " });
			issues.createSpan({ text: analysis.issues.slice(0, 3).join("; ") });
		}
	}

	/** Route a batch of OS-picked files into the sample list.
	 *
	 *  * Images → base64-encoded, stored on ``sampleImages[title]`` so
	 *    the analyzer (and future multimodal Generator calls) see them.
	 *    The sample's ``body_md`` is a short pointer so the text-only
	 *    prompt still has something sensible to render.
	 *  * Markdown → parsed inline (same logic as ``importSampleItem``,
	 *    but from a browser ``File`` rather than a vault ``TFile``).
	 *  * Everything else → skipped with a Notice.
	 */
	private async importSampleUploadFiles(files: File[]): Promise<void> {
		let added = 0;
		for (const f of files) {
			const lower = f.name.toLowerCase();
			const isImage = f.type.startsWith("image/") || /\.(png|jpe?g|gif|webp)$/.test(lower);
			const isMd = f.type === "text/markdown" || lower.endsWith(".md");

			if (!isImage && !isMd) {
				new Notice(`Skipped ${f.name} — images or .md only here.`);
				continue;
			}

			const baseTitle = f.name.replace(/\.[^.]+$/, "");
			let title = baseTitle;
			// Dedupe: if two photos share a basename we suffix the second one
			// so they both show up instead of silently dropping the newer one.
			let n = 2;
			while (this.sampleItems.some((s) => s.title === title)) {
				title = `${baseTitle} (${n++})`;
			}

			try {
				if (isImage) {
					await this.addImageAsSample(f, title);
				} else {
					await this.addMarkdownAsSample(f, title);
				}
				added += 1;
			} catch (err) {
				console.warn("sample upload failed", f.name, err);
				new Notice(
					`Failed to add ${f.name}: ${err instanceof Error ? err.message : String(err)}`
				);
			}
		}
		if (this.sampleListEl) this.renderSampleList(this.sampleListEl);
		if (added) new Notice(`Added ${added} sample item(s).`);
	}

	private async addImageAsSample(file: File, title: string): Promise<void> {
		const b64 = await fileToBase64(file);
		const mediaType = file.type || "image/png";
		const image: ContextImage = { image_base64: b64, media_type: mediaType };

		const item: GeneratedItem = {
			type: "problem",
			title,
			body_md: `(image attached: ${file.name})`,
			answer_md: "",
			foundation_concept_ids: [],
			difficulty: "medium",
			explanation_md: "",
			analysis_notes: "",
		};
		this.sampleItems.push(item);
		this.sampleImages[title] = [image];
		this.sampleAnalysisStatus[title] = "pending";
		void this.triggerSampleAnalysis(item);
	}

	private async addMarkdownAsSample(file: File, title: string): Promise<void> {
		const raw = await file.text();
		const body = this.stripFrontmatter(raw);
		const questionMatch = body.match(/## Question\s*\n([\s\S]*?)(?=\n## Answer|\n##\s|$)/);
		const answerMatch = body.match(/## Answer\s*\n([\s\S]*?)(?=\n##\s|$)/);

		const item: GeneratedItem = {
			type: "problem",
			title,
			body_md: questionMatch ? questionMatch[1].trim() : body.trim(),
			answer_md: answerMatch ? answerMatch[1].trim() : "",
			foundation_concept_ids: [],
			difficulty: "medium",
			explanation_md: "",
			analysis_notes: "",
		};
		this.sampleItems.push(item);
		this.sampleAnalysisStatus[title] = "pending";
		void this.triggerSampleAnalysis(item);
	}

	private async importSampleItem(file: TFile): Promise<void> {
		const raw = await this.app.vault.cachedRead(file);
		const cache = this.app.metadataCache.getFileCache(file);
		const fm = cache?.frontmatter || {};
		const body = this.stripFrontmatter(raw);

		const questionMatch = body.match(/## Question\s*\n([\s\S]*?)(?=\n## Answer|\n##\s|$)/);
		const answerMatch = body.match(/## Answer\s*\n([\s\S]*?)(?=\n##\s|$)/);

		const item: GeneratedItem = {
			type: (fm["type"] as ItemType) || "problem",
			title: file.basename,
			body_md: questionMatch ? questionMatch[1].trim() : body.trim(),
			answer_md: answerMatch ? answerMatch[1].trim() : "",
			foundation_concept_ids: [],
			difficulty: (fm["difficulty"] as Difficulty) || "medium",
			explanation_md: "",
			analysis_notes: "",
		};

		const alreadyPresent = this.sampleItems.some((s) => s.title === item.title);
		if (alreadyPresent) return;

		this.sampleItems.push(item);
		this.sampleAnalysisStatus[item.title] = "pending";

		void this.triggerSampleAnalysis(item);
	}

	/** Fire-and-forget analyzer call. Updates ``this.sampleAnalyses`` and
	 *  refreshes the sample list when done. Kept separate from
	 *  ``importSampleItem`` so the upload completes instantly and the
	 *  analysis badge transitions in later (analyzer can take 5–15s). */
	private async triggerSampleAnalysis(item: GeneratedItem): Promise<void> {
		try {
			// Send the *current* concept list as catalog so the analyzer
			// can tell the user which of their selected concepts the
			// sample actually exercises (vs. things outside scope).
			const catalog: ConceptRef[] = this.concepts.map((c) => ({ id: c.id, title: c.title }));

			// Images: per-sample uploads take priority (image samples
			// are useless without their image). For text-only samples
			// we fall back to the session-wide context images so a
			// user who pre-attached a figure still gets it analyzed.
			const perSample = this.sampleImages[item.title] || [];
			const images = perSample.length
				? perSample
				: this.contextImages.length
				? this.contextImages
				: undefined;

			const analysis = await this.plugin.api.analyzeSample({
				title: item.title,
				body_md: item.body_md,
				answer_md: item.answer_md,
				concept_catalog: catalog,
				context_images: images,
			});
			this.sampleAnalyses[item.title] = analysis;
			delete this.sampleAnalysisStatus[item.title];

			// Persist the analysis back onto the sample so it ships to
			// the Generator on the next request. We keep the human
			// summary on the plugin side and serialize a compact
			// prompt-ready blob into ``analysis_notes``.
			const current = this.sampleItems.find((s) => s.title === item.title);
			if (current) {
				current.analysis_notes = this.formatAnalysisForPrompt(analysis);
			}
		} catch (err) {
			console.warn("sample analyzer failed", err);
			this.sampleAnalysisStatus[item.title] = "failed";
			const msg = err instanceof Error ? err.message : String(err);
			this.sampleAnalysisErrors[item.title] = msg;
		} finally {
			if (this.sampleListEl) this.renderSampleList(this.sampleListEl);
		}
	}

	/** Serialize a ``SampleItemAnalysis`` into a compact text blob the
	 *  Generator prompt ingests via ``analysis_notes``. Mirrors the
	 *  backend ``format_analysis_for_prompt`` so the prompt payload
	 *  looks the same whether the analysis was produced here or on the
	 *  server (future: server-side caching). */
	/** Union session-wide context images with per-sample uploads
	 *  (image-as-sample), deduped by base64 so an image attached both
	 *  ways doesn't double-bill tokens. Used by the Generator requests
	 *  so the LLM can actually see image samples, not just their
	 *  placeholder titles. */
	private collectAllImagesForGenerator(): ContextImage[] {
		const seen = new Set<string>();
		const out: ContextImage[] = [];
		const push = (img: ContextImage) => {
			const key = `${img.media_type}|${img.image_base64.slice(0, 64)}|${img.image_base64.length}`;
			if (seen.has(key)) return;
			seen.add(key);
			out.push(img);
		};
		for (const img of this.contextImages) push(img);
		for (const sample of this.sampleItems) {
			for (const img of this.sampleImages[sample.title] || []) push(img);
		}
		return out;
	}

	private formatAnalysisForPrompt(a: SampleItemAnalysis): string {
		const parts: string[] = [];
		if (a.summary) parts.push(`Summary: ${a.summary}`);
		if (a.estimated_difficulty) parts.push(`Estimated difficulty: ${a.estimated_difficulty}`);
		if (a.concepts_covered?.length) parts.push(`Concepts exercised: ${a.concepts_covered.join(", ")}`);
		if (a.pedagogical_notes) parts.push(`Pedagogical notes: ${a.pedagogical_notes}`);
		if (a.strengths?.length) parts.push(`Strengths: ${a.strengths.join("; ")}`);
		if (a.issues?.length) parts.push(`Known issues: ${a.issues.join("; ")}`);
		return parts.join("\n");
	}

	private async createSampleItemNote(): Promise<void> {
		const dir = "SampleItems";
		if (!this.app.vault.getAbstractFileByPath(dir)) {
			await this.app.vault.createFolder(dir);
		}

		const name = `SampleItems/Sample ${Date.now()}.md`;
		const template = `---\ntype: problem\ndifficulty: medium\n---\n\n## Question\n(paste your question here)\n\n## Answer\n(paste the answer or leave blank)\n`;

		const file = await this.app.vault.create(name, template);
		const leaf = this.app.workspace.getLeaf(false);
		await leaf.openFile(file);
		new Notice("Sample item created — edit it, then add it from the picker.");
	}

	/* ------------------------------------------------------------------ */
	/* Context images                                                      */
	/* ------------------------------------------------------------------ */

	private renderImageList(container: HTMLElement): void {
		container.empty();
		if (this.contextImages.length === 0) {
			container.createEl("div", { cls: "kg-hint", text: "No images attached." });
			return;
		}
		this.contextImages.forEach((img, idx) => {
			const row = container.createDiv({ cls: "kg-concept-row" });
			const thumb = row.createEl("img", { cls: "kg-image-thumb" });
			thumb.src = `data:${img.media_type};base64,${img.image_base64}`;
			row.createEl("span", { text: `Image ${idx + 1} (${img.media_type})` });
			const removeBtn = row.createEl("button", { text: "×", cls: "kg-btn-remove" });
			removeBtn.addEventListener("click", () => {
				this.contextImages.splice(idx, 1);
				this.renderImageList(container);
			});
		});
	}

	/* ------------------------------------------------------------------ */
	/* Helpers                                                             */
	/* ------------------------------------------------------------------ */

	private addBackButton(container: HTMLElement): void {
		const backBtn = container.createEl("button", { text: "New Session", cls: "kg-btn kg-btn-secondary" });
		backBtn.addEventListener("click", () => {
			this.session = null;
			this.sessionFile = null;
			this.sampleItems = [];
			this.sampleAnalyses = {};
			this.sampleAnalysisStatus = {};
			this.sampleAnalysisErrors = {};
			this.sampleImages = {};
			this.contextImages = [];
			// Coverage and focus depth are session-scoped — reset them so
			// a fresh session starts with a clean matrix.
			this.coverage = {};
			this.focusDepth = 0;
			this.mastery = {};
			this.lastRoundItems = [];
			this.renderForm();
		});
	}

	private createSelect(parent: HTMLElement, label: string, options: [string, string][]): HTMLSelectElement {
		const field = parent.createDiv({ cls: "kg-field" });
		field.createEl("label", { text: label });
		const select = field.createEl("select", { cls: "kg-select" });
		for (const [value, text] of options) {
			select.createEl("option", { text, attr: { value } });
		}
		return select;
	}

	private createNumberInput(parent: HTMLElement, label: string, defaultVal: number, min: number, max: number): HTMLInputElement {
		const field = parent.createDiv({ cls: "kg-field" });
		field.createEl("label", { text: label });
		const input = field.createEl("input", {
			cls: "kg-input kg-input-narrow",
			attr: { type: "number", min: String(min), max: String(max), value: String(defaultVal) },
		});
		return input;
	}
}
