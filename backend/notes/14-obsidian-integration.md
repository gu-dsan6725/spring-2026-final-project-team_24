# Obsidian Plugin Integration

The frontend is an **Obsidian plugin** — a TypeScript thin client that renders data from the Python FastAPI backend. Obsidian provides the editor, file system, and plugin ecosystem; our plugin adds knowledge graph, traversal, item, landscape, and publish capabilities.

## Architecture

```
┌──────────────────────────────────────┐
│  Obsidian Desktop App                │
│  ┌────────────────────────────────┐  │
│  │  Our Plugin (plugin/)          │  │
│  │  ├── GraphView (Cytoscape.js)  │  │
│  │  ├── TraversalView             │  │
│  │  ├── ItemView                  │  │
│  │  ├── LandscapeView             │  │
│  │  ├── DataEntityView            │  │
│  │  └── Publish Command           │  │
│  └──────────┬─────────────────────┘  │
│             │ requestUrl()           │
│  ┌──────────┼─────────────────────┐  │
│  │  Community Plugins             │  │
│  │  ├── obsidian-spaced-repetition│  │
│  │  ├── Relay (CRDT collab)       │  │
│  │  └── Extended Graph            │  │
│  └────────────────────────────────┘  │
└──────────────┬───────────────────────┘
               │ HTTP (localhost:8000)
┌──────────────▼───────────────────────┐
│  FastAPI Backend (app/)              │
│  ├── /api/v1/concepts                │
│  ├── /api/v1/edges                   │
│  ├── /api/v1/items                   │
│  ├── /api/v1/groups                  │
│  ├── /api/v1/data-entities           │
│  ├── /api/v1/traversal              │
│  └── /api/v1/ai                      │
└──────────────────────────────────────┘
```

## Plugin Directory Structure

```
plugin/
├── manifest.json          # Obsidian plugin metadata (id, name, version, minAppVersion)
├── package.json           # npm deps: obsidian, cytoscape, esbuild
├── tsconfig.json          # strict, es2018, CommonJS
├── esbuild.config.mjs     # bundle → main.js
├── styles.css             # panel layout styles
└── src/
    ├── main.ts            # extends Plugin — registers views, commands, settings
    ├── settings.ts        # PluginSettingTab — backend URL, auth token, user/group ID
    ├── api.ts             # BackendAPI class — typed requestUrl() wrappers
    ├── types.ts           # TypeScript interfaces matching backend Pydantic schemas
    ├── views/
    │   ├── GraphView.ts       # Cytoscape.js knowledge graph panel
    │   ├── TraversalView.ts   # Study mode — outer fringe panel
    │   ├── ItemView.ts        # Item viewer with backend-tracked mastery
    │   ├── LandscapeView.ts   # Group landscape browser
    │   └── DataEntityView.ts  # Data entity detail + entries
    └── commands/
        └── publish.ts         # Three-mode publish: save, index, share
```

## Custom Components

### GraphView

Renders the user's personal knowledge graph using Cytoscape.js. Nodes are concepts, edges are typed connections fetched from the backend. Tap a node to open its markdown note or navigate to related items.

### TraversalView

Study mode panel showing the outer fringe — the set of concepts the user can learn next based on their current knowledge state. Fetched from `/api/v1/traversal/fringe`. Selecting a concept shows its foundation items.

### ItemView

Displays items (problems, definitions, exercises) with interactive answer submission. Mastery tracking lives on the backend — the plugin sends attempt results and renders updated status.

Current ItemView implementation also includes semantic retrieval helpers:
- Index current concept set to Pinecone (`/api/v1/vectors/concepts/index`)
- Index vault notes with YAML `id` + `vault_path` metadata
- Search by meaning and add hits into foundation concepts
- One-click `Search + Add + Generate` flow
- `Clear vector namespace` reset (`/api/v1/vectors/concepts/clear`) for stale mapping recovery

### LandscapeView

Read-only browser for the group's merged canonical landscape. Shows canonical nodes with member perspectives. Tap to inspect or fork a concept into the user's personal graph.

### DataEntityView

Detail view for a data entity — shows source metadata, description, and the appendable entry log. Users can append new entries (ML metrics, pipeline results) directly from this panel.

### Publish Command

The publish command is a **core custom component** (not replaceable by community plugins) because it implements our privacy-preserving ingest pipeline:

| Mode | What happens | Visibility |
|---|---|---|
| **Save** | Note stays in vault only | Private — no backend interaction |
| **Index** | Embed + index in user's private Pinecone namespace | Group can search by concept count only, not content |
| **Share** | Push to group landscape | Visible to group members, triggers canonical merge pipeline |

This three-mode workflow is central to the platform's privacy model: a user's private notes are never exposed to the group unless explicitly shared. The "index" mode enables privacy-preserving discoverability — group members can see that *someone* has a concept about topic X, but cannot read the content.

## Community Plugin Complements

These existing Obsidian plugins handle functionality we don't need to build:

| Plugin | What it does | Why we don't rebuild it |
|---|---|---|
| **obsidian-spaced-repetition** | Local flashcard review with SM-2 scheduling | Handles local-only spaced repetition. Our backend tracks mastery separately for items that span multiple concepts. |
| **Relay** | Real-time collaborative editing via CRDT | Handles multi-user co-editing of notes. We focus on async knowledge sharing via the landscape model. |
| **Extended Graph** | Enhanced vault-link graph visualization | Supplements our backend-powered GraphView with local vault link exploration. |

## Backend Requirements

### CORS Middleware

The FastAPI backend must allow requests from Obsidian's desktop app. Add CORS middleware to `app/main.py`:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["app://obsidian.md"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Auth

Plugin settings store an auth token. The backend validates it via the existing JWT middleware on every request. Token obtained via a login endpoint (`POST /api/v1/auth/login`).

## Privacy Model

The platform's privacy model is enforced at the backend level:

1. **Personal graph** — fully private. Only the owning user can read/write.
2. **Indexed concepts** — embedding stored in user's private Pinecone namespace. Group search returns existence counts only (e.g., "3 members have a concept about PCA"), never content.
3. **Shared concepts** — pushed to the group landscape. Visible to all group members. The canonical merge pipeline decides whether to merge with existing canonical nodes or keep as a distinct perspective.

The Obsidian publish command maps directly to these three levels.

## Build & Development

```bash
cd plugin
npm install
npm run dev     # watch mode — rebuilds main.js on save
npm run build   # production build
```

Copy `main.js`, `manifest.json`, and `styles.css` into the Obsidian vault's `.obsidian/plugins/knowledge-graph/` directory to install.

## MVP Scope

### Build (custom)

- [x] Plugin scaffold (manifest, build config, settings)
- [x] API client (`api.ts` — typed wrappers for items/extraction/vector endpoints used by ItemView)
- [ ] GraphView (Cytoscape.js personal graph)
- [ ] TraversalView (outer fringe study mode)
- [x] ItemView (generation, session resume, answer grading, extraction import, semantic search/index helpers)
- [ ] LandscapeView (group landscape browser)
- [ ] DataEntityView (data entity detail + entry appending)
- [ ] Publish command (save / index / share)

### Skip (community plugins suffice)

- Local flashcard review → obsidian-spaced-repetition
- Real-time collaborative editing → Relay
- Vault-link graph → Extended Graph

### Deferred

- Dive visualization (experimental concept — deferred)
- Chart rendering for data entity statistical overlays
- Handwriting submission panel
- MCP tool integration panel
