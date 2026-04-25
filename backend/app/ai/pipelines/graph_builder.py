"""LLM-driven dependency graph builder for paper sections.

Adapted from XingYx12's ``app/services/karpathy_agents/`` (origin/yubo branch).
That pipeline has four LLM agents (document analyst → summarizer → link
architect → link writer) and persists into a SQL Entity/Edge table; we keep
**only the link-architect step** because all we need here is a directed,
typed dependency graph over the section MDs we already produced. Output is
consumed by the depth-aware item generation scheduler.

One LLM call per paper. Returns:

* ``edges``  – directed list ``(source_section_id, target_section_id, label)``
  where the LLM is instructed to use ``depends_on`` / ``contrasts`` /
  ``generalizes`` / ``instantiates`` style labels, with directionality
  "source elaborates or depends on target".
* ``depths`` – ``{section_id -> int}`` from a topological layering over
  ``depends_on`` edges (cycles are condensed into one layer via Tarjan SCC).

The whole module is gracefully degradable: if no LLM key is configured we
return ``([], {sec_id: 0 for sec_id in sections})`` so the pipeline never
breaks ingest. Callers should treat depth=0 as "unranked".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.ai.jsonutil import load_llm_json
from app.ai.providers import chat_available, chat_json_completion
from app.ingest.section_splitter import Section

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GraphEdge:
    source: str           # section_id, e.g. "sec_03"
    target: str           # section_id
    label: str            # e.g. "depends_on", "generalizes", "contrasts"
    anchor: str | None = None  # short phrase the LLM thinks names this link


@dataclass
class GraphResult:
    edges: list[GraphEdge] = field(default_factory=list)
    depths: dict[str, int] = field(default_factory=dict)
    """``section_id -> depth``. depth=0 means "no inbound depends_on" (root layer).
    Sections that didn't appear in any edge are also assigned depth=0."""

    def edges_for_persist(self) -> list[dict]:
        return [
            {
                "source": e.source,
                "target": e.target,
                "label": e.label,
                "anchor": e.anchor,
            }
            for e in self.edges
        ]


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


_JSON_OUTPUT_RULES = (
    "CRITICAL — output format:\n"
    "- Return exactly ONE JSON object. No markdown code fences, no commentary.\n"
    "- All string values must be valid JSON (escape internal quotes as \\\").\n"
)


_LINK_ARCHITECT_SYSTEM = (
    _JSON_OUTPUT_RULES
    + "\nYou are the link architect agent for an academic-paper knowledge graph. "
    "You receive a catalog of sections from one paper and must propose a sparse "
    "directed graph capturing how the sections build on each other.\n\n"
    "Schema:\n"
    "{\n"
    '  "edges": [\n'
    '    {"source": "<section_id>", "target": "<section_id>", '
    '"label": "depends_on|generalizes|instantiates|contrasts|elaborates", '
    '"anchor": "short anchor phrase (optional)"}\n'
    "  ]\n"
    "}\n\n"
    "Rules:\n"
    "- source/target MUST be exact section_ids from the catalog.\n"
    "- No self-links. Direction matters: 'source depends_on target' means "
    "you must understand target before source makes sense.\n"
    "- Prefer `depends_on` for prerequisite relationships — these are what "
    "the downstream scheduler uses to determine reading order.\n"
    "- Keep the graph SPARSE: typically 1–3 outgoing edges per section.\n"
    "- Skip an edge if the relationship is weak or speculative.\n"
    "- The catalog order is the section order in the paper, but real "
    "dependencies often skip across (e.g. §5 depends on §2, not just §4)."
)


