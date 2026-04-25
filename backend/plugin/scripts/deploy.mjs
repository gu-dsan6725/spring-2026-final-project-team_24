#!/usr/bin/env node
/*
 * Copy the built plugin artifacts (main.js, manifest.json, styles.css) into
 * every Obsidian vault's plugin folder registered in the user's obsidian.json,
 * or into a single vault specified by the OBSIDIAN_VAULT_PLUGIN_DIR env var.
 *
 * Usage:
 *   npm run deploy
 *   OBSIDIAN_VAULT_PLUGIN_DIR="D:/AI/Obsidian/self" npm run deploy
 *   OBSIDIAN_VAULT_PLUGIN_DIR="D:/AI/Obsidian/self/.obsidian/plugins/knowledge-graph" npm run deploy
 *
 * The env var may point to the vault root OR the plugin folder directly;
 * we resolve ``.obsidian/plugins/<manifest.id>`` if it looks like a vault root.
 */

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const PLUGIN_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const ARTIFACTS = ["main.js", "manifest.json", "styles.css"];

function readManifestId() {
	const raw = fs.readFileSync(path.join(PLUGIN_ROOT, "manifest.json"), "utf-8");
	return JSON.parse(raw).id;
}

function obsidianConfigPath() {
	// Windows: %APPDATA%\obsidian\obsidian.json
	// Linux:   ~/.config/obsidian/obsidian.json
	// macOS:   ~/Library/Application Support/obsidian/obsidian.json
	if (process.platform === "win32" && process.env.APPDATA) {
		return path.join(process.env.APPDATA, "obsidian", "obsidian.json");
	}
	if (process.platform === "darwin") {
		return path.join(os.homedir(), "Library", "Application Support", "obsidian", "obsidian.json");
	}
	return path.join(os.homedir(), ".config", "obsidian", "obsidian.json");
}

function discoverVaults(pluginId) {
	const envTarget = process.env.OBSIDIAN_VAULT_PLUGIN_DIR;
	if (envTarget) {
		const resolved = path.resolve(envTarget);
		const asPluginDir = fs.existsSync(path.join(resolved, "manifest.json"));
		const asVaultRoot = fs.existsSync(path.join(resolved, ".obsidian"));
		if (asPluginDir) return [resolved];
		if (asVaultRoot) return [path.join(resolved, ".obsidian", "plugins", pluginId)];
		return [path.join(resolved, pluginId)];
	}
	const cfg = obsidianConfigPath();
	if (!fs.existsSync(cfg)) {
		throw new Error(
			`No OBSIDIAN_VAULT_PLUGIN_DIR set and Obsidian config not found at ${cfg}. ` +
				`Open Obsidian once to create it, or set OBSIDIAN_VAULT_PLUGIN_DIR.`
		);
	}
	const parsed = JSON.parse(fs.readFileSync(cfg, "utf-8"));
	const vaults = parsed.vaults || {};
	const paths = Object.values(vaults).map((v) => v.path).filter(Boolean);
	if (paths.length === 0) {
		throw new Error(`No vaults found in ${cfg}.`);
	}
	return paths.map((p) => path.join(p, ".obsidian", "plugins", pluginId));
}

function deployTo(target) {
	fs.mkdirSync(target, { recursive: true });
	for (const f of ARTIFACTS) {
		const src = path.join(PLUGIN_ROOT, f);
		if (!fs.existsSync(src)) {
			console.warn(`[deploy] skip missing ${f}`);
			continue;
		}
		const dst = path.join(target, f);
		fs.copyFileSync(src, dst);
	}
	console.log(`[deploy] ✓ ${target}`);
}

function main() {
	const pluginId = readManifestId();
	const targets = discoverVaults(pluginId);
	for (const t of targets) deployTo(t);
	console.log(`[deploy] done — ${targets.length} vault${targets.length === 1 ? "" : "s"} updated.`);
	console.log("[deploy] Reload Obsidian (Ctrl+P → 'Reload app without saving') to pick up changes.");
}

main();
