"""ACE Playbook — two-tier playbook CRUD and delta operations.

Adapted from: vendor/ace/playbook_utils.py

Storage: MongoDB documents with structured bullet-point entries.

Two tiers:
- Group-level playbook: domain-specific strategies shared across the group.
  Updated by aggregated member feedback via the Reflector.
  Example bullet: "For probability concepts, derivation edges have 82%
  acceptance — prefer over analogy edges."

- Per-user playbook: individual preference overrides layered on top of the
  group playbook. Updated by that user's feedback only.
  Example bullet: "User A prefers formal mathematical explanations."

Effective context for any AI operation = group_playbook + user_overrides.

Bullet format (matches ACE upstream):
  [section_slug-00042] helpful=12 harmful=2 :: bullet content text

Operations (via MongoDB $push, $set, $pull, $addToSet):
- add_bullet(playbook_id, section, content)
- update_counts(playbook_id, bullet_id, tag)  # helpful / harmful / neutral
- merge_bullets(playbook_id, source_ids)       # combine similar bullets
- delete_bullet(playbook_id, bullet_id)
- deduplicate(playbook_id, threshold)          # embedding-based dedup
"""
