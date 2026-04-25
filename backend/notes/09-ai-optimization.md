# AI Optimization Architecture

The AI services improve over time through a dual-loop optimization system.

## Inner Loop — ACE (Agentic Context Engineering)

ACE operates at **two tiers** — group-level and per-user — using structured JSON playbooks with delta updates.

### Two-Tier Context Store

**Group-level playbook** — domain-specific strategies shared across the group. Updated by aggregated member feedback. Example: "In this statistics course, derivation edges have 82% acceptance rate — prefer over analogy edges."

**Per-user playbook** — individual preference overrides layered on top of the group playbook. Updated by that user's feedback only. Example: "User A prefers formal mathematical explanations; User B prefers intuitive application-based ones."

When generating an edge or item for User A in Group X, the effective context is: `group_X_playbook + user_A_overrides`.

### Playbook Format (MongoDB Document)

Each playbook is a JSON document of structured bullet points with metadata, following ACE's original design:

```json
{
  "playbook_id": "group_stats101",
  "bullets": [
    {
      "id": "b_001",
      "content": "For probability concepts, derivation edges have 82% acceptance",
      "usage_count": 47,
      "success_rate": 0.82,
      "created_at": "2026-02-15",
      "last_validated": "2026-03-20",
      "status": "active"
    }
  ]
}
```

The Curator applies delta updates: `$push` new bullets, `$set` to update usage counts, `$pull` to retire outdated ones. Periodic deduplication via semantic embeddings removes redundant bullets. The playbook is never rewritten wholesale — this prevents context collapse.

### ACE Roles

- **Generator**: when a convergence event fires ([Merging](04-merging.md)), proposes canonical node structure, candidate edges with drafted markdown bodies, and candidate items. For per-user: proposes personalized edge explanations and item difficulty.
- **Reflector**: compares AI-generated edges/items against user feedback (accepted, rejected, edited). Distills which strategies work at group level vs. individual level.
- **Curator**: maintains both playbooks with incremental delta-based updates. Group insights propagate to all members; individual insights stay scoped to that user.

ACE is triggered by convergence events and user writes — lightweight, continuous.

Reference: [ACE paper (ICLR 2026)](https://arxiv.org/abs/2510.04618) | [GitHub](https://github.com/ace-agent/ace) | [Platform reference](../references/ace-agentic-context-engineering.md)

## Outer Loop — Meta-Harness

Periodic, admin-triggered whole-pipeline optimization.

- Reads full execution traces of the group's AI pipelines: which embeddings were used, what prompts generated items, what scores/feedback resulted.
- An agentic proposer diagnoses failure modes from the traces and proposes new pipeline configurations (embedding model swap, prompt template revision, threshold adjustment).
- New configurations are evaluated on held-out data before deployment.

This runs periodically or when metrics plateau — heavier, less frequent.

Reference: [Meta-Harness paper](https://arxiv.org/abs/2603.28052) | [GitHub](https://github.com/stanford-iris-lab/meta-harness-tbench2-artifact) | [Platform reference](../references/meta-harness.md)

## Loop Interaction

The inner loop (ACE) operates within a pipeline configuration. The outer loop (Meta-Harness) optimizes the configuration itself. When Meta-Harness deploys a new configuration, ACE's group-level context store resets or adapts to the new pipeline; per-user stores may be preserved if the change is backward-compatible.

> *[Detailed design deferred]* — Trigger conditions for the outer loop, evaluation metrics, rollback strategy, cost budgets for optimization runs.
