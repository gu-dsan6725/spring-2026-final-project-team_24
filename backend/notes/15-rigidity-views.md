# Rigidity & Rigid Views

A **rigid view** is a tree-or-DAG projection over a knowledge graph that preserves an **inherent, objective ordering** — prerequisite chains, code structure, execution pipelines, directory hierarchies. It stands in contrast to the default **liquid** graph, which expresses subjective conceptual connections (similarity, analogy, user-authored links).

> Short version: the knowledge graph is liquid (semantic, user-shaped). A rigid view is a structural spine extracted from that graph (or from an external artifact it references) — cycles removed, orderings preserved, guaranteed traversable.

## Liquid vs Rigid

| Aspect | Liquid (existing graph) | Rigid View (this spec) |
|---|---|---|
| **Shape** | General graph — may contain cycles, bidirectional edges, ambiguous ordering | Tree or DAG — cycles removed, unambiguous traversal |
| **Semantics** | Conceptual, associative ("X is similar to Y") | Structural, mechanical ("X must come before Y") |
| **Origin** | User-authored edges, AI similarity inference, landscape merge | Derived from structural rules, code AST, pipeline definitions, ML-informed ordering |
| **Mutability** | Reshapes freely with user preference | Fixed by artifact or algorithm — only changes when source artifact changes |
| **Primary use** | Browsing, connecting ideas, discovery | Traversal, execution, prerequisite enforcement, reproducibility |
| **Breaks when** | Nothing breaks — graph is forgiving | Breaks when the underlying artifact breaks (e.g., missing code file, broken import) |

A rigid view is not a replacement for the liquid graph — both co-exist. The liquid graph is the **source of truth** for what the user knows; the rigid view is a **projection** computed on demand.

## Relationship to Existing Concepts

Rigid views extend and complement existing primitives rather than replacing them:

- **Traversal graph** ([note 05](05-traversal.md)) is a *specific kind* of rigid view — the one built from `prerequisite` edges for learning-path traversal. Rigid views generalize this pattern.
- **Edges** ([note 02](02-edges.md)) with directional types (`prerequisite`, `derivation`, `reference`) already carry rigid semantics. Rigid views aggregate these into coherent structural projections.
- **Forking** ([note 03](03-forking.md)) is the mechanism used when a rigid view is materialized into a user's personal graph (bulk-fork informed by the rigid view's node set and ordering).
- **Entities** ([note 00](00-entities.md)) — any entity (concept, data entity, link, …) can have rigid views attached via the shared `attached_rigid_views` field, capturing its analytical pipeline, prerequisite subgraph, citation DAG, or AST. Rigid views are the substrate by which any entity accumulates structured work product.
- **Group landscape** ([note 08](08-groups.md)) is the typical *source* for rigid views — a user learning a domain derives a rigid view over the landscape, then copies the nodes into their personal graph for mastery tracking.

## Rigid View Construction Strategies

A rigid view is produced by a **strategy** — a pluggable algorithm that takes a source (graph region or external artifact) and returns a DAG plus traversal metadata. Strategies fall into three families:

### 1. Structural (from edge types)

- **Prerequisite spanning tree** — take all directed `prerequisite` edges within a region, remove back-edges to break cycles, topologically sort. Existing traversal engine uses this.
- **Derivation chain** — follow directed `derivation` edges from axioms/primitives toward applied results.
- **Reference DAG** — `reference` edges oriented outward from a root concept.

### 2. Profile-informed (ML / user features)

When a region is large and multiple valid orderings exist, the strategy uses user-profile features to pick one:

- A math student traversing a statistics landscape gets a rigid view rooted in linear algebra and calculus.
- A law student traversing the same statistics landscape gets a rigid view rooted in probability, hypothesis testing, and evidentiary reasoning.
- A practitioner gets a rigid view rooted in applied examples; a researcher gets one rooted in theory.

Mechanism (sketch): cluster concepts by discipline/domain metadata, score clusters by user-profile vector similarity, pick the cluster as root, traverse outward. Implementation is deferred — the schema only needs to record *which strategy produced the view*.

### 3. Artifact-derived (programmatic entities)

Rigid views extracted from external artifacts that *have their own inherent structure*:

