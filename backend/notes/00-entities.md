# Entities (Nodes) — Core Spec

An **entity** is the fundamental unit in the platform. Every node in the knowledge graph — whether it holds a markdown note, a dataset reference, a link, a rigid view, or a future content type — is an entity. Entities share one document shape; a `kind` discriminator dispatches kind-specific content.

> Short version: one shell, many kinds. The shell gives every entity a rich attachment surface (appendable entries, attached rigid views, reviews, status) so any node can accumulate work product without a separate "project" or "dive" wrapper.

This note is the **foundation** for all other entity notes. Kind-specific docs ([concepts](01-concepts.md), [data entities](07-data-entities.md), [items](06-items.md), [rigid views](15-rigidity-views.md)) describe only the `kind`-specific `content` field and any kind-specific endpoints — everything else inherits from this spec.

## Why a unified entity model

Earlier drafts introduced a separate "dive" concept for project-like work (research projects, data science pipelines, product specs). Analysis showed the dive pattern is not a new entity type — it is an **emergent state** of any entity that has accumulated rigid views, entries, and reviews. Instead of adding a meta-entity above entities, we make every entity capable of hosting that accumulation. This collapses the ontology and removes a redundant abstraction layer.

What a rich, accumulating entity looks like in practice:

- A dataset entity with no attachments = just data.
- The same dataset + 3 attached rigid views (pipelines) + 12 entries (reports/metrics) + a review = what used to be called a "data-science dive." No new type required.
- A markdown plan + forked rigid interpretations from group members + an approved status = what used to be called a "product dive." Same shell.
- A concept + citations + derivation rigid view + a draft paper entry = what used to be called a "research dive." Same shell.

The project-like behavior emerges from composition, not from a separate table.

## Document Shape

Every entity document in MongoDB follows this shape:

```json
{
  "_id": "ent_abc123",
  "kind": "concept",
  "owner_id": "user_42",
  "group_id": "group_ml_class",

  "name": "Principal Component Analysis",
  "description": "Short summary used in listings and search results.",
  "tags": ["linear-algebra", "dimensionality-reduction"],

  "content": { /* kind-specific payload — see per-kind notes */ },

  "entries": [
    {
      "id": "entry_001",
      "created_at": "2026-04-08T14:30:00Z",
      "created_by": "user_42",
      "kind": "report",
      "note": "Baseline evaluation, RF default params",
      "data": { "accuracy": 0.973, "f1_macro": 0.971 }
    }
  ],

  "attached_rigid_views": [
    { "rigid_view_id": "rv_abc", "role": "pipeline", "attached_by": "user_42" }
  ],

  "reviews": [
    {
      "id": "rev_001",
      "reviewer_id": "user_99",
      "reviewer_role": "head_of_data_science",
      "verdict": "approved",
      "note": "Methodology sound.",
      "created_at": "2026-04-10T..."
    }
  ],

  "status": "active",
  "visibility": "group",
  "fork": null,

  "created_at": "2026-04-07T...",
  "updated_at": "2026-04-09T..."
}
```

## Core Fields (shared by every entity)

| Field | Type | Purpose |
|---|---|---|
| `_id` | string | Unique entity identifier |
| `kind` | string enum | Discriminator — `"concept"`, `"data_entity"`, `"item"`, `"rigid_view"`, `"link"`, … |
| `owner_id` | string | User who created the entity (source of truth for personal graph ownership) |
| `group_id` | string \| null | Group scope, if any. `null` = personal-only |
| `name` | string | Human-readable label (required) |
| `description` | string \| null | Short free-text summary (optional) |
| `tags` | string[] | Discovery and filtering across the graph |
| `content` | object | Kind-specific payload — schema defined in the per-kind note |
| `entries` | Entry[] | Append-only log of member contributions (see below) |
| `attached_rigid_views` | AttachedRigidView[] | Rigid-view references (see below) |
| `reviews` | Review[] | Structured reviewer feedback (see below) |
| `status` | string enum | Lifecycle stage (see below) |
| `visibility` | string enum | `"private"`, `"group"`, `"public"` |
| `fork` | Fork \| null | Fork provenance — see [Forking](03-forking.md) |
| `created_at` | datetime | Creation timestamp |
| `updated_at` | datetime | Last modification timestamp |

