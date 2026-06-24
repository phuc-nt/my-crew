"""Once-only migration of the v1 `.data/` stores into `.data/agents/default/` (M1-P3).

v1 kept all stores at the top level of `.data/`. v2 isolates every agent under
`.data/agents/<id>/`, so the legacy `default` agent's stores must move down one level
to keep its v1 audit / dedup / budget / approvals / checkpoint history.

This is idempotent and allowlisted: it moves ONLY the known v1 store names, only when
`.data/agents/default/` does not yet exist (first multi-agent run), and never touches
`.data/agents/` or any unrelated file. Called at WORKER startup (not from the plain
single-agent CLI), so a user who only runs `cli report` never has data moved.
"""

from __future__ import annotations

import logging
import shutil

from src.config.settings import DATA_DIR

logger = logging.getLogger(__name__)

# The exact v1 store names (relative to .data/). Nothing else is ever touched.
_LEGACY_STORES = ("audit", "budget", "checkpoints.db", "dedup.db", "approvals.db")


def migrate_legacy_data_dir() -> bool:
    """Move v1 top-level stores into `.data/agents/default/`. Returns True if it moved.

    No-op (returns False) when already migrated (`.data/agents/default/` exists) or on a
    fresh install (no legacy stores present). Safe to call on every worker startup.
    """
    target_root = DATA_DIR / "agents" / "default"
    # The target's existence is the idempotency guard: once `default` has its own dir
    # (a prior migration, or a fresh `default` agent) we never move again, so a
    # half-migrated state is never re-touched and an existing target is never clobbered.
    # Known M1 limitation: if a first run is interrupted mid-move (microsecond window of
    # same-fs renames), any still-top-level store is STRANDED (readable at top level, not
    # lost) — never re-migrated. Accepted for M1; revisit a per-store-only scheme later.
    if target_root.exists():
        return False

    legacy_present = [name for name in _LEGACY_STORES if (DATA_DIR / name).exists()]
    if not legacy_present:
        return False  # fresh install: nothing to migrate, don't create an empty dir

    target_root.mkdir(parents=True, exist_ok=True)
    for name in legacy_present:
        shutil.move(str(DATA_DIR / name), str(target_root / name))  # same fs ⇒ rename
        logger.info("legacy migration: moved .data/%s → .data/agents/default/%s", name, name)
    return True
