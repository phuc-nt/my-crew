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

A tick spawns every due worker first and only then waits on them (v72), so its cost is
one worker's runtime rather than the sum. The cap still bounds how many run at once.
"""

from __future__ import annotations

import logging
import os
import subprocess  # noqa: S404 — spawning the worker is the service's whole job
import sys
import time
from collections.abc import Callable
from datetime import datetime

from my_crew.profile.loader import load_profile
from my_crew.runtime.registry import load_registry
from my_crew.runtime.run_event import read_last_run_event
from my_crew.runtime.scheduler import due_reports

logger = logging.getLogger(__name__)

_WORKER_TIMEOUT_S = 600  # kill a worker that runs longer than this (then status=timeout)
_CONCURRENCY_CAP = 4  # max worker subprocesses spawned per tick (excess defers to next tick)
_TICK_INTERVAL_S = 60  # how often run_forever evaluates the schedule
_POKE_SLICE_S = 5  # sleep-slice width: worst-case latency from team-step exit to team-tick

Spawn = Callable[[list[str]], "subprocess.Popen"]


def _real_spawn(argv: list[str]) -> subprocess.Popen:
    """Default spawn: launch the worker as a child process.

    argv is a list (no shell) and the agent id was validated at the registry boundary
    (`load_registry` enforces the id rule), so no shell-injection / path-escape is
    possible from a registry id.
    """
    return subprocess.Popen(argv)  # noqa: S603


#: Kinds exempt from the per-tick spawn cap (see `run_tick`): time-critical bodies
#: whose whole point is punctuality. Keep this set tiny — everything here bypasses the
#: load bound.
#:
#: `milestone-mirror` qualifies on the same grounds as `reminder-sweep`: it reads the
#: office room and DMs the CEO — one SQLite query plus one HTTP call, no LLM. Deferring
#: it defeats its only purpose (the CEO learning a task's state while it still matters).
#:
#: `team-tick` is the coordinator's control loop: it is what notices a finished/failed
#: step and decides the next one. Unlike the other two it CAN call an LLM (stuck
#: judgement, aggregation), but there is exactly one coordinator, so the extra load is
#: bounded at one worker per tick. Holding it behind the cap starves the whole team
#: pipeline deterministically — measured: with 11 enabled agents and 5 inbox pollers at
#: cap 4, a failed step waited >3h for its ruling because team-tick deferred every tick.
_CAP_EXEMPT_KINDS = frozenset({"reminder-sweep", "milestone-mirror", "team-tick"})


def _effective_schedule(loaded) -> tuple[dict[str, str], tuple[str, ...]]:
    """The agent's cron schedule + reports gate, with the inbox poll folded in.

    Any configured inbox transport (Slack `inbox:` block — M11 — and/or `telegram:`
    block — v6 M13) synthesizes a pseudo-kind `inbox` at the fastest transport's
    `*/poll_minutes` and admits it through the reports gate — reusing the one scheduler
    path instead of a second polling loop. No transport ⇒ profile values unchanged.
    """
    from my_crew.runtime.inbox_dispatch import has_any_inbox, inbox_poll_minutes
    from my_crew.runtime.task_scheduling import has_open_tasks, tasks_cron

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
    # v12 M29: the same admin agent runs a `milestone-mirror` tick — DMs the CEO only
    # `kind == "milestone"` office-room events (nhận việc / hoàn thành / cần duyệt /
    # kẹt / bỏ cuộc). Runs EVERY minute: a milestone is by definition the moment the CEO
    # needs to know, and a 15-minute floor meant a 22-minute task reported twice with a
    # blind stretch between. No LLM in the body — it exits immediately when the room has
    # no new milestone — and it is cap-exempt so the tick cap cannot defer it.
    if getattr(loaded, "domain", "") == "admin" and getattr(loaded.config, "telegram", None):
        schedule["milestone-mirror"] = "* * * * *"
        reports.append("milestone-mirror")
        changed = True
    # v12 M28b: the coordinator agent (company.yaml::coordinator_id) runs a `team-tick`
    # every minute — a short poll (read store, take ONE action, exit), not a report.
    # Only the ONE agent configured as coordinator gets this pseudo-kind; every other
    # agent's schedule is unaffected (byte-identical to pre-M28b for them).
    from my_crew.runtime.company import load_company

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
    # v65: an agent with PENDING timed reminders gets a per-minute `reminder-sweep`
    # pseudo-kind (no-LLM: read due rows → telegram_send → mark sent). Synthesized only
    # while pending rows exist — the store probe is a cheap SQLite read (False without
    # even creating the file), so agents that never set a reminder keep a byte-identical
    # schedule. `_effective_schedule` runs per tick, so a reminder created a moment ago
    # is picked up on the next tick without any restart.
    if getattr(getattr(loaded, "config", None), "telegram", None) is not None:
        from my_crew.runtime.agent_paths import agent_data_dir
        from my_crew.runtime.reminder_store import has_pending_reminders

        profile_id = getattr(loaded, "profile_id", "")
        if profile_id and has_pending_reminders(agent_data_dir(profile_id)):
            schedule["reminder-sweep"] = "* * * * *"
            reports.append("reminder-sweep")
            changed = True
    # v68: an agent with `heartbeat: {every: 30m}` in its profile gets a proactive
    # `secretary-heartbeat` pseudo-kind. OFF unless the key is present, so every existing
    # agent keeps a byte-identical schedule. Needs a CEO DM to have anywhere to speak.
    #
    # A pulse that failed MAX_CONSECUTIVE_FAILURES times in a row turns itself off by
    # writing the store, not the profile — so the cron simply stops being synthesized on
    # the very next tick, with no restart and no rewrite of the CEO's yaml. Same cheap
    # probe shape as the reminder sweep: no file ⇒ False without creating the DB.
    heartbeat_minutes = getattr(loaded, "heartbeat_every_minutes", None)
    if heartbeat_minutes and getattr(getattr(loaded, "config", None), "telegram", None):
        from my_crew.runtime.agent_paths import agent_data_dir
        from my_crew.runtime.heartbeat_state_store import heartbeat_disabled

        profile_id = getattr(loaded, "profile_id", "")
        if not (profile_id and heartbeat_disabled(agent_data_dir(profile_id))):
            schedule["secretary-heartbeat"] = _heartbeat_cron(heartbeat_minutes)
            reports.append("secretary-heartbeat")
            changed = True
    if not changed:
        return loaded.schedule, loaded.reports  # byte-identical when nothing synthesized
    return schedule, tuple(reports)


def _heartbeat_cron(minutes: int) -> str:
    """Cadence in minutes → a 5-field cron the scheduler already understands.

    Under an hour this is a minute-step (`*/30 * * * *`). At or above it, a minute-step
    would be wrong — `*/90` is not a valid minute field — so it becomes an hour-step
    pinned to minute 0, rounding DOWN to whole hours (a heartbeat that fires slightly
    more often than asked is harmless; one that skips a window is not).
    """
    if minutes < 60:
        return f"*/{minutes} * * * *"
    hours = minutes // 60
    return "0 * * * *" if hours == 1 else f"0 */{hours} * * *"


def _worker_argv(agent_id: str, kind: str, audience: str) -> list[str]:
    return [
        sys.executable, "-m", "my_crew.runtime.worker",
        "--agent-id", agent_id, "--report", kind, "--audience", audience,
    ]


def _collect(proc, argv: list[str], *, timeout: int) -> dict:
    """Wait up to `timeout` on an ALREADY-SPAWNED worker; return its outcome.

    On timeout: kill + `status="timeout"`. Else collect the exit code + the agent's
    last `runs.jsonl` line (so the caller has both the coarse signal and the detail).

    Split out of `_supervise` so a caller with several due workers can start them all
    BEFORE waiting on any (see `run_tick`) — waiting is the part that must not be
    serialized, spawning is cheap.
    """
    try:
        exit_code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        return {"status": "timeout", "exit_code": None}
    agent_id = argv[argv.index("--agent-id") + 1]
    return {"status": "ran", "exit_code": exit_code, "detail": _last_run_event(agent_id)}


def _supervise(spawn: Spawn, argv: list[str], *, timeout: int) -> dict:
    """Spawn ONE worker and wait for it. The one-shot path (`mpm agent run`, `mpm
    resume`, the telegram listener thread) where there is nothing to overlap with."""
    return _collect(spawn(argv), argv, timeout=timeout)


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
        from my_crew.runtime_backends.sandbox_reaper import reap_orphaned_sandboxes

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
        from my_crew.memory.consolidation import run_consolidation_sweep

        run_consolidation_sweep(now=now)
    except Exception as exc:  # noqa: BLE001 — maintenance must never break the scheduler
        logger.warning("memory consolidation sweep failed (ignored): %s", exc)


def _archive_stale_skills_best_effort(now: datetime) -> None:
    """Nightly skill-curator archive sweep (v38 #2) — same nightly window + best-effort
    contract as memory consolidation; never raises or blocks the tick."""
    if now.hour != _MEMORY_SWEEP_HOUR:
        return
    try:
        from my_crew.skills.skill_curator import run_skill_archive_sweep

        run_skill_archive_sweep(now=now)
    except Exception as exc:  # noqa: BLE001 — maintenance must never break the scheduler
        logger.warning("skill archive sweep failed (ignored): %s", exc)


class Service:
    """Holds the in-memory `last_fire` map across ticks (per (agent_id, kind))."""

    def __init__(self, *, timeout: int = _WORKER_TIMEOUT_S, cap: int = _CONCURRENCY_CAP) -> None:
        self._last_fire: dict[tuple[str, str], datetime] = {}
        self._seeded = False
        self._timeout = timeout
        self._cap = cap
        #: Rotating start offset into the registry (see `run_tick`). Without it the cap
        #: is refilled by the SAME first agents every tick and anyone ordered after them
        #: starves deterministically, not occasionally.
        self._rotate = 0
        #: v74 phase 2: mtime of the last HANDLED tick poke. None until the first look,
        #: which adopts whatever is on disk as already-handled — a poke left over from
        #: before this daemon started must not fire a spurious team-tick at startup.
        self._poke_watermark: float | None = None

    def _seed(self, now: datetime) -> None:
        """Seed last_fire for every scheduled (agent, kind) to `now` so a fresh daemon
        does not back-fire every past cron occurrence."""
        for entry in load_registry():
            if not entry.enabled:
                continue
            # A registry entry whose profile dir is missing (e.g. the shipped example
            # registers `admin` before the user created that profile) must not kill
            # the whole fleet loop — skip loudly, the other agents keep running.
            try:
                loaded = load_profile(entry.id)
            except FileNotFoundError as exc:
                logger.warning("skipping agent %r: %s", entry.id, exc)
                continue
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
        # Workers started this tick, in spawn order: (proc, argv, agent_id, kind). They
        # are collected AFTER the traversal — see the drain below.
        running: list[tuple] = []
        # Rotate the traversal start each tick. The cap bounds how many workers spawn,
        # not WHO gets to spawn — a fixed start order silently converts the bound into
        # "the first N registry entries always win" (UAT: one agent's inbox deferred 488
        # times in a row). Rotating by one per tick keeps the cap intact while
        # guaranteeing every agent reaches the front within len(registry) ticks.
        entries = [e for e in load_registry() if e.enabled]
        if entries:
            offset = self._rotate % len(entries)
            entries = entries[offset:] + entries[:offset]
            self._rotate += 1
        for entry in entries:
            try:
                loaded = load_profile(entry.id)
            except FileNotFoundError as exc:
                logger.warning("skipping agent %r: %s", entry.id, exc)
                continue
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
                # v65: time-critical no-LLM micro-kinds are cap-EXEMPT — the cap exists
                # to bound LLM/worker load, and a deferred `reminder-sweep` starves
                # DETERMINISTICALLY (same registry/kind order refills the cap every
                # tick; UAT-observed: a due reminder sat pending forever behind 4
                # inbox/team ticks). An exempt kind neither checks nor consumes the cap.
                exempt = kind in _CAP_EXEMPT_KINDS
                if not exempt and spawned >= self._cap:
                    logger.info("tick cap %d reached; deferring %s/%s", self._cap, entry.id, kind)
                    continue
                argv = _worker_argv(entry.id, kind, audience)
                # Start it and move on. Waiting here (the pre-v72 shape) made the tick
                # cost the SUM of its workers' runtimes instead of the max: measured
                # 65s median / 108s max against a 60s interval, so the loop was always
                # behind. Since the rotation offset advances only once per tick, a tick
                # that overruns also slows fairness — pong's inbox, scheduled every
                # minute, was reaching the front of the queue once every 28-144 minutes
                # (6 runs against the coordinator's 338). Spawn-then-drain keeps the cap
                # and the order identical while making a tick cost one worker's wait.
                running.append((spawn(argv), argv, entry.id, kind))
                self._last_fire[(entry.id, kind)] = now  # advance: no re-fire this period
                if not exempt:
                    spawned += 1
        # Drain in spawn order. `_collect`'s timeout is per-worker and they run
        # concurrently, so a hung first worker cannot mask a later one: by the time we
        # reach worker N it has already had the whole drain so far to finish, and its
        # own full timeout on top. Outcome order stays spawn order.
        for proc, argv, agent_id, kind in running:
            outcome = _collect(proc, argv, timeout=self._timeout)
            outcome.update(agent_id=agent_id, kind=kind)
            outcomes.append(outcome)
        _reap_sandboxes_best_effort()
        _consolidate_memories_best_effort(now)
        _archive_stale_skills_best_effort(now)
        return outcomes

    def start_telegram_listeners(self, *, spawn: Spawn = _real_spawn) -> list:
        """v57: một thread long-poll per telegram agent — DM trả lời ~1-2s thay vì chờ tick.

        Listener chỉ "peek" (không LLM, không offset) rồi spawn ĐÚNG worker inbox
        subprocess như tick lịch vẫn spawn — cách ly tiến trình + pipeline giữ nguyên.
        Best-effort: hỏng ở đây không được giết daemon (tick lịch vẫn là fallback)."""
        from my_crew.runtime.agent_paths import agent_data_dir
        from my_crew.runtime.inbox_dispatch import telegram_reader
        from my_crew.runtime.telegram_listener import start_telegram_listeners

        agents = []
        for entry in load_registry():
            if not entry.enabled:
                continue
            try:
                loaded = load_profile(entry.id)
            except FileNotFoundError as exc:
                logger.warning("listener: skipping agent %r: %s", entry.id, exc)
                continue
            # Cửa thứ hai của cùng một token: một binding send-only (`poll_minutes: 0`)
            # KHÔNG được có listener, y như nó không có tick `inbox`. Bỏ sót chỗ này thì
            # agent vẫn treo getUpdates trên token của agent khác — đúng cái 409 mà
            # send-only sinh ra để tránh (xem inbox_dispatch.telegram_reader).
            if not loaded.enabled or telegram_reader(loaded) is None:
                continue
            agents.append((entry.id, loaded.config.telegram, agent_data_dir(entry.id)))

        def run_inbox_worker(agent_id: str) -> None:
            outcome = _supervise(
                spawn, _worker_argv(agent_id, "inbox", "internal"), timeout=self._timeout
            )
            logger.info("listener-triggered inbox %s: %s", agent_id, outcome.get("status"))

        return start_telegram_listeners(agents, run_inbox_worker=run_inbox_worker)

    def poke_pending(self) -> bool:
        """One sleep-slice check: has a team-step worker poked since the last handled
        poke? Advances the watermark when it answers True, so a burst of pokes inside
        one slice (three workers finishing together) collapses to a single early
        team-tick — the tick itself reads the store and handles all of them.

        The first look after daemon start adopts the on-disk mtime as already-handled
        (a stale poke from a previous daemon run is not a fresh signal; the step it
        announced was picked up by the minute cadence long ago).
        """
        from my_crew.runtime.tick_poke import poke_mtime

        mtime = poke_mtime()
        if self._poke_watermark is None:
            self._poke_watermark = mtime if mtime is not None else 0.0
            return False
        if mtime is None or mtime <= self._poke_watermark:
            return False
        self._poke_watermark = mtime
        return True

    def run_poked_team_tick(self, *, spawn: Spawn = _real_spawn) -> dict | None:
        """Spawn + supervise ONE early team-tick for the configured coordinator.

        Mirrors the listener-triggered inbox shape: same worker argv the minute cadence
        would use, just sooner. Does NOT advance `_last_fire` — the minute tick keeps
        firing as the fallback, and an overlap costs one idempotent no-op worker (the
        step lease/DB already serialize real actions). No coordinator configured → the
        poke has no addressee, clean no-op.
        """
        from my_crew.runtime.company import load_company

        coordinator_id = load_company().coordinator_id
        if not coordinator_id:
            return None
        outcome = _supervise(
            spawn, _worker_argv(coordinator_id, "team-tick", "internal"),
            timeout=self._timeout,
        )
        logger.info("poke-triggered team-tick %s: %s", coordinator_id,
                    outcome.get("status"))
        return outcome

    def _sleep_watching_pokes(self, interval: int) -> None:  # pragma: no cover
        """Sleep `interval` seconds in ~5s slices, launching an early team-tick (on a
        daemon thread, so a slow ruling never delays the minute cadence) whenever a
        fresh poke shows up. Thin timing wrapper — the decision (`poke_pending`) and
        the action (`run_poked_team_tick`) are the unit-tested parts, mirroring how
        `run_forever` wraps `run_tick`."""
        import threading

        deadline = time.monotonic() + interval
        while (remaining := deadline - time.monotonic()) > 0:
            time.sleep(min(_POKE_SLICE_S, remaining))
            if self.poke_pending():
                threading.Thread(target=self.run_poked_team_tick, daemon=True).start()

    def run_forever(self, *, interval: int = _TICK_INTERVAL_S) -> None:  # pragma: no cover
        """The daemon loop: tick, sleep, repeat. Thin wrapper over run_tick.

        Uses naive LOCAL time (`datetime.now()`) to match how the cron `schedule:`
        strings are interpreted (local, like launchd) — a `"0 8 * * *"` fires at 08:00
        local, not UTC.
        """
        logger.info("service started; tick interval %ds", interval)
        try:
            listeners = self.start_telegram_listeners()
            logger.info("telegram listeners: %d thread(s)", len(listeners))
        except Exception:  # noqa: BLE001 — instant-chat là tiện nghi, không được giết daemon
            logger.warning("telegram listeners failed to start (scheduled inbox still runs)",
                           exc_info=True)
        while True:
            _write_coordinator_heartbeat()
            self.run_tick(datetime.now())  # noqa: DTZ005 — local time, matches cron intent
            self._sleep_watching_pokes(interval)


def _write_coordinator_heartbeat() -> None:
    """v16: touch `DATA_DIR/coordinator.heartbeat` each SERVICE loop pass — the signal
    `/api/health/coordinator` reads to tell the CEO whether the dispatch engine is
    alive at all (the "task giao xong kẹt im lặng" root cause). Written from the LOOP,
    not from a worker's team-tick body: a long sequential worker run must not make the
    service look dead. try/degrade — a heartbeat write failure never stops the loop."""
    try:
        from my_crew.config.settings import DATA_DIR

        path = DATA_DIR / "coordinator.heartbeat"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    except Exception:  # noqa: BLE001
        logger.warning("coordinator heartbeat write failed", exc_info=True)


def resolve_tick_interval(raw: str | None) -> int:
    """Tick interval in seconds, from `MY_CREW_TICK_INTERVAL_S`.

    An operations knob: the default paces a real deployment, but a full-flow test
    driving a real `serve` process cannot wait a minute per tick. Anything the env
    cannot be read as a positive int falls back to the default rather than failing
    boot — a typo in a unit file must not leave the CEO without a dispatch engine.
    """
    if raw is None:
        return _TICK_INTERVAL_S
    try:
        seconds = int(raw)
    except ValueError:
        logger.warning("MY_CREW_TICK_INTERVAL_S=%r is not an integer; using %ds",
                       raw, _TICK_INTERVAL_S)
        return _TICK_INTERVAL_S
    if seconds < 1:
        logger.warning("MY_CREW_TICK_INTERVAL_S=%r is below 1s; using %ds",
                       raw, _TICK_INTERVAL_S)
        return _TICK_INTERVAL_S
    return seconds


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = argv if argv is not None else sys.argv[1:]
    from my_crew.config.home_seed import ensure_home_seeded

    ensure_home_seeded()
    service = Service()
    if "--once" in args:
        outcomes = service.run_tick(datetime.now())  # noqa: DTZ005 — local, matches cron intent
        logger.info("one tick: %d worker(s) spawned", len(outcomes))
        return 0
    interval = resolve_tick_interval(os.environ.get("MY_CREW_TICK_INTERVAL_S"))
    service.run_forever(interval=interval)  # pragma: no cover — runs until killed
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
