"""Meta-Harness optimizer — diagnoses failure modes and proposes improvements.

STATUS: DORMANT for POC.

Future role — Item Refinement Proposer:
  After the Reflector identifies quality issues in generated items, the
  optimizer proposes specific improvements:
  - Rephrase the question to better target the foundation concepts.
  - Adjust difficulty based on Actor's solution trajectories.
  - Add or remove foundation concepts if coverage is wrong.
  - Suggest a different item type if the current type doesn't fit.

  Consumes: Reflector feedback, current candidate items, source content.
  Produces: revision instructions for the next Generator iteration.
"""
