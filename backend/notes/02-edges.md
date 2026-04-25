# Edges

An **edge** connects two concept nodes. The platform uses a single unified edge model — direction, type, and an optional note.

## Edge Model

Stored as MongoDB documents in the `edges` collection:

```json
{
  "_id": "edge_abc123",
  "source_id": "concept_linear_algebra",
  "target_id": "concept_pca",
  "direction": "directed",
  "type": "prerequisite",
  "note": "PCA requires eigendecomposition from linear algebra",
  "origin": "user",
  "confidence": null,
  "created_by": "user_42",
  "fork": null,
  "created_at": "2026-04-07T...",
  "updated_at": "2026-04-07T..."
}
```

### Fields

| Field | Type | Description |
|---|---|---|
| `source_id` | string | Origin concept node |
| `target_id` | string | Destination concept node |
| `direction` | string | `"directed"` or `"undirected"` |
| `type` | string | See type taxonomy below |
| `note` | string (optional) | Short markdown note explaining why this edge exists |
| `origin` | string | `"user"`, `"ai_suggested"`, `"admin"` |
| `confidence` | float (optional) | AI-generated edges only — confidence score |
| `created_by` | string | User who created the edge |
| `fork` | object (optional) | Fork provenance — see [Forking](03-forking.md) |
| `created_at` | datetime | Creation timestamp |
| `updated_at` | datetime | Last modification timestamp |

### Type Taxonomy

| Type | Default Direction | Example |
|---|---|---|
| **prerequisite** | directed | "Calculus requires algebra" |
| **reference** | directed | "Bayes theorem references probability axioms" |
| **application** | undirected | "Linear algebra applies to ML" |
| **derivation** | directed | "Chain rule is derived from limit definition" |
| **contrast** | undirected | "Frequentist vs. Bayesian" |
| **analogy** | undirected | "Neural nets analogous to biological neurons" |
| **custom** | user chooses | Freeform label with user-defined semantics |

Default direction is a suggestion — users can override it.

### Origin Sources

| Origin | Mechanism |
|---|---|
| `user` | Manual creation with optional note |
| `ai_suggested` | Embedding similarity, LLM inference, co-occurrence analysis. Includes confidence score. |
| `admin` | Instructor/admin-defined prerequisite maps (e.g., course topic ordering) |

## Traversal

The traversal engine does **not** use a separate edge type. Instead, it derives its DAG from directed `prerequisite` edges (and optionally other directed types like `reference` and `derivation`). This keeps the model simple — one edge collection, one schema.

Cycle detection runs on the subset of directed edges used for traversal. Cycles are flagged for resolution: either break the cycle or group the cyclic concepts into a learn-together cluster.

See [Traversal Engine](05-traversal.md) for the outer-fringe algorithm.

## Fork Provenance

Any edge can be forked from another user's edge. When present, the `fork` field records where it came from:

```json
"fork": {
  "from_entity_id": "edge_xyz",
  "from_owner_id": "user_55",
  "from_group_id": "group_ml_class",
  "forked_at": "2026-04-09T..."
}
```

Fork is a **universal operation** — it applies to concepts, edges, and future dives alike. See [Forking](03-forking.md) for the full spec.

## Examples

**Prerequisite edge (directed, user-created):**
```json
{
  "source_id": "concept_linear_algebra",
  "target_id": "concept_pca",
  "direction": "directed",
  "type": "prerequisite",
  "note": "PCA requires eigendecomposition from linear algebra",
  "origin": "user",
  "fork": null
}
```

**AI-suggested analogy (undirected):**
```json
{
  "source_id": "concept_neural_nets",
  "target_id": "concept_biological_neurons",
  "direction": "undirected",
  "type": "analogy",
  "note": null,
  "origin": "ai_suggested",
  "confidence": 0.87
}
```

**Forked prerequisite from another group member:**
```json
{
  "source_id": "concept_probability",
  "target_id": "concept_bayesian_inference",
  "direction": "directed",
  "type": "prerequisite",
  "note": "Adapted from Sarah's ML course prereq map",
  "origin": "user",
  "fork": {
    "from_entity_id": "edge_sarah_prereq_42",
    "from_owner_id": "user_sarah",
    "from_group_id": "group_ml_class",
    "forked_at": "2026-04-09T10:00:00Z"
  }
}
```

---

## *[Experimental — Deferred]* Dive Hyperedges

> This section describes a future concept. Do not implement.

A **dive** is an advanced exploration point that spans multiple foundation concepts. It represents deeper territory a user reaches through agentic Q&A and progressive knowledge building.

### Concept

- Concepts are **base level** nodes — the fundamental units of knowledge.
- **Diving** is the action of exploring deeper into an advanced topic that requires multiple base concepts.
- A dive is a hyperedge connecting its foundation concepts to an advanced research or application topic.

### How it works

When a user accesses a dive, the system provides:

1. All **foundation concept nodes** the dive requires
2. The **prerequisite subgraph** connecting those nodes (all edges between them)
3. The dive's own **content** — the advanced topic, research question, or application

This gives the user a complete learning package: "here's everything you need to know, and here's the advanced territory you're diving into."

### Creation

Dives emerge from the agentic pipeline. As a user explores deeper through Q&A alongside their knowledge base, the system can propose a dive that captures the advanced territory they've reached — linking it back to the foundation concepts that enabled the exploration.

### Example

A dive "Kernel PCA in High-Dimensional Spaces" might have foundations:
- Linear Algebra (eigendecomposition)
- Probability (distribution assumptions)
- Optimization (objective functions)
- PCA (base technique)

Accessing this dive gives the user the full subgraph of these four concepts plus all their interconnecting edges, followed by the dive's own advanced content.

### Visualization concern

Dives could create visual clutter if rendered alongside all base-level edges. The suggested approach is **dive-included region** rendering: when viewing a dive, show only its foundation subgraph — the relevant nodes and edges — not the entire graph. This keeps the view focused and manageable.

### Data Entities as Specialized Dives

A **data entity** is the first concrete specialization of the dive concept. Where a generic dive has abstract "advanced content," a data entity has a real dataset at its center — with download metadata, a description, and appendable entries from different group members representing independent analytical approaches.

See [Data Entities](07-data-entities.md#data-entity-as-specialized-dive) for the full mapping between dive concepts and data entity fields.

### Open questions

- How are dives stored? Separate collection or embedded in the concept graph?
- Can dives have edges between them (dive-to-dive prerequisites)?
- How does the agentic pipeline decide when to propose a dive vs. create a new concept?
- Should dives be forkable like concepts and edges? (likely yes — see [Forking](03-forking.md))