def _build_catalog(sections: list[Section], excerpt_chars: int = 320) -> str:
    """Catalog format: ``- <section_id> | <title!r> | <excerpt!r>``.

    Excerpt is the first ``excerpt_chars`` of the body, single-lined. We use
    an excerpt rather than a summary to keep the call to one round-trip; the
    architect-only port deliberately drops yubo's ``summarize_agent`` step.
    """
    lines: list[str] = []
    for sec in sections:
        body = (sec.body_md or "").strip().replace("\n", " ")[:excerpt_chars]
        lines.append(f"- {sec.section_id} | {sec.title!r} | {body!r}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Topological layering
# ---------------------------------------------------------------------------


def _scc_tarjan(nodes: list[str], adj: dict[str, list[str]]) -> list[list[str]]:
    """Tarjan's SCC. Returns components in reverse topological order
    (sinks first). Used to condense cycles before depth assignment."""
    index_counter = [0]
    stack: list[str] = []
    on_stack: dict[str, bool] = {}
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    components: list[list[str]] = []

    def strongconnect(v: str) -> None:
        indices[v] = index_counter[0]
        lowlinks[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack[v] = True

        for w in adj.get(v, []):
            if w not in indices:
                strongconnect(w)
                lowlinks[v] = min(lowlinks[v], lowlinks[w])
            elif on_stack.get(w):
                lowlinks[v] = min(lowlinks[v], indices[w])

        if lowlinks[v] == indices[v]:
            comp: list[str] = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                comp.append(w)
                if w == v:
                    break
            components.append(comp)

    for n in nodes:
        if n not in indices:
            strongconnect(n)
    return components


def compute_depths(
    section_ids: list[str],
    edges: list[GraphEdge],
    *,
    relation: str = "depends_on",
) -> dict[str, int]:
    """Assign each section a non-negative depth where roots = 0 and
    ``depth(v) = 1 + max(depth(u) for u in v.dependencies)``.

    Cycles are collapsed into a single SCC and all members share that
    component's depth (so a 2-cycle doesn't blow up). Sections with no
    inbound or outbound ``depends_on`` edge get depth 0.

    Only edges whose ``label`` matches ``relation`` (default ``"depends_on"``)
    contribute. Anchor / contrast / generalize edges are ignored for layering
    but kept for the UI and for downstream graph rendering.
    """
    # Build "depends_on" adjacency: src -> [tgt]. By our prompt convention,
    # `source depends_on target` ⇒ target must be learned BEFORE source ⇒
    # depth(source) = depth(target) + 1.
    rel = relation.strip().lower()
    adj: dict[str, list[str]] = {sid: [] for sid in section_ids}
    rev: dict[str, list[str]] = {sid: [] for sid in section_ids}
    valid_ids = set(section_ids)
    for e in edges:
        if e.label.strip().lower() != rel:
            continue
        if e.source not in valid_ids or e.target not in valid_ids:
            continue
        if e.source == e.target:
            continue
        adj[e.source].append(e.target)  # source → target (prerequisite)
        rev[e.target].append(e.source)

    # SCC on the depends_on subgraph. Tarjan returns components in reverse
    # topological order (sinks first), which is exactly what we want for
    # incremental depth assignment.
    comps = _scc_tarjan(section_ids, adj)
    comp_of: dict[str, int] = {}
    for cid, comp in enumerate(comps):
        for n in comp:
            comp_of[n] = cid

    # Condensation DAG: edges between distinct components only.
    cond_adj: dict[int, set[int]] = {i: set() for i in range(len(comps))}
    for u, outs in adj.items():
        cu = comp_of[u]
        for v in outs:
            cv = comp_of[v]
            if cv != cu:
                cond_adj[cu].add(cv)

    # depth(component) = 1 + max(depth(target component)) over outgoing
    # condensation edges; sinks ⇒ depth 0. Tarjan order is reverse-topo
    # (sinks first), so a single forward sweep suffices.
    comp_depth: dict[int, int] = {}
    for cid, _ in enumerate(comps):
        outs = cond_adj[cid]
        if not outs:
            comp_depth[cid] = 0
        else:
            comp_depth[cid] = 1 + max(comp_depth[o] for o in outs)

    return {sid: comp_depth[comp_of[sid]] for sid in section_ids}


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def _parse_edges(
    raw: dict, valid_ids: set[str], max_edges: int
) -> list[GraphEdge]:
    """Defensively parse the architect agent's JSON. Skips malformed
    entries silently; logs a warning if nothing usable came back."""
    edges_out: list[GraphEdge] = []
    seen: set[tuple[str, str]] = set()

    for item in (raw.get("edges") or []):
        if not isinstance(item, dict):
            continue
        if len(edges_out) >= max_edges:
            break
        src = str(item.get("source", "")).strip()
        tgt = str(item.get("target", "")).strip()
        if not src or not tgt or src == tgt:
            continue
        if src not in valid_ids or tgt not in valid_ids:
            continue
        key = (src, tgt)
        if key in seen:
            continue
        seen.add(key)
        label = (str(item.get("label", "depends_on")).strip().lower() or "depends_on")[:64]
        anchor_raw = item.get("anchor")
        anchor = str(anchor_raw).strip()[:120] if isinstance(anchor_raw, str) and anchor_raw.strip() else None
        edges_out.append(GraphEdge(source=src, target=tgt, label=label, anchor=anchor))
    return edges_out


async def build_section_graph(
    sections: list[Section],
    *,
    provider: str | None = None,
    max_edges: int = 120,
) -> GraphResult:
    """Run the link-architect agent over a paper's sections.

    Always returns a ``GraphResult`` with a depth assigned to every section.
    On any failure path (no LLM key, parse error, network) we log and fall
    back to ``edges=[], depths={sid: 0 for ...}`` so ingest never blocks on
    graph construction.
    """
    section_ids = [s.section_id for s in sections]

    if len(sections) < 2:
        return GraphResult(edges=[], depths={sid: 0 for sid in section_ids})

    if not chat_available(provider):
        logger.info(
            "build_section_graph: chat provider %r unavailable; depths=0 fallback "
            "(%d sections).",
            provider,
            len(sections),
        )
        return GraphResult(edges=[], depths={sid: 0 for sid in section_ids})

    user = (
        f"Paper sections (ordered as in the paper, {len(sections)} total):\n"
        + _build_catalog(sections)
    )

    try:
        raw_text = await chat_json_completion(
            system=_LINK_ARCHITECT_SYSTEM,
            user=user,
            provider=provider,
        )
    except Exception:
        logger.exception("build_section_graph: link_architect LLM call failed")
        return GraphResult(edges=[], depths={sid: 0 for sid in section_ids})

    raw = load_llm_json(raw_text or "")
    if not raw:
        logger.warning(
            "build_section_graph: link_architect returned unparseable JSON "
            "(snippet=%r)",
            (raw_text or "")[:300],
        )
        return GraphResult(edges=[], depths={sid: 0 for sid in section_ids})

    edges = _parse_edges(raw, set(section_ids), max_edges=max_edges)
    depths = compute_depths(section_ids, edges)

    logger.info(
        "build_section_graph: sections=%d edges=%d max_depth=%d (provider=%s)",
        len(sections),
        len(edges),
        max(depths.values(), default=0),
        provider or "default",
    )
    return GraphResult(edges=edges, depths=depths)
