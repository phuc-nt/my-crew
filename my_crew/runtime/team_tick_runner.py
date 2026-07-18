"""`team-tick` generic run kind's real body (v12 M28b) — runs ONLY on the coordinator
agent (`company.yaml::coordinator_id`). Wires the pure `run_one_tick` (coordinator_graph)
with real collaborators: the shared `TeamTaskStore`, a JSON-sidecar `RetryTracker`, a
DETACHED `team-step` worker spawn (never waited on — that is the whole point of a SHORT
tick), `os.kill`-based pid probing, and (from `team_tick_collaborators`) an LLM aggregate
call + a Telegram escalation mirroring `ops_alert_runner.py`'s pattern (best-effort,
never raises).

Returns the same `{status, checked, cost_usd, delivered}` shape `run_tasks`/
`run_ops_alerts` return, so `worker.py`'s `team-tick` branch can reuse the identical
run-event plumbing as every other generic kind.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess  # noqa: S404 — spawning a detached team-step worker is this module's job
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from my_crew.agent.coordinator_graph import CoordinatorDeps, RetryTracker, run_one_tick
from my_crew.runtime.company import load_company
from my_crew.runtime.team_task_paths import team_tasks_db_path, team_tasks_root
from my_crew.runtime.team_task_store import TeamStep, TeamTask, TeamTaskStore
from my_crew.runtime.team_tick_collaborators import make_aggregate, make_deliver_room, make_escalate

logger = logging.getLogger(__name__)

#: Persists retry counts across ticks/process restarts (a fresh `RetryTracker` per tick
#: would forget a count between two separate `team-tick` worker invocations, since each
#: is its own OS process) — a small JSON sidecar next to the shared store, keyed by
#: "task_id/step_id".
_RETRY_SIDECAR_NAME = "team_tick_retries.json"


def run_team_tick(loaded: Any, settings: Any, *, now: datetime | None = None) -> dict:
    """One `team-tick`: advance ONE open team task by ONE action, return a run-event dict.

    `loaded`/`settings` are the coordinator agent's own `LoadedProfile`/`Settings` — used
    for the Telegram escalation (its own `config.telegram`) and for the LLM aggregate call
    (its own `settings.require_api_key()`-gated client). No open task is a clean success
    (mirrors `run_tasks`'s "a tick with zero due tasks is a SUCCESS").
    """
    company = load_company()
    cap_usd = company.team_task_cap_usd

    store = TeamTaskStore(team_tasks_db_path())
    try:
        deps = CoordinatorDeps(
            store=store,
            retry_tracker=_json_retry_tracker(team_tasks_root() / _RETRY_SIDECAR_NAME),
            cost_cap_usd=cap_usd,
            concurrency=company.team_task_concurrency,
            spawn_step=_make_spawn_step(),
            pid_alive=_pid_alive,
            kill_pid=_kill_pid,
            approval_status=_approval_status,
            clarify_status=_clarify_status,
            roster_ok=_roster_ok,
            aggregate=make_aggregate(loaded, settings),
            deliver_room=make_deliver_room(),
            escalate=make_escalate(loaded, settings),
            now=(lambda: now) if now is not None else (lambda: datetime.now(UTC)),
        )
        result = run_one_tick(deps)
        try:
            # Best-effort hygiene, same posture as everything else in this function's
            # try block being wrapped by the outer `finally: store.close()` — an
            # abandoned "chỉnh kế hoạch" draft the CEO never confirmed/cancelled must
            # not sit forever (see `team_task_amend.cleanup_stale_drafts`'s docstring).
            # Never allowed to fail the tick itself: this is cleanup, not the tick's
            # own actionable work.
            store.cleanup_stale_amendment_drafts()
        except Exception:
            logger.warning("team-tick: cleanup_stale_amendment_drafts failed", exc_info=True)
        # v33 P4: same hygiene posture — overdue CEO questions flip to expired so an
        # unanswered clarify can never wedge anything (the asking step already moved
        # on with its safe default; expiry just closes the queue entry).
        from my_crew.runtime.clarify_service import expire_sweep

        expire_sweep()
        # v33 P5: keep the history index warm (incremental, cheap when idle) so a
        # search never has to backfill a cold index in the CEO's request path.
        try:
            from my_crew.runtime.history_search_index import HistorySearchIndex

            _idx = HistorySearchIndex()
            try:
                _idx.sweep()
            finally:
                _idx.close()
        except Exception:  # noqa: BLE001 — index hygiene must never break the tick
            logger.warning("team-tick: history index sweep failed", exc_info=True)
        # v34 P1: sweep orphaned step-graph checkpoint threads. Steps delete their
        # thread on completion; what's left belongs to tasks that ended sideways
        # (cancelled mid-run, worker never resumed). Keep threads of LIVE tasks —
        # they are exactly the resume state P1 exists for.
        try:
            _sweep_team_checkpoints(store)
        except Exception:  # noqa: BLE001 — hygiene, never the tick's fate
            logger.warning("team-tick: checkpoint sweep failed", exc_info=True)
        # v34 P3: the coordinator ĐEO BÁM stuck work — pure-SQL detect + a bounded
        # escalation ladder (office event → clarify question → Telegram notice),
        # cooldown-gated per task. Never LLM, never a status write.
        try:
            from my_crew.runtime.follow_up_sweep import run_follow_up_sweep

            run_follow_up_sweep(store)
        except Exception:  # noqa: BLE001 — hygiene, never the tick's fate
            logger.warning("team-tick: follow-up sweep failed", exc_info=True)
        # v36 P1: retention GC (captures/office_room/clarify/dedup grew unbounded) +
        # a daily read-only integrity audit. Both best-effort; storage_hygiene guards
        # each store internally, this wrapper is the final backstop for the tick.
        try:
            from my_crew.runtime.storage_hygiene import run_integrity_audit, run_retention_sweep

            run_retention_sweep()
            run_integrity_audit()
        except Exception:  # noqa: BLE001 — hygiene, never the tick's fate
            logger.warning("team-tick: storage hygiene failed", exc_info=True)
    finally:
        store.close()

    checked = 0 if result.task_id is None else 1
    delivered = result.action == "aggregated"
    logger.info("team-tick: task=%s action=%s detail=%s",
                result.task_id, result.action, result.detail)
    return {"status": result.action, "checked": checked, "cost_usd": None,
            "delivered": delivered}


def _sweep_team_checkpoints(store: TeamTaskStore) -> None:
    """Delete step-graph checkpoint threads whose task is gone or terminal.

    Reads the checkpointer's own SQLite file directly (any table carrying a
    `thread_id` column — table names are the saver library's internals, so introspect
    rather than hard-code). Thread ids are `team:<task_id>:<step_id>`.
    """
    import sqlite3

    from my_crew.runtime.team_task_paths import team_checkpoints_db_path

    path = team_checkpoints_db_path()
    if not path.exists():
        return
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("PRAGMA busy_timeout=3000")
        tables = [
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ]
        def _q(name: str) -> str:
            return '"' + name.replace('"', '""') + '"'  # quoted identifier (review M4)

        threaded_tables = [
            t for t in tables
            if any(c[1] == "thread_id" for c in conn.execute(f"PRAGMA table_info({_q(t)})"))
        ]
        if not threaded_tables:
            return
        threads: set[str] = set()
        for t in threaded_tables:
            threads.update(
                r[0] for r in conn.execute(
                    f"SELECT DISTINCT thread_id FROM {_q(t)} WHERE thread_id LIKE 'team:%'"
                )
            )
        removed = 0
        for thread_id in threads:
            parts = thread_id.split(":")
            task = store.get(parts[1]) if len(parts) >= 3 and parts[1] else None
            if task is not None and task.status not in ("done", "cancelled"):
                continue  # live task — this thread may be resume state
            for t in threaded_tables:
                conn.execute(f"DELETE FROM {_q(t)} WHERE thread_id = ?", (thread_id,))
            removed += 1
        if removed:
            conn.commit()
            logger.info("team-tick: swept %d orphaned checkpoint thread(s)", removed)
    finally:
        conn.close()


# ---- collaborator factories -------------------------------------------------------


def _json_retry_tracker(sidecar_path: Path) -> RetryTracker:
    """A `RetryTracker` backed by a small JSON file — read fresh, written fresh, on
    every call, so it survives across the separate OS processes each tick runs in.
    Corrupt/missing file degrades to "no retries recorded yet" rather than raising
    (a lost retry-count sidecar should cost one extra retry, never crash the ticker)."""

    def _load() -> dict[str, int]:
        try:
            raw = sidecar_path.read_text(encoding="utf-8")
        except OSError:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _save(data: dict[str, int]) -> None:
        sidecar_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = sidecar_path.with_suffix(f".tmp-{os.getpid()}")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, sidecar_path)

    def _key(task_id: str, step_id: str) -> str:
        return f"{task_id}/{step_id}"

    def _get(task_id: str, step_id: str) -> int:
        return int(_load().get(_key(task_id, step_id), 0))

    def _increment(task_id: str, step_id: str) -> int:
        data = _load()
        key = _key(task_id, step_id)
        data[key] = int(data.get(key, 0)) + 1
        _save(data)
        return data[key]

    def _clear(task_id: str, step_id: str) -> None:
        data = _load()
        data.pop(_key(task_id, step_id), None)
        _save(data)

    return RetryTracker(get=_get, increment=_increment, clear=_clear)


def _make_spawn_step():
    """Detached `team-step` worker spawn: `start_new_session=True` so the child is not
    killed if the ticker's own (short-lived) process exits/is signaled — the tick
    intentionally does NOT wait on this child (that is what makes a tick short)."""

    def _spawn(task: TeamTask, step: TeamStep, attempt_id: str) -> int:
        argv = [
            sys.executable, "-m", "my_crew.runtime.worker",
            "--agent-id", step.assigned_to, "--report", "team-step",
            "--audience", "internal",
            "--task-id", task.id, "--step-id", step.step_id, "--attempt-id", attempt_id,
        ]
        proc = subprocess.Popen(  # noqa: S603 — argv is a list, ids come from the store, no shell
            argv, start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return proc.pid

    return _spawn


def _pid_alive(pid: int) -> bool:
    """POSIX liveness probe: signal 0 sends nothing, just checks the pid exists and is
    reachable. `ProcessLookupError` -> dead. `PermissionError` -> alive but owned by
    another user (treat as alive: killing it isn't ours to do either way, and it is
    definitely still running)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    else:
        return True