The fields are identical across kinds. The only thing that changes between a concept, a data entity, and a link is `content`.

### `content` (kind-specific)

Dispatches by `kind`:

| `kind` | `content` shape (summary) | Spec |
|---|---|---|
| `concept` | `{ body_md, media: [{type: "video" \| "audio", url, ...}] }` | [note 01](01-concepts.md) |
| `data_entity` | `{ source: { storage, url, bucket, key, format, size_bytes, checksum_sha256 } }` | [note 07](07-data-entities.md) |
| `item` | `{ item_type, foundation_concept_ids, prompt, answer, ... }` | [note 06](06-items.md) |
| `rigid_view` | `{ source_type, strategy, nodes, edges, root_ids, is_tree }` | [note 15](15-rigidity-views.md) |
| `link` | `{ url, title, og_metadata }` | (future) |

Each kind-specific note owns the `content` schema for that kind. No other field leaks into `content`.

### `entries` — Append-Only Member Contributions

Every entity supports an append-only log of freeform contributions. This is the mechanism by which members add reports, metrics, configs, notes, or any structured result **without modifying the entity's core content**.

```json
{
  "id": "entry_001",
  "created_at": "2026-04-08T14:30:00Z",
  "created_by": "user_42",
  "kind": "report",
  "note": "Free-text context for this entry",
  "data": { "...": "arbitrary JSON blob" }
}
```

| Field | Type | Description |
|---|---|---|
| `id` | string | Server-generated entry identifier |
| `created_at` | datetime | When appended |
| `created_by` | string | User who appended |
| `kind` | string (optional) | Entry subtype — `"report"`, `"metric"`, `"config"`, `"note"`, `"run_log"`, `"artifact_ref"` … |
| `note` | string \| null | Short human-readable description |
| `data` | object | Arbitrary JSON — evaluation metrics, pipeline configs, status payloads |

**Semantics**:
- Append-only. Existing entries are never mutated. (Audit trail + concurrent-safe via MongoDB `$push`.)
- Freeform `data`. The platform enforces no schema on `data`; kinds or groups may adopt conventions.
- Soft-deletable by owner/admin (removes from array; not physically erased from event log).

### `attached_rigid_views` — Derived Structural Projections

Rigid views (tree/DAG projections — see [note 15](15-rigidity-views.md)) are separate entities referenced by ID:

```json
{
  "rigid_view_id": "rv_abc",
  "role": "pipeline",
  "attached_by": "user_42",
  "attached_at": "2026-04-08T..."
}
```

| Field | Type | Description |
|---|---|---|
| `rigid_view_id` | string | Points to a `kind: "rigid_view"` entity |
| `role` | string | What the rigid view *is* for this entity — `"pipeline"`, `"prerequisite_tree"`, `"ast"`, `"methodology"`, `"citation_dag"`, `"custom"` |
| `attached_by` | string | User who attached the view |
| `attached_at` | datetime | When attached |

Multiple rigid views can attach with the same `role` (e.g., competing pipeline interpretations from different members). The rigid view itself is cached/derived — see [note 15](15-rigidity-views.md).

### `reviews` — Structured Reviewer Feedback

```json
{
  "id": "rev_001",
  "reviewer_id": "user_99",
  "reviewer_role": "head_of_data_science",
  "verdict": "approved",
  "note": "Methodology sound.",
  "scope": { "target": "attached_rigid_view", "rigid_view_id": "rv_abc" },
  "created_at": "2026-04-10T..."
}
```

| Field | Type | Description |
|---|---|---|
| `id` | string | Server-generated review identifier |
| `reviewer_id` | string | User who reviewed |
| `reviewer_role` | string (optional) | Role label at time of review (immutable snapshot) |
| `verdict` | string | `"approved"`, `"changes_requested"`, `"rejected"`, `"comment"` |
| `note` | string | Free-text feedback |
| `scope` | object (optional) | What was reviewed — whole entity, a specific attached rigid view, or a specific entry |
| `created_at` | datetime | When created |

Reviews never mutate the entity they target. They accumulate like entries.

### `status` — Lifecycle Stage

Default values (kinds may define narrower enums):

