# ACE — Agentic Context Engineering

## Source

- **Paper**: [Agentic Context Engineering: Evolving Contexts for Self-Improving Language Models](https://arxiv.org/abs/2510.04618) (ICLR 2026)
- **GitHub**: [ace-agent/ace](https://github.com/ace-agent/ace) (Python, Apache 2.0)

## Summary

ACE transforms static prompts into dynamic, self-improving systems. It treats contexts as evolving playbooks that accumulate, refine, and organize strategies through a modular process of generation, reflection, and curation.

### Three Roles

- **Generator** — creates reasoning trajectories and problem-solving traces for new queries, surfacing both effective tactics and observed pitfalls.
- **Reflector** — critiques outputs by comparing successful and unsuccessful trajectories, distilling domain-specific insights.
- **Curator** — maintains a structured context store with incremental, delta-based updates that preserve knowledge and avoid redundancy.

### Key Results

- +10.6% on agent tasks (matches top-ranked production agents on AppWorld leaderboard)
- +8.6% on finance/domain-specific tasks
- 86.9% lower adaptation latency compared to existing methods
- 75–83% reduction in rollouts and token costs

### Key Innovation

ACE addresses **brevity bias** (dropping domain insights for conciseness) and **context collapse** (iterative rewriting eroding details) by using structured, incremental updates rather than monolithic rewrites.

## Applicability to This Platform

ACE maps to the **inner loop** of the AI optimization architecture (see plan.md Section 9.1):

| ACE Role | Platform Mapping |
|---|---|
| **Generator** | When a new concept enters a group region, propose candidate edges with drafted markdown bodies and candidate items. |
| **Reflector** | Compare AI-generated edges/items against user feedback (accepted, rejected, edited). Identify which strategies work for this group's domain. |
| **Curator** | Maintain and evolve the per-group context store. Preserve accumulated domain insight (e.g., "in this math course, derivation edges are more useful than analogy edges") without context collapse. |

ACE's delta-based updates are critical for long-lived groups (e.g., a semester-long course) where the context store accumulates hundreds of edge-generation strategies over time.
