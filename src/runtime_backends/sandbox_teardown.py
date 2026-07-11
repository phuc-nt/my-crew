"""Sandbox teardown registry (v20.5 Phase 3, red-team C6).

A deep-agent step spawns a sandbox container. The team-step worker is a detached subprocess
killed by SIGKILL when its 600s lease expires — SIGKILL runs no `finally`/`atexit`, so a naive
teardown would leak the container (still consuming resources). This registry gives the runtime a
best-effort teardown it calls on the normal path, and documents the SIGKILL gap: the real
backstop against an orphaned container is the container's OWN self-destruct (the Docker backend
runs `sleep 3600`, so an orphan dies within an hour on its own — an idle ceiling well under a
runaway's cost, and the operator can `docker ps`/`docker rm` to reap sooner).
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
