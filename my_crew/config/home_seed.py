"""First-run seeding of MY_CREW_HOME from shipped resources (installed/container mode).

A checkout runs with MY_CREW_HOME == SHIPPED_ROOT, where the shipped starter profiles
already sit in place — seeding is a no-op there. An installed package or container
resolves MY_CREW_HOME elsewhere (~/.my-crew, /data volume): the loaders only look in
home for profiles (user data), so the shipped starters must be copied in once.
Copy-if-absent only — a user-edited default profile is user data and is never
overwritten (same rule as the registry.yaml example bootstrap).
"""

from __future__ import annotations

import logging
import shutil

from my_crew.config.settings import MY_CREW_HOME, SHIPPED_ROOT

logger = logging.getLogger(__name__)

#: Shipped starter profile dirs every entrypoint expects to be loadable.
_SEED_PROFILE_DIRS = ("default", "templates")


def ensure_home_seeded() -> None:
    """Idempotent; called from every long-lived entrypoint main() (serve/web/service/CLI)."""
    if MY_CREW_HOME == SHIPPED_ROOT:
        return
    for name in _SEED_PROFILE_DIRS:
        src = SHIPPED_ROOT / "profiles" / name
        dst = MY_CREW_HOME / "profiles" / name
        if not src.is_dir() or dst.exists():
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst)
            logger.info("seeded shipped profile %r into %s", name, dst)
        except OSError:
            # Degrade loudly, don't crash startup: the loaders raise their own clear
            # FileNotFoundError if the profile is actually needed later.
            logger.warning("seeding shipped profile %r failed", name, exc_info=True)
