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
from my_crew.agent.task_reflection import make_reflect
from my_crew.runtime.company import load_company
from my_crew.runtime.team_task_paths import team_tasks_db_path, team_tasks_root
from my_crew.runtime.team_task_store import TeamStep, TeamTask, TeamTaskStore
from my_crew.runtime.team_tick_collaborators import make_aggregate, make_deliver_room, make_escalate
from my_crew.runtime.team_tick_stuck_judge import make_judge_stuck_step

logger = logging.getLogger(__name__)

#: Persists retry counts across ticks/process restarts (a fresh `RetryTracker` per tick
#: would forget a count between two separate `team-tick` worker invocations, since each
#: is its own OS process) — a small JSON sidecar next to the shared store, keyed by
#: "task_id/step_id".
_RETRY_SIDECAR_NAME = "team_tick_retries.json"

#: v74: tick actions that OPEN THE DOOR for the next action ("take ONE action, exit"
#: means a ruling and the rework spawn it enables are two separate ticks — measured
#: ~65s apart on the minute cadence). A tick ending in one of these pokes the service
#: so the next tick runs within a sleep slice (~5s). "none" NEVER pokes, so every
#: poke chain terminates the first tick that finds nothing to do; failure-ish ends
#: (failed/stalled/timeout_escalated/gave_up/cap_exceeded) don't poke either — their
#: next move is either impossible or arrives via a worker-exit poke anyway.
_POKE_WORTHY_ACTIONS = frozenset({"spawned", "aggregated", "stuck_retry", "stuck_reassigned"})


def poke_worthy(action: str) -> bool:
    """Should a tick that ended with `action` request an immediate follow-up tick?"""
    return action in _POKE_WORTHY_ACTIONS


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
            approval_approve=_approval_approve,
            approval_reject=_approval_reject,
            approval_action=_approval_action,
            approval_rule_match=_approval_rule_match,
            approval_rule_record_use=_approval_rule_record_use,
            autopilot_enabled=_autopilot_enabled,
            clarify_status=_clarify_status,
            roster_ok=_roster_ok,
            can_do_step=_can_do_step,
            aggregate=make_aggregate(loaded, settings),
            deliver_room=make_deliver_room(loaded, settings),
            escalate=make_escalate(loaded, settings),
            judge_stuck_step=make_judge_stuck_step(settings),
            # Lessons live in the COORDINATOR's own namespace — it is the agent that
            # assigns work, so what it learns is about its own delegating. `loaded` IS
            # the coordinator here (this kind runs only on that agent), so its profile id
            # is the right namespace owner even when company.yaml names it differently.
            reflect=make_reflect(
                getattr(loaded, "profile_id", "") or (company.coordinator_id or ""),
                settings,
            ),
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
        # v67 P1: re-send finished-task summaries whose room milestone never landed
        # (delivery split — "done" execution vs "the CEO was actually told"). Bounded
        # per task; the attempts==cap transition escalates exactly once.
        try:
            from my_crew.runtime.delivery_retry_sweep import run_delivery_retry_sweep

            run_delivery_retry_sweep(store, deps.deliver_room, deps.escalate)
        except Exception:  # noqa: BLE001 — hygiene, never the tick's fate
            logger.warning("team-tick: delivery retry sweep failed", exc_info=True)
        # v63 autopilot: with the company flag ON, resolve stalled tasks in the CEO's
        # place on a bounded deterministic ladder (retry → accept/drop, capped per
        # task). No-op with the flag off; every decision audited + mirrored to the CEO.
        try:
            from my_crew.runtime.autopilot_sweep import run_autopilot_sweep

            run_autopilot_sweep(store)
        except Exception:  # noqa: BLE001 — hygiene, never the tick's fate
            logger.warning("team-tick: autopilot sweep failed", exc_info=True)
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
    if poke_worthy(result.action):
        from my_crew.runtime.tick_poke import touch_poke

        touch_poke()
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


