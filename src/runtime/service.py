"""Coordinating service daemon + scheduler (v2 M1-P3, D1).

A long-running process that reads `registry.yaml`, reads each agent's `schedule:`
(profile.yaml cron strings), and on a schedule spawns + supervises one per-agent worker
subprocess per due report — replacing v1's global launchd plists. An agent runs only
when BOTH its registry `enabled` and its profile `enabled` are true.

All scheduling logic is the pure `scheduler.due_reports`; this module adds the daemon
loop, the worker spawn, supervision (600s timeout + a concurrency cap), and outcome
collection. `spawn` is injectable so tests assert the exact worker argv with no real
process and a fixed clock — `run_forever` (the only timing-dependent part) is a thin
untested wrapper over the unit-tested `run_tick`.
"""

from __future__ import annotations

import logging
import subprocess  # noqa: S404 — spawning the worker is the service's whole job
import sys
import time
from collections.abc import Callable
from datetime import datetime

from src.profile.loader import load_profile
from src.runtime.registry import load_registry
from src.runtime.run_event import read_last_run_event
from src.runtime.scheduler import due_reports

logger = logging.getLogger(__name__)

_WORKER_TIMEOUT_S = 600  # kill a worker that runs longer than this (then status=timeout)
_CONCURRENCY_CAP = 4  # max worker subprocesses spawned per tick (excess defers to next tick)
_TICK_INTERVAL_S = 60  # how often run_forever evaluates the schedule

Spawn = Callable[[list[str]], "subprocess.Popen"]


def _real_spawn(argv: list[str]) -> subprocess.Popen:
    """Default spawn: launch the worker as a child process.

    argv is a list (no shell) and the agent id was validated at the registry boundary
    (`load_registry` enforces the id rule), so no shell-injection / path-escape is
    possible from a registry id.
    """
    return subprocess.Popen(argv)  # noqa: S603


def _effective_schedule(loaded) -> tuple[dict[str, str], tuple[str, ...]]:
    """The agent's cron schedule + reports gate, with the inbox poll folded in.

    Any configured inbox transport (Slack `inbox:` block — M11 — and/or `telegram:`
    block — v6 M13) synthesizes a pseudo-kind `inbox` at the fastest transport's
    `*/poll_minutes` and admits it through the reports gate — reusing the one scheduler
    path instead of a second polling loop. No transport ⇒ profile values unchanged.
    """
    from src.runtime.inbox_dispatch import has_any_inbox, inbox_poll_minutes

    if not has_any_inbox(loaded):
        return loaded.schedule, loaded.reports
    schedule = dict(loaded.schedule)
    schedule["inbox"] = f"*/{inbox_poll_minutes(loaded)} * * * *"
    return schedule, (*loaded.reports, "inbox")


def _worker_argv(agent_id: str, kind: str, audience: str) -> list[str]:
    return [
        sys.executable, "-m", "src.runtime.worker",
        "--agent-id", agent_id, "--report", kind, "--audience", audience,
    ]


def _supervise(spawn: Spawn, argv: list[str], *, timeout: int) -> dict:
    """Spawn one worker, wait up to `timeout`, return its outcome.

    On timeout: kill + `status="timeout"`. Else collect the exit code + the agent's
    last `runs.jsonl` line (so the caller has both the coarse signal and the detail).
    """
    proc = spawn(argv)
    try:
        exit_code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        return {"status": "timeout", "exit_code": None}
    agent_id = argv[argv.index("--agent-id") + 1]
    return {"status": "ran", "exit_code": exit_code, "detail": _last_run_event(agent_id)}


def _last_run_event(agent_id: str) -> dict | None:
    """Read the last line of the agent's runs.jsonl (the just-finished run's detail).

    Thin wrapper over the shared `run_event.read_last_run_event` (M2-P6 lifted the
    body there so the web service does not import a service-private). Kept as a name
    so existing callers/tests that patch `service._last_run_event` are unaffected.
    """
    return read_last_run_event(agent_id)


class Service:
    """Holds the in-memory `last_fire` map across ticks (per (agent_id, kind))."""

    def __init__(self, *, timeout: int = _WORKER_TIMEOUT_S, cap: int = _CONCURRENCY_CAP) -> None:
        self._last_fire: dict[tuple[str, str], datetime] = {}
        self._seeded = False
        self._timeout = timeout
        self._cap = cap

    def _seed(self, now: datetime) -> None:
        """Seed last_fire for every scheduled (agent, kind) to `now` so a fresh daemon
        does not back-fire every past cron occurrence."""
        for entry in load_registry():
            if not entry.enabled:
                continue
            loaded = load_profile(entry.id)
            if not loaded.enabled:
                continue
            schedule, _ = _effective_schedule(loaded)
            for kind in schedule:
                self._last_fire.setdefault((entry.id, kind), now)
        self._seeded = True

    def run_tick(self, now: datetime, *, spawn: Spawn = _real_spawn) -> list[dict]:
        """Evaluate the schedule once at `now`; spawn due workers (up to the cap)."""
        if not self._seeded:
            self._seed(now)
        outcomes: list[dict] = []
        spawned = 0
        for entry in load_registry():
            if not entry.enabled:
                continue
            loaded = load_profile(entry.id)
            if not loaded.enabled:
                continue
            schedule, reports = _effective_schedule(loaded)
            per_kind = {k: self._last_fire[(entry.id, k)]
                        for k in schedule if (entry.id, k) in self._last_fire}
            for kind, audience in due_reports(schedule, reports, now, per_kind):
                if spawned >= self._cap:
                    logger.info("tick cap %d reached; deferring %s/%s", self._cap, entry.id, kind)
                    break
                argv = _worker_argv(entry.id, kind, audience)
                outcome = _supervise(spawn, argv, timeout=self._timeout)
                outcome.update(agent_id=entry.id, kind=kind)
                outcomes.append(outcome)
                self._last_fire[(entry.id, kind)] = now  # advance: no re-fire this period
                spawned += 1
            if spawned >= self._cap:
                break
        return outcomes

    def run_forever(self, *, interval: int = _TICK_INTERVAL_S) -> None:  # pragma: no cover
        """The daemon loop: tick, sleep, repeat. Thin wrapper over run_tick.

        Uses naive LOCAL time (`datetime.now()`) to match how the cron `schedule:`
        strings are interpreted (local, like launchd) — a `"0 8 * * *"` fires at 08:00
        local, not UTC.
        """
        logger.info("service started; tick interval %ds", interval)
        while True:
            self.run_tick(datetime.now())  # noqa: DTZ005 — local time, matches cron intent
            time.sleep(interval)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = argv if argv is not None else sys.argv[1:]
    service = Service()
    if "--once" in args:
        outcomes = service.run_tick(datetime.now())  # noqa: DTZ005 — local, matches cron intent
        logger.info("one tick: %d worker(s) spawned", len(outcomes))
        return 0
    service.run_forever()  # pragma: no cover — runs until killed
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
