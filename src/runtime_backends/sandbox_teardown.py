"""Sandbox teardown registry (v20.5 Phase 3, red-team C6).

A deep-agent step spawns a sandbox container. The team-step worker is a detached subprocess
killed by SIGKILL when its 600s lease expires — SIGKILL runs no `finally`/`atexit`, so this
best-effort teardown (called on the normal path) never runs for a lease-killed worker. Three
layers cover the orphan case: the container self-terminates (`sleep 600`), Docker `auto_remove`
deletes it once it exits, and the ticker's active reaper (`sandbox_reaper`) removes any
still-running container older than the lease window. So an orphaned container is cleaned within
the lease window, not left for an hour.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def teardown_sandbox(backend: Any) -> None:
    """Best-effort teardown of a sandbox backend (called on the normal completion path).

    Never raises — a teardown failure must not fail the step (the container self-destructs via
    its own idle ceiling regardless). Logs so an operator can see leaks.
    """
    if backend is None:
        return
    fn = getattr(backend, "teardown", None)
    if fn is None:
        return
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 — teardown is best-effort
        logger.warning("sandbox teardown failed (container may linger until idle ceiling): %s", exc)