def _step_worker_log_path() -> Path:
    """Where a spawned step worker's stderr lands: `<data>/logs/team-step-workers.log`.

    One shared append-only file rather than per-step files: steps are many and short, and
    what an operator actually wants is the interleaved story of a task, not a directory to
    correlate by hand. Every worker line is already prefixed by its agent/task/step.
    """
    path = team_tasks_root() / "logs" / "team-step-workers.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


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
        # The step worker's stderr used to go to DEVNULL, which threw away the ONLY record
        # of how a step actually ran: which runtime tier it resolved to, whether its tool
        # loop hit the recursion cap and degraded to an empty result, why a search was
        # skipped. Debugging a bad step then meant reproducing it by hand, because the
        # service log legitimately contains nothing — the work happens in this child.
        # Best-effort: if the log cannot be opened, fall back to DEVNULL rather than let a
        # logging problem stop real work from being dispatched.
        try:
            sink = open(_step_worker_log_path(), "a")  # noqa: SIM115 — owned by the child
        except OSError:
            logger.warning("team-tick: step worker log unavailable; stderr discarded",
                           exc_info=True)
            sink = subprocess.DEVNULL
        try:
            proc = subprocess.Popen(  # noqa: S603 — argv is a list, ids from the store, no shell
                argv, start_new_session=True,
                stdout=subprocess.DEVNULL, stderr=sink,
            )
        finally:
            # The child holds its own dup of the fd; the parent's copy is dead weight and
            # would leak one descriptor per dispatched step in a long-lived ticker.
            if sink is not subprocess.DEVNULL:
                sink.close()
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


def _approval_status(approval_id: int, agent_id: str) -> str | None:
    """Read-only poll against ONE agent's `ApprovalStore` — the SAME store
    `mpm approve`/`mpm reject` (per-agent `<agent_data_dir>/approvals.db`) write to.

    Scoped to `agent_id` (the step's `assigned_to`) since v64: approval ids are
    per-FILE AUTOINCREMENT (every agent's store counts 1,2,3…), so the old cross-store
    scan could return a DIFFERENT agent's colliding row's status — a wrong-row READ
    that could resume or fail a step off someone else's decision. The write half
    (`_approval_approve`) was scoped in v63; this closes the read half.

    Returns `None` when the id does not resolve in that store (unknown/stale id) —
    the ticker treats that identically to `"pending"` (leave the step alone), never
    as an implicit approve.
    """
    from my_crew.actions.approval_store import ApprovalStore
    from my_crew.runtime.agent_paths import agent_data_dir

    if not agent_id:
        return None
    store = ApprovalStore(agent_data_dir(agent_id) / "approvals.db")
    try:
        approval = store.get(approval_id)
    finally:
        store.close()
    return approval.status if approval is not None else None


def _autopilot_enabled() -> bool:
    """Fresh read per decision — `set_autopilot off` must bite on the next tick."""
    from my_crew.agent.ops_autopilot import autopilot_enabled

    return autopilot_enabled()


def _approval_approve(approval_id: int, agent_id: str) -> bool:
    """v63 autopilot: flip ONE pending Lớp B row to approved, scoped to the STEP'S OWN
    agent store (`agent_id` = the step's `assigned_to`) — approval ids are per-file
    AUTOINCREMENT, so a cross-store scan would routinely hit a colliding id in another
    agent's store and approve an unrelated action (review-found v63 H1). Same
    `transition_if_pending` transition the manual `mpm approve` path uses, so a
    concurrent CEO decision wins the race and this returns False."""
    from my_crew.actions.approval_store import ApprovalStore
    from my_crew.runtime.agent_paths import agent_data_dir

    if not agent_id:
        return False
    store = ApprovalStore(agent_data_dir(agent_id) / "approvals.db")
    try:
        if store.get(approval_id) is None:
            return False
        return store.transition_if_pending(approval_id, "approved")
    finally:
        store.close()


def _approval_reject(approval_id: int, agent_id: str) -> bool:
    """v67 learned deny rule (queued path): flip ONE pending Lớp B row to rejected, scoped
    to the step's OWN agent store — same per-file AUTOINCREMENT reasoning + same
    `transition_if_pending` compare-and-set as `_approval_approve`, so a concurrent CEO
    decision wins the race and this returns False."""
    from my_crew.actions.approval_store import ApprovalStore
    from my_crew.runtime.agent_paths import agent_data_dir

    if not agent_id:
        return False
    store = ApprovalStore(agent_data_dir(agent_id) / "approvals.db")
    try:
        if store.get(approval_id) is None:
            return False
        return store.transition_if_pending(approval_id, "rejected")
    finally:
        store.close()