| Artifact | Rigid View Extracted |
|---|---|
| Code repository | Directory tree |
| Python/JS/etc. codebase | Module import graph (DAG) |
| Single source file | AST-derived tree of classes, functions, variables |
| Jupyter notebook | Cell execution order + variable dependency DAG |
| Data pipeline (dbt, Airflow, Prefect) | Task DAG |
| Research workflow | Experimental step ordering (preprocess → train → evaluate) |
| Build system (Make, Bazel) | Target dependency DAG |

This family is the **critical case for data science, research, and development work** — the one where the liquid graph alone is insufficient.

## Programmatic Entities (The Critical Case)

Code, notebooks, and pipelines are artifacts where **the inherent structure must be preserved for the artifact to function**. You cannot reorder imports arbitrarily; you cannot flatten a directory tree; you cannot shuffle pipeline stages. The rigid view is the *canonical representation* of these artifacts inside the knowledge platform.

### Why this matters

The existing knowledge graph treats a `.py` file as a markdown-ish note — a blob of content attached to a concept. That loses everything: function boundaries, variable scope, import relationships, call graph. A user exploring a codebase through a liquid graph can't see "what does this function depend on" or "what breaks if I change this variable."

A rigid view preserves this structure as first-class data.

### Granularity levels

A single code file or repository supports multiple rigid views at different zoom levels:

| Level | What the rigid view captures | Example use |
|---|---|---|
| **Repo** | Directory tree + top-level module graph | Navigating an unfamiliar codebase |
| **Package** | Module import DAG within a package | Understanding package architecture |
| **File** | AST-level tree of definitions (classes → methods → statements) | Reading/reviewing a specific file |
| **Function** | Variable dependency DAG + call graph within a scope | Debugging, refactoring, variable tracking |
| **Pipeline** | Execution DAG (data in → transforms → data out) | Reproducing an experiment |

### Execution visualization (addon)

Once a rigid view models an execution pipeline, a runtime overlay becomes natural:

- Highlight the node currently executing
- Show intermediate data at each edge
- Animate progress through the DAG
- Attach metrics/artifacts to each completed step

This turns the rigid view into both a **static map** (what's there) and a **dynamic dashboard** (what's happening). Execution visualization is a deferred addon — the rigid view schema just needs fields to support it (e.g., per-node runtime status).

## Rigid View as a Learning Tool (Landscape → Personal Copy)

The flow the user described:

1. A member views the **group landscape** and wants to learn a subregion (e.g., "Bayesian methods").
2. The system generates a **rigid view** over that region — ordered by prerequisite chain, or ML-informed by the member's profile (e.g., math-student ordering).
3. The member confirms the rigid view is the path they want.
4. The system **bulk-forks** each concept in the rigid view into the member's personal graph, preserving the ordering as prerequisite edges.
5. Each forked concept is initialized with **mastery metadata** — e.g., `mastery: 0.0`, `status: "pending"`, `estimated_effort: ...`.
6. As the member completes items associated with each concept, mastery updates propagate to the knowledge state **K**, which feeds back into the traversal engine ([note 05](05-traversal.md)).

### Mastery features (shape, not specifics)

The copied concepts carry feature fields that downstream services populate:

| Field | Populated by | Purpose |
|---|---|---|
| `mastery` | Item service, self-assessment | 0.0 → 1.0 confidence |
| `status` | Traversal engine | pending / learning / mastered / archived |
| `difficulty` | Item generation feasibility check | easy → expert |
| `time_spent` | Client telemetry | Minutes invested |
| `last_reviewed` | Spaced repetition | Schedule next review |
| `source_rigid_view_id` | This service | Which rigid view produced this copy |

Feature specifics (which ML algorithm, which mastery model) are deferred — the schema just needs to carry them.

## Data Model (sketch)

A rigid view is an entity with `kind: "rigid_view"` — it inherits the shared entity shell ([note 00](00-entities.md)) and defines its kind-specific `content`:

