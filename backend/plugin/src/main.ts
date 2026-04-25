import { Plugin, WorkspaceLeaf } from "obsidian";
import { BackendAPI } from "./api";
import {
	runIngestPaperCommand,
	runSearchPapersCommand,
} from "./commands/paper_ingest";
import {
	DEFAULT_SETTINGS,
	KnowledgeGraphSettingTab,
	type KnowledgeGraphSettings,
} from "./settings";
import { ItemGeneratorView, VIEW_TYPE_ITEM_GENERATOR } from "./views/ItemView";

export default class KnowledgeGraphPlugin extends Plugin {
	settings: KnowledgeGraphSettings = DEFAULT_SETTINGS;
	api: BackendAPI = new BackendAPI(DEFAULT_SETTINGS.backendUrl, DEFAULT_SETTINGS.authToken);

	async onload(): Promise<void> {
		await this.loadSettings();

		this.registerView(VIEW_TYPE_ITEM_GENERATOR, (leaf) => new ItemGeneratorView(leaf, this));

		this.addRibbonIcon("wand-sparkles", "Open Item Generator", () => {
			this.activateView();
		});

		this.addCommand({
			id: "open-item-generator",
			name: "Open Item Generator",
			callback: () => this.activateView(),
		});

		this.addCommand({
			id: "ingest-pdf-as-paper",
			name: "Ingest PDF as paper (MinerU + embed)",
			callback: () => runIngestPaperCommand(this),
		});

		this.addCommand({
			id: "search-indexed-papers",
			name: "Search indexed papers",
			callback: () => runSearchPapersCommand(this),
		});

		this.addSettingTab(new KnowledgeGraphSettingTab(this.app, this));
	}

	async onunload(): Promise<void> {
		this.app.workspace.detachLeavesOfType(VIEW_TYPE_ITEM_GENERATOR);
	}

	async loadSettings(): Promise<void> {
		this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
		this.api.updateConfig(this.settings.backendUrl, this.settings.authToken);
	}

	async saveSettings(): Promise<void> {
		await this.saveData(this.settings);
		this.api.updateConfig(this.settings.backendUrl, this.settings.authToken);
	}

	private async activateView(): Promise<void> {
		const existing = this.app.workspace.getLeavesOfType(VIEW_TYPE_ITEM_GENERATOR);
		if (existing.length > 0) {
			this.app.workspace.revealLeaf(existing[0]);
			return;
		}

		const leaf: WorkspaceLeaf = this.app.workspace.getRightLeaf(false)!;
		await leaf.setViewState({
			type: VIEW_TYPE_ITEM_GENERATOR,
			active: true,
		});
		this.app.workspace.revealLeaf(leaf);
	}
}
