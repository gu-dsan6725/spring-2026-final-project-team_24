import {
	App,
	Notice,
	SuggestModal,
	TFile,
	normalizePath,
} from "obsidian";
import type KnowledgeGraphPlugin from "../main";
import type { DocChunkSearchHit, IngestPaperResponse } from "../types";

/**
 * Chunked ArrayBuffer → base64. Avoids the stack-overflow that
 * ``String.fromCharCode(...new Uint8Array(buf))`` causes for large PDFs.
 */
function arrayBufferToBase64(buf: ArrayBuffer): string {
	const bytes = new Uint8Array(buf);
	let binary = "";
	const chunk = 0x8000; // 32 KiB
	for (let i = 0; i < bytes.length; i += chunk) {
		const slice = bytes.subarray(i, i + chunk);
		binary += String.fromCharCode.apply(
			null,
			Array.from(slice) as unknown as number[]
		);
	}
	return btoa(binary);
}

/**
 * Resolve the absolute filesystem path of the current vault's root, if the
 * adapter exposes it (Electron/desktop does; mobile does not).
 */
export function vaultBasePath(app: App): string | null {
	const adapter = app.vault.adapter as unknown as { basePath?: string; getBasePath?: () => string };
	if (typeof adapter.getBasePath === "function") {
		try {
			return adapter.getBasePath();
		} catch {
			// fallthrough
		}
	}
	if (typeof adapter.basePath === "string" && adapter.basePath) {
		return adapter.basePath;
	}
	return null;
}

/** Join a vault-root path with a subfolder in a cross-platform way. */
function joinPath(root: string, sub: string): string {
	const trimmed = root.replace(/[\\/]+$/, "");
	if (!sub) return trimmed;
	const sep = trimmed.includes("\\") && !trimmed.includes("/") ? "\\" : "/";
	return `${trimmed}${sep}${sub.replace(/^[\\/]+/, "")}`;
}

/**
 * Lightweight shape we pass into ``ingestPdfFile``. Abstracts over
 * both vault-local ``TFile`` and OS-picker ``File`` sources.
 */
export interface PickedPdf {
	name: string;
	readBytes(): Promise<ArrayBuffer>;
}

/**
 * Trigger the browser/Electron native OS file-picker and resolve with the
 * selected PDF (or ``null`` if the user cancelled). Uses a transient
 * ``<input type="file">`` element so we get platform-native folder
 * navigation, drive letters, shortcuts, etc.
 */
