"""ACE Reflector — feedback distillation at both tiers.

Adapted from: vendor/ace/ace/core/reflector.py

Analyzes user interactions and distills them into playbook updates:

Personal tier (per-user playbook):
- User edits an AI-suggested edge → "this user disagrees with analogy edges"
- User rejects a concept dedup suggestion → preference signal
- User fails an item → identifies which foundation concept was weak

Group tier (group-level playbook):
- Edge acceptance rates across members → "derivation edges work well"
- Item pass/fail patterns → "code challenges are too hard for this group"
- Merge outcomes → "canonical nodes from 3+ perspectives are higher quality"

Tags playbook bullets as helpful / harmful / neutral and emits update
operations consumed by the Curator (personal) and Meta-Curator (group).
"""