```
entity (kind: "rigid_view")
├─ shared: _id, owner_id, group_id, name, description, tags, status, visibility, fork, timestamps
├─ shared: entries[]       — runtime logs, per-run metrics (for execution-style rigid views)
├─ shared: reviews[]       — reviewer sign-off on the rigid view's structure or outputs
└─ content:
    ├─ source_type: "graph_region" | "code_repo" | "notebook" | "pipeline" | ...
    ├─ source_ref: { group_id, root_concept_id, artifact_url, ... }
    ├─ strategy: "prerequisite_tree" | "import_graph" | "ast" | "profile_informed" | ...
    ├─ strategy_params: { user_profile, clustering_method, ... }
    ├─ nodes: [{ id, label, parent_id, depth, metadata }]
    ├─ edges: [{ source, target, kind: "structural" | "execution" | "prerequisite" }]
    ├─ root_ids: [...]
    ├─ is_tree: bool
    ├─ generated_at
    └─ generated_from_version: optional ref for cache invalidation
```

Rigid views are **derived** — regenerable from source at any time. They're cached for performance but never authoritative. If the source graph or artifact changes, the cached rigid view is invalidated.

**How rigid views attach to other entities**: any entity can reference one or more rigid views via its shared `attached_rigid_views` array (see [note 00](00-entities.md#attached_rigid_views--derived-structural-projections)). One rigid view may be attached by multiple entities (e.g., a standard "ML evaluation pipeline" template attached by many data entities); and one entity may have multiple rigid views attached with different `role`s (e.g., a concept with both a `prerequisite_tree` and a `citation_dag`).

## Frontend Implications

The floating-window shell should support both viewing modes:

| Mode | Renderer | Interactions |
|---|---|---|
| **Liquid** (default) | Force-directed graph, pan/zoom, cluster | Browse, connect, discover |
| **Rigid** | Tree layout / DAG flowchart (top-down or left-right) | Traverse, mark complete, step through |

Users toggle between modes for the same region. The rigid view mode gets additional overlays when the view is artifact-derived: execution status, per-file drill-down, pipeline step animation.

Specific frontend needs:

- A renderer library suited to DAGs/trees (candidates: React Flow, dagre-d3, mermaid, custom SVG)
- A per-node "inspector" panel (file content, variable list, function signatures)
- A "generate rigid view" action in the landscape browser
- A "materialize to personal graph" action that triggers the bulk-fork flow

## Relationship to Microservices

A future `rigid-view-service` sits cleanly alongside existing services:

```
concept-service  ─┐
edge-service     ─┤   ┌─> rigid-view-service
traversal-service├──> │   ├─ strategies/prerequisite_tree
group-service    ─┘   │   ├─ strategies/code_graph
ai-service       ────>│   ├─ strategies/profile_informed
                      │   └─ strategies/pipeline_dag
                      └──> cached_views (MongoDB)
```

The service reads from the liquid graph (or external artifacts), applies a strategy, writes the resulting DAG to a cache, and serves it via `/api/v1/rigid-views`.

## Open Questions

- **Strategy registry** — how are new rigid-view strategies registered? Plugin system, configuration, or hardcoded dispatch?
- **Cycle-breaking policy** — when a strategy hits a cycle in the liquid graph, which edge gets dropped? User choice, timestamp, or heuristic?
- **Profile vector** — what features define a "math student" vs "law student"? Manually declared, inferred from knowledge state, learned from behavior?
- **Code parsing scope** — which languages do we support initially? (Python AST is easy; Java/TS/Rust each need their own parsers.)
- **Notebook handling** — do we extract a rigid view from `.ipynb` files? (This is specifically requested by data science workflows.)
- **Execution overlay source** — where does runtime data come from? External observability systems (OpenTelemetry), our own event bus, or plugin-specific?
- **Versioning** — when source artifacts change, do we keep prior rigid view snapshots (diff-able) or always regenerate fresh?
- **Interaction with mastery** — if the user's rigid-view-materialized concepts fall behind (mastery stalls), does the system re-suggest the next step, or switch strategy?
- **Cross-rigid-view linkage** — can one rigid view reference another? (E.g., "this code rigid view depends on this prerequisite rigid view.")

## Status

- **Concept**: Formalized here.
- **Implementation**: Deferred. No code dependencies on this yet.
- **Related working code**: The traversal engine ([note 05](05-traversal.md)) already implements one strategy (prerequisite spanning tree) under a different name. Generalizing it into the rigid-view-service is the natural first concrete step.
