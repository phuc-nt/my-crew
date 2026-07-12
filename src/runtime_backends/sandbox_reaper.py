"""Reap orphaned deep_agent sandbox containers.

A sandbox container is torn down on the normal path, but a worker that is SIGKILL'd on lease
expiry runs no cleanup — its container orphans. Two backstops cover that: the container is
started with a short self-terminating `sleep` + `auto_remove` (so a normally-exited or
self-terminated container is removed by Docker itself), and this reaper, which the ticker runs
each tick to remove any STILL-RUNNING orphan whose age exceeds the lease window.

Division of labor: `auto_remove` handles containers that exited on their own (they vanish from
the listing). This reaper handles the remaining case — a container still running past the point
where its worker must already be dead — by age + our own label, never by name or image.

Best-effort by contract: Docker unavailable, a hung socket, or a parse error must never raise
into the ticker (which also spawns report/team-tick workers). A bounded client timeout keeps a
slow daemon from stalling the tick.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from src.runtime.team_task_store import DEFAULT_LEASE_TTL_S

logger = logging.getLogger(__name__)

#: Label stamped on every sandbox container, so the reaper only ever touches our own containers.
SANDBOX_LABEL = "mycrew-sandbox"
SANDBOX_LABEL_VALUE = "1"

#: Grace beyond the lease TTL before a still-running container is considered a dead-worker orphan.
#: Must exceed one ticker interval + jitter so a container whose worker the ticker has not yet
#: lease-killed (a delayed tick) is not removed mid-exec. Two intervals + a minute is comfortable.
_TICK_INTERVAL_S = 60
_DEFAULT_GRACE_S = 2 * _TICK_INTERVAL_S + 60

#: Low client timeout so a hung Docker socket degrades to a no-op instead of freezing the tick.
_DOCKER_TIMEOUT_S = 5


def _parse_docker_created(created: str) -> datetime:
    """Parse Docker's `Created` timestamp into an aware UTC datetime.

    Docker emits RFC3339 with 9-digit NANOSECONDS + `Z` (e.g. `2026-07-12T10:04:33.123456789Z`).
    `datetime.fromisoformat` rejects 9-digit fractional seconds (it accepts only 3 or 6), so the
    sub-second field is truncated to microseconds and the trailing `Z` normalized before parsing.
    A naive `fromisoformat` here would raise on every real container and silently disable the
    reaper.
    """
    s = created.strip()
    # Truncate a >6-digit fractional-seconds field to 6 digits.
    s = re.sub(r"(\.\d{6})\d+", r"\1", s)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).astimezone(UTC)


def reap_orphaned_sandboxes(
    *, ttl_s: int = DEFAULT_LEASE_TTL_S, grace_s: int = _DEFAULT_GRACE_S, client=None
) -> int:
    """Remove still-running sandbox containers older than `ttl_s + grace_s`. Returns count reaped.

    Only containers carrying our label AND older than the threshold are touched (label + age
    double-gate against false-killing a live worker's fresh sandbox). Never raises: Docker
    unavailable → 0; a per-container failure is isolated and skips that container.
    """
    try:
        if client is None:
            import docker  # optional dep
            client = docker.from_env(timeout=_DOCKER_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 — Docker absent/unreachable is a clean no-op
        logger.info("sandbox reaper: Docker unavailable, skipping (%s)", exc)
        return 0

    threshold_s = ttl_s + grace_s
    reaped = 0
    try:
        containers = client.containers.list(
            all=True, filters={"label": f"{SANDBOX_LABEL}={SANDBOX_LABEL_VALUE}"}
        )
    except Exception as exc:  # noqa: BLE001 — listing failed (hung/slow socket) → no-op
        logger.warning("sandbox reaper: container list failed, skipping (%s)", exc)
        return 0

    now = datetime.now(UTC)
    for container in containers:
        try:
            created = (getattr(container, "attrs", {}) or {}).get("Created")
            if not created:
                continue  # unknown age → conservatively leave it
            age_s = (now - _parse_docker_created(created)).total_seconds()
            if age_s > threshold_s:
                container.remove(force=True)
                reaped += 1
        except Exception as exc:  # noqa: BLE001 — one bad container never aborts the sweep
            logger.warning("sandbox reaper: could not reap a container: %s", exc)
    if reaped:
        logger.info("sandbox reaper: removed %d orphaned container(s)", reaped)
    return reaped
