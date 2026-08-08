"""Event-driven dispatch signal (v74 phase 2): the tick poke file.

A team-step worker exiting means the coordinator has something to judge — done,
needs_decision, paused, failed all require a ruling or a next dispatch. Waiting for
the 60s cadence to notice cost a measured 253s (11% of wall-clock) on a clean 5-step
run. The poke file closes that gap: the worker touches it on every team-step exit,
and the service's sleep loop (sliced ~5s) spawns one early team-tick when the file's
mtime moves past the last handled poke.

The file's CONTENT is irrelevant — mtime is the whole signal. Both sides are
best-effort: a missing/unwritable poke degrades to the old 60s latency, never to
lost work (the minute cadence stays as the fallback and the store is the source of
truth either way).
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def poke_path() -> Path:
    from my_crew.config.settings import DATA_DIR

    return DATA_DIR / "tick.poke"


def touch_poke() -> None:
    """Signal "a team-step just finished" — atomic touch, swallow every failure."""
    try:
        path = poke_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    except Exception:  # noqa: BLE001 — a failed poke only costs the old 60s latency
        logger.warning("tick poke touch failed (falling back to the 60s cadence)",
                       exc_info=True)


def poke_mtime() -> float | None:
    """The poke file's mtime, or None when it does not exist / cannot be read."""
    try:
        return poke_path().stat().st_mtime
    except OSError:
        return None
