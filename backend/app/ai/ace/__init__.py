"""ACE — Agentic Context Engineering (inner loop).

Adapted from: https://github.com/ace-agent/ace (vendor/ace/)

Two roles + playbook manager operating on two-tier playbooks (group + per-user):

- Curator: manages each user's personal knowledge pool — embed-on-write,
  personal dedup detection, quality signals. Operates on the per-user tier.

- Meta-Curator: group landscape gatekeeper — "gated push" from personal
  graphs to canonical landscape. Enforces convergence threshold, three-band
  similarity routing, canonical node synthesis. Operates on the group tier.

- Reflector: distills user feedback (edge accept/reject, item pass/fail,
  concept edits) into playbook updates at both tiers.

- Playbook: MongoDB-backed two-tier playbook CRUD with delta operations.

The original ACE Generator role is not mapped here — it is split across
purpose-specific pipelines in app.ai.pipelines (writing_assist,
item_construction, connection_inference, etc.).
"""
