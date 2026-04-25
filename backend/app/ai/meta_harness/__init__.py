"""Meta-Harness — outer loop pipeline optimization.

STATUS: DORMANT for POC. Group/user knowledge-space optimization is not
needed yet. This module is reserved for the future ACE-style iterative
item refinement loop described below.

---

Original role (deferred):
  Periodic, admin-triggered whole-pipeline optimization. Reads execution
  traces, proposes config changes (model swap, prompt revision, threshold),
  evaluates on held-out data before deployment.

Future role — ACE Item Refinement Loop:
  Repurposes the Meta-Harness architecture as an iterative item quality
  loop that wraps around the POC item_construction pipeline:

  1. Generator: produces candidate items via tool-calling (same as POC).
  2. Actor (evaluator.py): solves each generated item via multiple
     solution trajectories, acting as a simulated student.
  3. Reflector: compares the Actor's solution trajectories against the
     user's selected source content. Identifies:
     - Items that are trivially solvable without the foundation concepts.
     - Items whose answers contradict the source content.
     - Items that don't actually test the intended concepts.
  4. Decision: if quality is insufficient AND iteration < 3, feed the
     Reflector's advice back to the Generator for a refined attempt.
     Otherwise, accept or reject via item_evaluation.

  Loop termination:
  - Tool-calling logic signals DONE (Reflector approves all items).
  - Maximum of 3 iterations reached.
  - All candidates rejected after 3 rounds → return empty with reason.
"""