| Value | Meaning |
|---|---|
| `draft` | Freshly created, not yet ready for engagement |
| `active` | Under development — entries accumulating, rigid views being built |
| `in_review` | Work product submitted for review; further edits discouraged |
| `finalized` | Outputs locked; can still be executed/consumed but not re-authored |
| `published` | Pushed to group landscape as reference content |
| `archived` | Retired — retained for provenance only |

Transitions are user- or system-driven; no automatic progression. The field is advisory — clients may filter by it but the schema imposes no hard gating.

### `visibility` — Scope

| Value | Meaning |
|---|---|
| `private` | Personal graph only; not surfaced in any landscape |
| `group` | Visible within `group_id` (if set) |
| `public` | Visible across all groups (cross-group discovery) |

### `fork` — Provenance

See [Forking](03-forking.md). When non-null, the entity is a derivative of another entity; provenance is preserved across kinds uniformly.

## Inline vs Referential Containment

Entities follow two containment rules:

**Inline (in the document)** — small, owned-by-this-entity data:
- `content` (markdown body, source metadata, etc.)
- `entries[]`, `reviews[]`, `tags[]`
- References by ID to other entities (`attached_rigid_views[].rigid_view_id`)

**Referential (in other collections)** — large, independently-queryable data:
- Full rigid view documents (referenced by ID in `attached_rigid_views`)
- Edges (separate `edges` collection — see [note 02](02-edges.md))
- Binary payloads (files in S3/MinIO — referenced by URI inside `content.source`)
- Vector embeddings (in Pinecone — referenced by vector ID)

