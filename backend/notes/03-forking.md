# Forking

**Fork** is a universal operation that applies to any entity in the platform — concepts, edges, and future dives. Forking creates a new entity with a provenance link back to the original.

## What forking means

- A fork is a **new entity**, not a copy. It builds on the source with the forker's own perspective.
- The original is never modified. The fork lives in the forker's personal graph.
- The original author is notified and can reference the fork back.
- Fork provenance is recorded so the lineage is always traceable.

## Fork provenance

Every entity (concept, edge, dive) carries an optional `fork` field. When `null`, the entity is an original. When present, it records where the entity came from:

```json
"fork": {
  "from_entity_id": "concept_abc",
  "from_owner_id": "user_55",
  "from_group_id": "group_ml_class",
  "forked_at": "2026-04-09T10:00:00Z"
}
```

| Field | Type | Description |
|---|---|---|
| `from_entity_id` | string | ID of the original entity that was forked |
| `from_owner_id` | string | User who owns the original |
| `from_group_id` | string (optional) | Group where the original was discovered (null if from a public source or direct share) |
| `forked_at` | datetime | When the fork was created |

## Forking by entity type

### Concepts

Forking a concept creates a new concept node in the forker's personal graph. The forker can modify, extend, or rewrite the content while preserving the link to the original.

A directed `reference` or `derivation` edge from the fork back to the original is suggested automatically.

### Edges

Forking an edge copies its type, direction, and note into a new edge owned by the forker. Useful when adapting another member's prerequisite map or relationship annotation for your own graph.

### Dives (future)

When dive hyperedges are implemented, they will be forkable in the same way — creating a new dive with the same foundation concepts but the forker's own advanced content.

## Visibility

Forks can originate from:
- **Within the same group** — forking a concept visible in the group landscape
- **Across groups** — if cross-group discovery is enabled, forking a concept from another group
- **External sources** — forking from a shared link or public reference (fork provenance records the source URL or identifier)

## Branching

Multiple users can fork the same entity independently, producing branching extensions visible in the group landscape. The canonical node merge pipeline (see [Merging](04-merging.md)) considers fork lineage when deciding whether to merge or keep forks as distinct perspectives.
