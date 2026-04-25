"""Meta-Harness evaluator — the Actor that solves generated items.

STATUS: DORMANT for POC.

Future role — Simulated Student (Actor):
  Takes each generated candidate item and attempts to solve it via
  multiple solution trajectories, simulating different student approaches:

  Trajectory types:
  - Direct solve: attempt the item using only the foundation concepts.
  - Blind solve: attempt without any concept context (tests whether the
    item is trivially solvable from general knowledge alone).
  - Wrong-path solve: deliberately use an incorrect approach to verify
    the item catches common mistakes.

  The solution trajectories are passed to the Reflector, which compares
  them against the user's source content to assess item quality.

  Uses the same LLM provider as item_construction (Groq/OpenAI/Claude).
"""