The entity document stays small (well within MongoDB's 16 MB document limit). Heavy payloads live out-of-band. Graph shape lives in the `edges` collection.

## API Surface

All entity interactions are JSON-over-HTTP. The API is the sole gateway — clients never touch MongoDB, Pinecone, or S3 directly.

### Generic entity endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/entities` | Create an entity of any kind |
| `GET` | `/api/v1/entities/{id}` | Fetch full entity document |
| `PATCH` | `/api/v1/entities/{id}` | Update mutable top-level fields (`name`, `description`, `tags`, `status`, `visibility`) |
| `DELETE` | `/api/v1/entities/{id}` | Soft-delete (owner/admin) |
| `POST` | `/api/v1/entities/{id}/entries` | Append an entry |
| `DELETE` | `/api/v1/entities/{id}/entries/{entry_id}` | Remove an entry (owner/admin) |
| `POST` | `/api/v1/entities/{id}/rigid-views` | Attach a rigid view (by ID or inline spec) |
| `DELETE` | `/api/v1/entities/{id}/rigid-views/{rv_id}` | Detach a rigid view |
| `POST` | `/api/v1/entities/{id}/reviews` | Add a review |
| `POST` | `/api/v1/entities/{id}/fork` | Fork this entity into the caller's personal graph |
| `GET` | `/api/v1/entities/{id}/edges` | Edges connected to this entity |

### Kind-specific convenience endpoints

Kinds may expose convenience routes layered on top of the generic API:

- `/api/v1/concepts` → filtered to `kind: "concept"`
- `/api/v1/data-entities` → filtered to `kind: "data_entity"`
- `/api/v1/rigid-views` → filtered to `kind: "rigid_view"`, plus generation endpoints

These routes share the same underlying document shape and validation; they exist for client ergonomics only.

## Pydantic Schemas (sketch)

```python
from typing import Any, Literal
from datetime import datetime
from pydantic import BaseModel

EntityKind = Literal["concept", "data_entity", "item", "rigid_view", "link"]
Status = Literal["draft", "active", "in_review", "finalized", "published", "archived"]
Visibility = Literal["private", "group", "public"]

class Entry(BaseModel):
    id: str
    created_at: datetime
    created_by: str
    kind: str | None = None
    note: str | None = None
    data: dict[str, Any]

class AttachedRigidView(BaseModel):
    rigid_view_id: str
    role: str
    attached_by: str
    attached_at: datetime

class Review(BaseModel):
    id: str
    reviewer_id: str
    reviewer_role: str | None = None
    verdict: Literal["approved", "changes_requested", "rejected", "comment"]
    note: str | None = None
    scope: dict[str, Any] | None = None
    created_at: datetime

class Fork(BaseModel):
    from_entity_id: str
    from_owner_id: str
    from_group_id: str | None = None
    forked_at: datetime

class EntityBase(BaseModel):
    id: str
    kind: EntityKind
    owner_id: str
    group_id: str | None = None
    name: str
    description: str | None = None
    tags: list[str] = []
    content: dict[str, Any]               # kind-specific — validated by discriminated union
    entries: list[Entry] = []
    attached_rigid_views: list[AttachedRigidView] = []
    reviews: list[Review] = []
    status: Status = "draft"
    visibility: Visibility = "private"
    fork: Fork | None = None
    created_at: datetime
    updated_at: datetime
```

Kind-specific models narrow `content` using a discriminated union, e.g., `ConceptEntity(EntityBase, kind=Literal["concept"], content: ConceptContent)`. See the per-kind notes.

## Design Rationale

- **One shell, many kinds** — simpler ontology, easier to extend. New content types (link, image, notebook, chart) = new `kind` value + new `content` schema. No new collection, no new endpoint family.
- **Rich attachment surface on every entity** — any node can host project-like accumulation (entries, rigid views, reviews) without an outer wrapper. Removes the need for a separate "project" or "dive" type.
- **Append-only entries** — MongoDB `$push` is atomic; safe for concurrent contributions from group members. Natural audit trail.
- **Reference large payloads** — binaries in object storage, vectors in Pinecone, rigid views in their own documents. Keeps entity documents small.
- **Kind discrimination, not table separation** — one collection (`entities`) with a `kind` field keeps cross-kind queries cheap (e.g., "all entities in this group tagged `bayesian`") while still allowing kind-specific indexes and schemas.

## Graph Participation

Every entity is a node in the graph regardless of kind. Concepts and data entities, rigid views and links — all connect through the unified [edge](02-edges.md) model. A prerequisite edge can link two concepts, or a concept to a data entity, or a data entity to a rigid view; the edge collection does not care about `kind`.

Traversal ([note 05](05-traversal.md)) operates over directed edges regardless of endpoint kind. Landscape merge ([note 04](04-merging.md)) deduplicates by semantic similarity within a `kind`.

## Migration Notes

- The legacy "dive" concept is **fully absorbed** into this spec. No separate `dives` collection exists or is planned. Previous dive framings in [note 02](02-edges.md) and [note 07](07-data-entities.md) have been removed.
- The legacy `data_entities` collection (per [note 07](07-data-entities.md)) maps 1:1 onto `entities` with `kind: "data_entity"`. Storage consolidation can be done in a single migration — same fields, same semantics, new `kind` discriminator.
- Existing `concepts` likewise become `kind: "concept"` in the unified collection.

## Open Questions

- **Storage consolidation** — one `entities` collection or keep per-kind collections (`concepts`, `data_entities`, …) with shared indexes? One collection is simpler; per-kind collections allow tighter schemas and targeted indexes. Default plan: one collection with a compound index on `(kind, group_id, updated_at)`.
- **Entry schema registration** — should groups be able to register expected `entry.data` schemas for their workflows (e.g., "all entries of kind `eval` must include `accuracy`")? Deferred — freeform for now.
- **Review workflows** — simple `verdict` string for MVP, but do we need multi-reviewer aggregation (e.g., "2/3 approvals required")? Deferred.
- **Status transitions** — enforced gating (can't go `draft → finalized` without `active` in between) or fully freeform? Default: freeform; kinds may layer gating in their own service.
- **Cross-kind similarity** — should landscape merge ever collapse a concept and a data entity? Probably not; landscape merge is kind-scoped.

## Status

- **Concept**: Formalized here. This note supersedes the prior "dive" framing and subsumes the shared-field portion of the data entity spec.
- **Implementation**: Phased — start with the `content`, `entries`, `fork` fields (already partially implemented for data entities); add `attached_rigid_views`, `reviews`, and extended `status` when the rigid view service and review flow come online.
- **Required for MVP**: `_id`, `kind`, `owner_id`, `name`, `content`, `entries[]`, `tags`, `fork`, timestamps. Everything else can phase in.