def _ps_command_line(pid: int) -> str:
    """`ps -o command= -p <pid>` (POSIX, works unmodified on both macOS and Linux, no
    extra dependency) — empty string on any failure (pid gone, `ps` missing/erroring),
    which `_kill_pid` treats identically to "identity unverifiable, skip the kill"."""
    try:
        return subprocess.run(  # noqa: S603 — fixed argv, no shell, pid is an int
            ["ps", "-o", "command=", "-p", str(pid)],
            capture_output=True, text=True, timeout=5, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _kill_pid(pid: int, attempt_id: str, *, ps_command_line=_ps_command_line) -> None:
    """PID-reuse-guarded SIGKILL: a lease-expired step's `child_pid` was
    recorded when the worker was spawned, but by the time the lease actually expires
    (default 10 minutes later) the OS may have long since reaped that pid and handed
    the SAME number to an unrelated process — blindly signaling it would kill a
    stranger, not the stuck worker.

    Verifies identity first via `ps_command_line` (real: `ps -o command= -p <pid>`,
    injectable for tests) and only kills if the command line still contains THIS step's
    `attempt_id` (present in `_make_spawn_step`'s argv via `--attempt-id`) — a pid whose
    command line no longer matches (reused by another process, or the process is
    already gone and `ps` returns nothing) is left alone; the step is still marked
    `timeout` by the caller either way, so a skipped kill never leaves the step lease
    dangling.
    """
    output = ps_command_line(pid)
    if attempt_id not in output:
        logger.warning(
            "team-tick: kill_pid(%s) skipped — command line does not contain attempt_id "
            "%s (process reused or already gone)", pid, attempt_id,
        )
        return
    try:
        os.kill(pid, 9)
    except (ProcessLookupError, PermissionError):
        pass


def _clarify_status(clarify_id: int) -> tuple[str, str] | None:
    """Read-only poll against the shared ClarifyStore (v34 P2) — the same rows the
    web answer route and the Telegram button path write to."""
    from my_crew.runtime.clarify_service import clarify_status

    return clarify_status(clarify_id)


def _approval_status(approval_id: int) -> str | None:
    """Read-only poll against the shared `ApprovalStore` — the SAME store
    `mpm approve`/`mpm reject` (per-agent `<agent_data_dir>/approvals.db`) write to.

    An `approval_id` on a team step always originates from THAT step's `assigned_to`
    agent's own gateway (per-agent isolation — a coordinator never runs its own
    gateway for another agent's write), but this function has no `step` in scope, only
    the raw id — the caller (`CoordinatorDeps.approval_status`) is agent-agnostic by
    signature. Since approval ids are process-wide unique (SQLite AUTOINCREMENT per
    file) but stores are per-agent files, this scans every enabled agent's store for
    the id rather than requiring the caller to also pass `assigned_to` — simplest
    correct option; team tasks are low-volume (a handful of agents, single-digit
    concurrent approvals) so an O(agents) scan per poll is not a real cost.

    Returns `None` when the id resolves in no store at all (unknown/stale id) — the
    ticker treats that identically to `"pending"` (leave the step alone), never as an
    implicit approve.
    """
    from my_crew.actions.approval_store import ApprovalStore
    from my_crew.runtime.agent_paths import agent_data_dir
    from my_crew.runtime.registry import load_registry

    for entry in load_registry():
        store = ApprovalStore(agent_data_dir(entry.id) / "approvals.db")
        try:
            approval = store.get(approval_id)
        finally:
            store.close()
        if approval is not None:
            return approval.status
    return None


def _roster_ok(agent_id: str) -> bool:
    """Dispatch-time role re-check — delegates to the SAME
    `team_task_roster.is_assignable` decompose-validation time uses, so both gates can
    never silently disagree."""
    from my_crew.agent.team_task_roster import is_assignable

    return is_assignable(agent_id)
