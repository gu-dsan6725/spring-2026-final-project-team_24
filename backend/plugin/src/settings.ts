import { App, PluginSettingTab, Setting } from "obsidian";
import type KnowledgeGraphPlugin from "./main";

export interface KnowledgeGraphSettings {
	backendUrl: string;
	authToken: string;
	/** Pinecone namespace segment ``user_{vectorUserId}_concepts`` — must match index/search API calls. */
	vectorUserId: string;
	/**
	 * Absolute filesystem path where ingested papers are mirrored by the backend
	 * (e.g. an Obsidian vault root or a ``Papers/`` subfolder inside one).
	 * Leave blank to default to ``<current vault>/Papers``.
	 */
	paperExportPath: string;
}

export const DEFAULT_SETTINGS: KnowledgeGraphSettings = {
	backendUrl: "http://localhost:8000",
	authToken: "",
	vectorUserId: "",
	paperExportPath: "",
};

export class KnowledgeGraphSettingTab extends PluginSettingTab {
	plugin: KnowledgeGraphPlugin;

	constructor(app: App, plugin: KnowledgeGraphPlugin) {
		super(app, plugin);
		this.plugin = plugin;
	}

	display(): void {
		const { containerEl } = this;
		containerEl.empty();

		new Setting(containerEl)
			.setName("Backend URL")
			.setDesc("URL of the FastAPI backend server.")
			.addText((text) =>
				text
					.setPlaceholder("http://localhost:8000")
					.setValue(this.plugin.settings.backendUrl)
					.onChange(async (value) => {
						this.plugin.settings.backendUrl = value.trim().replace(/\/+$/, "");
						await this.plugin.saveSettings();
						this.plugin.api.updateConfig(this.plugin.settings.backendUrl, this.plugin.settings.authToken);
					})
			);

		new Setting(containerEl)
			.setName("Auth Token")
			.setDesc("JWT token for backend authentication (leave empty if auth is not enabled).")
			.addText((text) =>
				text
					.setPlaceholder("eyJhbGciOi...")
					.setValue(this.plugin.settings.authToken)
					.onChange(async (value) => {
						this.plugin.settings.authToken = value.trim();
						await this.plugin.saveSettings();
						this.plugin.api.updateConfig(this.plugin.settings.backendUrl, this.plugin.settings.authToken);
					})
			);

		new Setting(containerEl)
			.setName("Vector user id")
			.setDesc(
				"Stable id for Pinecone namespaces (user_{id}_concepts). Use the same value when calling index/search from the Item Generator."
			)
			.addText((text) =>
				text
					.setPlaceholder("e.g. your name or vault slug")
					.setValue(this.plugin.settings.vectorUserId)
					.onChange(async (value) => {
						this.plugin.settings.vectorUserId = value.trim();
						await this.plugin.saveSettings();
					})
			);

		new Setting(containerEl)
			.setName("Paper export path")
			.setDesc(
				"Absolute filesystem path the backend mirrors ingested papers into. " +
					"Leave blank to default to '<current vault>/Papers'. " +
					"Each paper produces <path>/<stem>/{sections,plots,.meta,auto}."
			)
			.addText((text) =>
				text
					.setPlaceholder("e.g. C:\\Users\\me\\Obsidian\\Vault\\Papers")
					.setValue(this.plugin.settings.paperExportPath)
					.onChange(async (value) => {
						this.plugin.settings.paperExportPath = value.trim();
						await this.plugin.saveSettings();
					})
			);
	}
}
