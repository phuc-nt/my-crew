"""First-run seeding of MY_CREW_HOME from shipped resources (installed/container mode).

A checkout runs with MY_CREW_HOME == SHIPPED_ROOT, where the shipped starter profiles
already sit in place — seeding is a no-op there. An installed package or container
resolves MY_CREW_HOME elsewhere (~/.my-crew, /data volume): the PROFILE loaders only
look in home (user data), so the shipped `default` starter must be copied in once.
`profiles/templates` is NOT seeded — every template consumer (one-click create,
template skills) reads SHIPPED_ROOT directly, so a home copy would be dead data.
Copy-if-absent only — a user-edited default profile is user data and is never
overwritten (same rule as the registry.yaml example bootstrap). The copy lands via
a temp dir + atomic rename so an interrupted first boot can never leave a
half-seeded profile that blocks re-seeding forever.
"""

from __future__ import annotations

import logging
import shutil

from my_crew.config.settings import MY_CREW_HOME, SHIPPED_ROOT

logger = logging.getLogger(__name__)

#: Shipped starter profile dirs every entrypoint expects to be loadable.
_SEED_PROFILE_DIRS = ("default",)


def ensure_home_seeded() -> None:
    """Idempotent; called from every long-lived entrypoint main() (serve/web/service/CLI)."""
    if MY_CREW_HOME == SHIPPED_ROOT:
        return
    for name in _SEED_PROFILE_DIRS:
        src = SHIPPED_ROOT / "profiles" / name
        dst = MY_CREW_HOME / "profiles" / name
        if not src.is_dir() or dst.exists():
            continue
        tmp = dst.with_name(dst.name + ".seeding")
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.rmtree(tmp, ignore_errors=True)  # leftover from an interrupted boot
            shutil.copytree(src, tmp)
            tmp.rename(dst)  # atomic on the same fs — dst is complete or absent
            logger.info("seeded shipped profile %r into %s", name, dst)
        except OSError:
            # Lost the rename race to a sibling process, or fs trouble: clean the temp
            # and degrade loudly — the loaders raise their own clear FileNotFoundError
            # if the profile is actually needed later.
            shutil.rmtree(tmp, ignore_errors=True)
            if dst.exists():
                continue
            logger.warning("seeding shipped profile %r failed", name, exc_info=True)