def _approval_action(approval_id: int, agent_id: str) -> dict | None:
    """v67: read the queued action payload of a pending Lớp B row (the step itself carries
    only the approval_id), scoped to the step's OWN agent store. `None` when the id does
    not resolve — the ticker then skips the rule check, same as no rule at all."""
    from my_crew.actions.approval_store import ApprovalStore
    from my_crew.runtime.agent_paths import agent_data_dir

    if not agent_id:
        return None
    store = ApprovalStore(agent_data_dir(agent_id) / "approvals.db")
    try:
        approval = store.get(approval_id)
    finally:
        store.close()
    return approval.action if approval is not None else None


def _approval_rule_match(action: dict, agent_id: str) -> tuple[str, int] | None:
    """v67: ask ONE agent's ApprovalRuleStore for a standing decision on `action`.
    Returns `(scope, rule_id)` where scope is "deny"/"approve" (mapped from the store's
    "always"), or `None` for no rule.

    Deliberately does NOT record the use: a matched rule only DECIDES if the row is still
    pending when the ticker transitions it. A concurrent CEO decision can win that race, and
    a rule that decided nothing must not show a use in the audit trail. The ticker calls
    `approval_rule_record_use` after a confirmed transition instead."""
    from my_crew.actions.approval_rule_store import SCOPE_DENY, ApprovalRuleStore
    from my_crew.runtime.agent_paths import agent_data_dir

    if not agent_id:
        return None
    store = ApprovalRuleStore(agent_data_dir(agent_id) / "approvals.db")
    try:
        rule = store.match(action)
        if rule is None:
            return None
        scope = "deny" if rule.scope == SCOPE_DENY else "approve"
        return scope, rule.id
    finally:
        store.close()


def _approval_rule_record_use(rule_id: int, agent_id: str) -> None:
    """Stamp a rule's use AFTER it actually decided a row (see `_approval_rule_match`)."""
    from my_crew.actions.approval_rule_store import ApprovalRuleStore
    from my_crew.runtime.agent_paths import agent_data_dir

    if not agent_id:
        return
    store = ApprovalRuleStore(agent_data_dir(agent_id) / "approvals.db")
    try:
        store.record_use(rule_id)
    finally:
        store.close()


def _roster_ok(agent_id: str) -> bool:
    """Dispatch-time role re-check — delegates to the SAME
    `team_task_roster.is_assignable` decompose-validation time uses, so both gates can
    never silently disagree."""
    from my_crew.agent.team_task_roster import is_assignable

    return is_assignable(agent_id)


def _web_search_enabled(agent_id: str) -> bool:
    """Whether that agent can ACTUALLY search the web. Unknown/unloadable profile ⇒ False.

    Read from the profile rather than the registry: `web_search:` is the same per-agent
    flag that arms both the native pre-work hook and the loop tier's `web.search` tool.
    The flag alone is not the whole truth, though: a deep_agent runs its work INSIDE a
    sandbox, and with no network opt-in that sandbox cannot reach any search provider —
    the flag arms nothing usable there. Observed live (twice): research steps reassigned
    to the deep-tier analyst on the strength of its flag, which then honestly reported
    'không có quyền truy cập thời gian thực' and burned the step's whole budget.
    """
    from my_crew.profile.loader import load_profile

    try:
        loaded = load_profile(agent_id)
        if not bool(getattr(loaded, "web_search", False)):
            return False
        runtime = getattr(loaded, "agent_runtime", None)
        if getattr(runtime, "kind", "") == "deep_agent":
            sandbox = getattr(runtime, "sandbox", None) or {}
            return bool(sandbox.get("network"))
        return True
    except Exception:  # noqa: BLE001 — an unreadable profile must not wedge the tick
        logger.warning("team-tick: cannot read web_search for %s", agent_id, exc_info=True)
        return False


def _can_do_step(agent_id: str, step) -> bool:
    """Whether `agent_id` holds the tools this step needs.

    There is no "needs web" flag on a step, and inventing one would mean trusting the
    decomposing model to predict its own future tool needs. What IS knowable is the
    capability of the agent who already holds the step: if the current assignee can
    search and the proposed one cannot, the reassign is a capability DOWNGRADE — the
    step gets handed to someone strictly less able to finish it. That is the shape that
    bit us in production (a web data-collection step moved from researcher to an agent
    with no search), and it is decidable without asking a model anything.

    Deliberately one-directional: an upgrade, a lateral move, or a step whose current
    holder never had search all pass. This gate only refuses to make things worse.
    """
    current = getattr(step, "assigned_to", "") or ""
    if not current or not _web_search_enabled(current):
        return True
    return _web_search_enabled(agent_id)
