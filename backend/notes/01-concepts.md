# Concepts (Nodes)

A **concept** is the fundamental unit of knowledge. Each concept encapsulates a piece of content and participates in a graph of relationships.

## Content Types

A concept may contain one or more of the following:

| Type | Description |
|---|---|
| **Markdown** (`.md`) | Rich text notes, definitions, explanations, derivations, LaTeX |
| **Video** (URL) | External video links (YouTube, Vimeo, hosted media) |
| **Voice / Audio** | Uploaded audio recordings — lectures, voice memos, explanations |

## Three-Layer Graph Model

The platform maintains three co-existing views of the same underlying knowledge:

**Personal Graph** — each user's own concept nodes and edges. This is the source of truth for what a user *knows*. Other users cannot modify it. When a user creates a note, it lives here first.

**Group Landscape** — a merged, deduplicated view of all group members' personal graphs within a region. Semantically similar notes from different users collapse into **canonical nodes**, each preserving links to every original perspective. The landscape is a computed view — personal graphs are never modified by the merge.

**Traversal Graph** — a personalized directed acyclic graph derived from the landscape, filtered by a specific user's knowledge state. This drives study mode and learning path recommendations. See [Traversal Engine](05-traversal.md).
