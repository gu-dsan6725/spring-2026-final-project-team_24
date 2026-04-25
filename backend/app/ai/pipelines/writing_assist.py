"""Writing assist pipeline — proofread and refine user concept drafts.

This is one of the two roles that replace ACE's original Generator in
our platform (the other being item_construction).

Lightweight, optional pipeline triggered when a user requests help with
their concept note. The user always owns the content — this only suggests
improvements.

Capabilities:
- Proofread markdown for clarity, grammar, and structure.
- Suggest LaTeX formatting for mathematical expressions.
- Flag missing definitions or assumed prerequisites.
- Respect per-user playbook style preferences (formal vs. intuitive,
  verbose vs. concise, etc.).

Uses the group's configured chat provider (OpenAI, Anthropic, or local LLM).
"""
