# Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                          API Gateway                             │
│                   (Auth, Rate Limiting, Routing)                  │
├────────┬────────┬──────────┬──────────┬──────────┬───────────────┤
│ Concept│  Data  │  Items   │  Groups  │Traversal │ AI Services   │
│Service │Service │ Service  │ Service  │ Engine   │ Orchestrator  │
│        │        │          │          │          │ (ACE + M-H)   │
├────────┴────────┴──────────┴──────────┴──────────┴───────────────┤
│                     Message Queue / Event Bus                     │
│          (every write emits events → vector search pipeline)      │
├──────────────────────────────────────────────────────────────────┤
│  MongoDB      │  PostgreSQL     │  Pinecone       │  S3 / MinIO  │
│ (concepts,    │  (users, groups │  (embeddings,    │ (audio,      │
│  edges, ACE   │   permissions,  │   merge detect,  │  media,      │
│  playbooks,   │   K-states,     │   foreign content│  uploads)    │
│  canonical    │   scheduling)   │   resolution)    │              │
│  nodes)       │                 │                  │              │
└───────────────┴─────────────────┴──────────────────┴──────────────┘
```

## Storage Layers

| Store | Purpose | Technology |
|---|---|---|
| **MongoDB** | Document store for concepts, edges (with markdown bodies), canonical landscape nodes, ACE playbooks (group + per-user). Supports delta updates (`$push`, `$set`, `$pull`) and graph traversal via `$graphLookup`. | MongoDB Atlas or self-hosted |
| **PostgreSQL** | Relational data: users, groups, permissions, knowledge states K, item scores, spaced repetition schedules. ACID transactions for auth and state updates. | PostgreSQL 16+ |
| **Pinecone** | Vector search for all similarity operations: merge detection, edge dedup, foreign content resolution, AI connection inference. Managed serverless — zero-ops. | Pinecone Serverless |
| **Object Store** | Audio files, images, handwritten submissions, large media. | S3-compatible (MinIO for local dev) |

## Pinecone Namespace Design

Searches are scoped by namespace to prevent cross-contamination and keep results fast:

| Namespace | Contents | Queried By |
|---|---|---|
| `group_{id}_landscape` | Canonical node embeddings | Merge pipeline (concept writes) |
| `group_{id}_edges` | Landscape edge body embeddings | Edge dedup, AI connection inference |
| `user_{id}_concepts` | Personal concept note embeddings | Foreign content resolution, personal dedup |
| `user_{id}_edges` | Personal edge body embeddings | Edge dedup ("you already have a similar connection") |

## Event-Driven Vector Search Pipeline

Every user write triggers at least one Pinecone search as a side effect:

| Event | Searches Triggered |
|---|---|
| New concept | 1–2 (landscape merge check + member convergence check) |
| Update concept | 1 (re-check landscape similarity, may shift cluster) |
| New edge | 1–2 (personal edge dedup + landscape edge check) |
| Update edge body | 1 (re-check against existing edges) |
| Fork/extend | 1 (check if extension overlaps another member's fork) |

For a course with 30 students writing 5–10 notes per week: 150–600 vector searches per week — trivial for Pinecone's serverless tier.

## Key Design Principles

- **Service-oriented** — each domain (concepts, items, groups, traversal, AI) is a distinct service with clear API boundaries
- **Event-driven** — every write emits events to the message queue, consumed by the vector search pipeline, ACE, the merge engine, and the traversal engine
- **Delta-first** — ACE playbooks and canonical nodes are updated incrementally, never rewritten. MongoDB's update operators (`$push`, `$set`, `$addToSet`) support this natively.
- **Plugin-friendly AI** — LLM and embedding providers are abstracted behind interfaces; groups swap implementations without code changes
- **Multi-tenant** — groups are isolated regions; shared infrastructure, scoped data. Pinecone namespaces enforce isolation.
- **Superhypergraph underneath, standard graph on top** — the data model supports hyperedges (items) and nested subgraphs (groups), but the user always sees a clean node-and-edge interface at their current semantic zoom level
