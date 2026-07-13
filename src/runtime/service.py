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
    from src.runtime.task_scheduling import has_open_tasks, tasks_cron

    schedule = dict(loaded.schedule)
    reports = list(loaded.reports)
    changed = False
    if has_any_inbox(loaded):
        schedule["inbox"] = f"*/{inbox_poll_minutes(loaded)} * * * *"
        reports.append("inbox")
        changed = True
    # v6 M15: an agent with open assigned tasks synthesizes a `tasks` pseudo-kind that the
    # runner services on a cadence (per-day reminder dedup bounds it to one/day per task).
    if has_open_tasks(loaded):
        schedule["tasks"] = tasks_cron(loaded)
        reports.append("tasks")
        changed = True
    # v8 M21: the admin agent (fleet overseer with a CEO DM) runs an `ops-alerts` health
    # tick every 6h — computes team_alerts and pushes "agent chết ngầm" to the CEO. The
    # per-(agent,kind,day) dedup bounds a still-failing agent to one ping per day.
    if getattr(loaded, "domain", "") == "admin" and getattr(loaded.config, "telegram", None):
        schedule["ops-alerts"] = "0 */6 * * *"
        reports.append("ops-alerts")
        changed = True
    # v12 M29: the same admin agent runs a `milestone-mirror` tick every 15min — DMs the
    # CEO only `kind == "milestone"` office-room events (nhận việc / hoàn thành / cần
    # duyệt). Tighter cadence than ops-alerts (health issues can wait 6h; a CEO watching
    # a task's progress on Telegram wants it sooner).
    if getattr(loaded, "domain", "") == "admin" and getattr(loaded.config, "telegram", None):
        schedule["milestone-mirror"] = "*/15 * * * *"
        reports.append("milestone-mirror")
        changed = True
    # v12 M28b: the coordinator agent (company.yaml::coordinator_id) runs a `team-tick`
    # every minute — a short poll (read store, take ONE action, exit), not a report.
    # Only the ONE agent configured as coordinator gets this pseudo-kind; every other
    # agent's schedule is unaffected (byte-identical to pre-M28b for them).
    from src.runtime.company import load_company

    company = load_company()
    # getattr: a degraded/partial profile object (or a test double) may lack the id —
    # an unidentifiable agent simply never gets the coordinator pseudo-kind.
    if company.coordinator_id and getattr(loaded, "profile_id", None) == company.coordinator_id:
        schedule["team-tick"] = "* * * * *"
        reports.append("team-tick")
        changed = True
    # v31 P5 wake-gate: an agent with declared `watchers:` gets a `watch` pseudo-kind —
    # a NO-LLM poll tick (read source → hash → wake only on diff). Agents without
    # watchers keep a byte-identical schedule, like the coordinator check above.
    if getattr(loaded, "watchers", None):
        schedule["watch"] = "*/5 * * * *"
        reports.append("watch")
        changed = True
    if not changed:
        return loaded.schedule, loaded.reports  # byte-identical when nothing synthesized
    return schedule, tuple(reports)


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


def _reap_sandboxes_best_effort() -> None:
    """Sweep orphaned deep_agent sandbox containers once per tick (best-effort).

    Runs in the ticker's own process — the single long-lived scheduler — rather than a second
    daemon that could race the store. It must never raise or block the tick: the reaper is itself
    best-effort (Docker-unavailable → no-op, bounded socket timeout), and this wrapper is a final
    guard so a reaper bug cannot stall report/team-tick spawning.
    """
    try:
        from src.runtime_backends.sandbox_reaper import reap_orphaned_sandboxes

        reap_orphaned_sandboxes()
    except Exception as exc:  # noqa: BLE001 — telemetry cleanup must never break the scheduler
        logger.warning("sandbox reaper sweep failed (ignored): %s", exc)


#: Local hour the nightly memory-consolidation sweep may run (03:00–03:59 — outside
#: working hours, so the sweep never races a remember-node write from an active step;
#: the per-agent 24h cooldown inside the sweep keeps it to one LLM attempt per night).
_MEMORY_SWEEP_HOUR = 3


def _consolidate_memories_best_effort(now: datetime) -> None:
    """Nightly MEMORY.md consolidation sweep (v35 P2), same contract as the reaper:
    runs in the scheduler's own process and must never raise or block the tick."""
    if now.hour != _MEMORY_SWEEP_HOUR:
        return
    try:
        from src.memory.consolidation import run_consolidation_sweep

        run_consolidation_sweep(now=now)
    except Exception as exc:  # noqa: BLE001 — maintenance must never break the scheduler
        logger.warning("memory consolidation sweep failed (ignored): %s", exc)


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
            # v18 (red-team C1): seed-at-discovery — an agent REGISTERED AFTER daemon
            # start (the web register button / append_registry) gets its schedule
            # baseline the first tick that sees it, instead of never firing until a
            # restart. Same "seed to now, no back-fire" semantics `_seed` gives a
            # fresh daemon; an already-seeded pair is untouched.
            for kind in schedule:
                self._last_fire.setdefault((entry.id, kind), now)
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
        _reap_sandboxes_best_effort()
        _consolidate_memories_best_effort(now)
        return outcomes

    def run_forever(self, *, interval: int = _TICK_INTERVAL_S) -> None:  # pragma: no cover
        """The daemon loop: tick, sleep, repeat. Thin wrapper over run_tick.

        Uses naive LOCAL time (`datetime.now()`) to match how the cron `schedule:`
        strings are interpreted (local, like launchd) — a `"0 8 * * *"` fires at 08:00
        local, not UTC.
        """
        logger.info("service started; tick interval %ds", interval)
        while True:
            _write_coordinator_heartbeat()
            self.run_tick(datetime.now())  # noqa: DTZ005 — local time, matches cron intent
            time.sleep(interval)


def _write_coordinator_heartbeat() -> None:
    """v16: touch `DATA_DIR/coordinator.heartbeat` each SERVICE loop pass — the signal
    `/api/health/coordinator` reads to tell the CEO whether the dispatch engine is
    alive at all (the "task giao xong kẹt im lặng" root cause). Written from the LOOP,
    not from a worker's team-tick body: a long sequential worker run must not make the
    service look dead. try/degrade — a heartbeat write failure never stops the loop."""
    try:
        from src.config.settings import DATA_DIR

        path = DATA_DIR / "coordinator.heartbeat"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    except Exception:  # noqa: BLE001
        logger.warning("coordinator heartbeat write failed", exc_info=True)


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