function pickPdfFromOS(): Promise<File | null> {
	return new Promise((resolve) => {
		const input = document.createElement("input");
		input.type = "file";
		input.accept = "application/pdf,.pdf";
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
				const file = input.files && input.files.length > 0 ? input.files[0] : null;
				cleanup();
				resolve(file);
			},
			{ once: true }
		);

		// ``cancel`` fires in Chromium when the user dismisses the dialog.
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

/** Debounced full-text search modal over /vectors/docs/search. */
class DocChunkSearchModal extends SuggestModal<DocChunkSearchHit> {
	private debounceTimer: number | null = null;
	private lastQuery = "";
	private pending: Promise<DocChunkSearchHit[]> | null = null;

	constructor(
		app: App,
		private readonly plugin: KnowledgeGraphPlugin,
		private readonly userId: string
	) {
		super(app);
		this.setPlaceholder("Search your indexed papers…");
		this.emptyStateText = "No matches yet — try a different phrase.";
	}

	async getSuggestions(query: string): Promise<DocChunkSearchHit[]> {
		const q = query.trim();
		if (!q) return [];
		this.lastQuery = q;

		return new Promise((resolve) => {
			if (this.debounceTimer !== null) {
				window.clearTimeout(this.debounceTimer);
			}
			this.debounceTimer = window.setTimeout(async () => {
				if (q !== this.lastQuery) {
					resolve([]);
					return;
				}
				try {
					const resp = await this.plugin.api.searchDocChunks(
						this.userId,
						q,
						15
					);
					resolve(resp.hits);
				} catch (err) {
					new Notice(
						`Search failed: ${
							err instanceof Error ? err.message : String(err)
						}`
					);
					resolve([]);
				}
			}, 250);
		});
	}

	renderSuggestion(hit: DocChunkSearchHit, el: HTMLElement): void {
		const md = hit.metadata || {};
		const title = (md["section_title"] as string) || hit.section_id || hit.vector_id;
		const doc = (md["doc_id"] as string) || hit.doc_id || "";
		const snippet = (md["preview"] as string) || "";

		el.createEl("div", { text: title, cls: "kg-docchunk-title" });
		const sub = el.createEl("div", { cls: "kg-docchunk-sub" });
		sub.setText(
			`score ${hit.score.toFixed(3)} · doc ${doc.slice(0, 8) || "?"} · chunk #${hit.chunk_index ?? "?"}`
		);
		if (snippet) {
			el.createEl("div", { text: snippet, cls: "kg-docchunk-preview" });
		}
	}

	onChooseSuggestion(hit: DocChunkSearchHit): void {
		const md = hit.metadata || {};
		const vaultPath = (md["vault_path"] as string) || "";
		if (vaultPath) {
			const normalized = normalizePath(vaultPath);
			const file = this.app.vault.getAbstractFileByPath(normalized);
			if (file instanceof TFile) {
				this.app.workspace.getLeaf(false).openFile(file);
				return;
			}
		}
		new Notice(
			`Hit: ${hit.vector_id} (score ${hit.score.toFixed(3)}) — no matching file in vault`
		);
	}
}

// ---------------------------------------------------------------------------
// Public entry points — invoked from main.ts
// ---------------------------------------------------------------------------

export async function runIngestPaperCommand(plugin: KnowledgeGraphPlugin): Promise<void> {
	const userId = plugin.settings.vectorUserId.trim();
	if (!userId) {
		new Notice(
			"Set 'Vector user id' in Knowledge Graph settings before ingesting papers."
		);
		return;
	}

	const file = await pickPdfFromOS();
	if (!file) return; // user cancelled

	const picked: PickedPdf = {
		name: file.name,
		readBytes: () => file.arrayBuffer(),
	};
	await ingestPdfFile(plugin, picked, userId);
}

/**
 * Core ingest routine. Reads a picked PDF, base64s it, POSTs to the
 * backend, and surfaces a status Notice. Returns the raw response so
 * callers (like the Item Generator) can reach into the generated paper
 * folder to import section MDs as concepts.
 */
export async function ingestPdfFile(
	plugin: KnowledgeGraphPlugin,
	file: PickedPdf,
	userId: string
): Promise<IngestPaperResponse | null> {
	const app = plugin.app;
	const progress = new Notice(`Ingesting ${file.name}… reading PDF`, 0);

	try {
		const buf = await file.readBytes();
		progress.setMessage(
			`Ingesting ${file.name}… uploading (${(buf.byteLength / 1024 / 1024).toFixed(1)} MB)`
		);
		const b64 = arrayBufferToBase64(buf);

		// Default export_path to <vault>/Papers unless user set one explicitly.
		let exportPath = plugin.settings.paperExportPath.trim();
		if (!exportPath) {
			const base = vaultBasePath(app);
			if (base) exportPath = joinPath(base, "Papers");
		}

		progress.setMessage(`Ingesting ${file.name}… extracting (this may take 30–120s)`);
		const resp: IngestPaperResponse = await plugin.api.ingestPaper({
			user_id: userId,
			pdf_base64: b64,
			filename: file.name,
			export_path: exportPath || null,
		});

		progress.hide();

		const exported = resp.exported_to
			? ` → ${resp.exported_to}`
			: "";
		const indexed = resp.pinecone_indexed
			? ` · ${resp.pinecone_indexed} vectors indexed`
			: "";

		if (resp.already_ingested) {
			new Notice(
				`"${file.name}" is already ingested — reusing existing paper folder ` +
					`(${resp.section_count} sections${exported}). ` +
					`Delete the folder from your vault to force re-ingest.`,
				10000
			);
		} else {
			new Notice(
				`Ingested ${file.name}: ${resp.section_count} sections, ` +
					`${resp.chunk_count} chunks${indexed}${exported}`,
				8000
			);
		}
		return resp;
	} catch (err) {
		progress.hide();
		const msg = err instanceof Error ? err.message : String(err);
		new Notice(`Paper ingestion failed: ${msg}`, 12000);
		console.error("[knowledge-graph] ingestPaper failed", err);
		return null;
	}
}

export function runSearchPapersCommand(plugin: KnowledgeGraphPlugin): void {
	const userId = plugin.settings.vectorUserId.trim();
	if (!userId) {
		new Notice("Set 'Vector user id' in Knowledge Graph settings before searching papers.");
		return;
	}
	new DocChunkSearchModal(plugin.app, plugin, userId).open();
}
