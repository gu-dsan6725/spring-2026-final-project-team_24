# Groups & Organizations

A **group** defines a shared region of the knowledge graph with collaborative features and customizable AI services.

## Shared Regions & Landscape

- A group creates a **region** — a bounded subgraph visible to its members.
- Members contribute concepts and edges from their personal graphs into the region.
- The **landscape** ([Merging](04-merging.md)) merges similar notes into canonical nodes.
- Divergent perspectives are preserved — different users' takes on the same concept are visible as perspectives under the canonical node.

## Permissions & Roles

| Role | Capabilities |
|---|---|
| **Owner / Admin** | Full control — manage members, configure AI services, define region boundaries |
| **Instructor / Professor** | Configure AI pipelines, curate items, review and annotate student concepts |
| **Member / Student** | Contribute concepts, create edges, consume items, use AI services |
| **Viewer** | Read-only access to the region |

## MCP & AI Service Domains

Each group defines its own **AI service domain** — a customizable layer of AI capabilities scoped to the region.

### Configurable AI Pipelines

| Pipeline | Configuration Options |
|---|---|
| **Embedding model** | Choose model for concept embeddings (OpenAI, Cohere, local sentence-transformers, etc.) |
| **Connection inference** | Method for auto-generating edges (cosine threshold, LLM reasoning, hybrid) |
| **Item construction** | How items are generated from concepts — prompt templates, difficulty calibration, LLM provider |
| **Note evaluation** | AI-assisted grading/feedback on student concepts — rubric, LLM model |
| **Data pipelines** | ETL logic for data entities — SQL generation, chart recommendation |

### MCP (Model Context Protocol) Integration

- Groups can expose their region as an **MCP server** for external AI agents and tools.
- Groups can connect **external MCP servers** as data/tool sources.
- Admins can design custom MCP tool definitions wrapping their group's AI pipelines.
