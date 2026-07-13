"""Cross-agent team-task store — SQLite at `data_dir` ROOT, not per-agent.

A team task spans MULTIPLE agents (e.g. "chuẩn bị demo cho khách" fans out into steps
each run by a different agent), so unlike `TaskStore` (one file per agent) this store
lives at one shared path: `<data_dir>/team_tasks.sqlite3`. Real cross-process writers
(the coordinator ticker + each spawned worker writing its own step's cost/status) can
hit this concurrently, so it opens **WAL + busy_timeout** — without WAL, two writers in
the same instant would trip `sqlite3.OperationalError: database is locked`.

Two tables:
  - `team_tasks`: the task header (title, status, plan_hash, cost roll-up columns).
  - `team_steps`: one row per DAG step, including the **lease** columns
    (`attempt_id`/`child_pid`/`spawned_at`/`last_seen`/`lease_expires_at`) a worker
    spawn claims via `reserve_step`. Step-row SQL lives in `team_task_steps` (module
    split — this file stays under the repo's LOC guideline).

Reserve-before-spawn / lease semantics: `reserve_step` issues a fresh `attempt_id` UUID
and marks the step `running`. A caller may re-reserve an ALREADY-`running` step ONLY when
its lease has expired (`lease_expired`) AND no outcome artifact exists yet for that
attempt — "the row says running" is an idempotent DB write, not proof a process is
alive, so the artifact-absence check (owned by the coordinator, which knows the
artifact-path convention) is the actual double-spawn guard. `mark_done`/`mark_failed`
additionally accept an `attempt_id` so a stale worker's terminal write, should it ever
race a legitimate re-reserve, is a harmless no-op rather than clobbering the new
attempt's row (see `team_task_steps.set_step_status`'s docstring for the full guard).

Rows here are internal-audience-only (THE INVARIANT): nothing in this store is ever
handed to an external delivery path.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.runtime import team_task_amend as _amend
from src.runtime import team_task_steps as _steps
from src.runtime.team_task_amend import (  # re-exported for callers
    AmendmentDraft,
    ConfirmAmendmentResult,
    full_dag_plan_hash,
)
from src.runtime.team_task_paths import team_tasks_db_path, team_tasks_root
from src.runtime.team_task_steps import TeamStep  # re-exported for callers

__all__ = [
    "AmendmentDraft", "ConfirmAmendmentResult", "TeamStep", "TeamTask", "TeamTaskStore",
    "DEFAULT_LEASE_TTL_S", "full_dag_plan_hash", "team_tasks_root", "team_tasks_db_path",
]

#: A reserved-but-not-yet-heartbeating step is considered dead (re-reservable) once
#: this many seconds pass with no heartbeat/spawn record update.
DEFAULT_LEASE_TTL_S = 600

_TASK_STATUSES = ("planning", "open", "running", "done", "cancelled", "stalled")
#: Statuses the coordinator ticker may ACT on — deliberately excludes `planning`
#: (a draft the CEO has previewed but not yet confirmed via `confirm_plan`). The
#: confirm-binds-hash / TOCTOU design (see `confirm_plan`'s docstring) is only real
#: if the ticker never dispatches a step for a task the CEO has not confirmed —
#: `list_open` (visibility: what a status view may show) and `list_dispatchable`
#: (what the ticker may act on) are DELIBERATELY separate lists so a future
#: visibility need for `planning` tasks can never silently reopen the dispatch gate.
_DISPATCHABLE_TASK_STATUSES = ("open", "running")
_OPEN_TASK_STATUSES = ("planning", "open", "running")


@dataclass(frozen=True)
class TeamTask:
    id: str
    title: str
    original_request: str
    status: str
    created_at: str
    assigned_by: str
    cost_usd_total: float
    plan_hash: str | None
    decompose_cost_usd: float
    aggregate_cost_usd: float
    escalated_at: str | None
    # v15 PIC: staffer responsible for the whole task ("" = pre-v15 task, no PIC).
    # Metadata OUTSIDE the plan hash — see task_decomposition.decomposition_content_hash.
    pic_id: str = ""
    # v16 workroom: the room this task's events live in. "" = the task's own id (every
    # pre-v16 task and every task assigned outside a room) — resolve via
    # `office_room_append.room_for_task`, never read this raw for routing.
    room_id: str = ""
    steps: tuple[TeamStep, ...] = field(default_factory=tuple)


class TeamTaskStore:
    """SQLite-backed cross-agent store for team tasks + their DAG steps.

    `check_same_thread=False` + WAL + a `busy_timeout` PRAGMA: several OS processes
    (the ticker plus each spawned per-agent worker) open a connection to the SAME
    file concurrently, so both the driver-level thread check and SQLite's default
    rollback-journal locking must be relaxed/widened for a real multi-writer file.
    """

    def __init__(self, db_path: Path, *, lease_ttl_s: int = DEFAULT_LEASE_TTL_S) -> None:
        self._path = db_path
        self._lease_ttl_s = lease_ttl_s
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False, timeout=30.0)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._create_schema()

    def _create_schema(self) -> None:
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS team_tasks ("
            "  id TEXT PRIMARY KEY,"
            "  title TEXT NOT NULL,"
            "  original_request TEXT NOT NULL DEFAULT '',"
            "  status TEXT NOT NULL DEFAULT 'planning',"
            "  created_at TEXT NOT NULL,"
            "  assigned_by TEXT NOT NULL DEFAULT '',"
            "  cost_usd_total REAL NOT NULL DEFAULT 0.0,"
            "  plan_hash TEXT,"
            "  decompose_cost_usd REAL NOT NULL DEFAULT 0.0,"
            "  aggregate_cost_usd REAL NOT NULL DEFAULT 0.0,"
            "  escalated_at TEXT"
            ")"
        )
        # Additive column for a store created before v15 — same migrate-free ALTER
        # pattern `team_task_steps.create_schema` uses for its own later columns.
        try:
            self._conn.execute("ALTER TABLE team_tasks ADD COLUMN pic_id TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            pass  # column already exists
        try:
            self._conn.execute("ALTER TABLE team_tasks ADD COLUMN room_id TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            pass  # column already exists
        # v34 P3: follow-up ladder bookkeeping (cooldown + escalation level) — read and
        # written ONLY by `follow_up_sweep`; never part of the plan hash.
        for ddl in (
            "ALTER TABLE team_tasks ADD COLUMN last_follow_up_at TEXT",
            "ALTER TABLE team_tasks ADD COLUMN follow_up_level INTEGER NOT NULL DEFAULT 0",
        ):
            try:
                self._conn.execute(ddl)
            except sqlite3.OperationalError:
                pass  # column already exists
        _steps.create_schema(self._conn)
        _amend.create_schema(self._conn)
        from src.runtime.store_schema_meta import ensure_schema_meta

        ensure_schema_meta(self._conn)
        self._conn.commit()

    def _now(self) -> str:
        return datetime.now(UTC).isoformat()

    # ---- task lifecycle -----------------------------------------------------

    def create_task(
        self, *, task_id: str, title: str, original_request: str = "", assigned_by: str = "",
        pic_id: str = "", room_id: str = "",
    ) -> str:
        """Create a task row in `planning` status. `task_id` is caller-supplied
        (the coordinator mints it) so it can be referenced before `set_plan`.

        `room_id` (v16): the existing workroom this task joins ("" = its own room).
        'office' is the GLOBAL log room every event mirrors into — a task claiming it
        as its workroom would collapse the two concepts, hence the hard reject."""
        if room_id == "office":
            raise ValueError("room_id 'office' là phòng nhật ký tổng — không thể làm workroom")
        self._conn.execute(
            "INSERT INTO team_tasks "
            "(id, title, original_request, status, created_at, assigned_by, pic_id, room_id) "
            "VALUES (?, ?, ?, 'planning', ?, ?, ?, ?)",
            (task_id, title, original_request, self._now(), assigned_by, pic_id, room_id),
        )
        self._conn.commit()
        return task_id

    def set_plan(self, task_id: str, steps: list[dict[str, Any]], plan_hash: str) -> None:
        """Attach the confirmed DAG to a task: replaces any existing steps, records
        `plan_hash` (a content hash of the confirmed DAG), and moves the task to
        `open`. Each step dict: `{step_id, title, assigned_to, deps}`.

        Test/fixture convenience (writes + confirms in one call). The REAL CEO-facing
        assign_team_task flow does NOT use this — it uses `set_draft_plan` (preview
        time) then `confirm_plan` (confirm time) so the confirm step can verify the
        CEO is approving the EXACT DAG they were shown, never re-materializing it (see
        `confirm_plan`'s docstring).
        """
        _steps.replace_steps(self._conn, task_id, steps)
        self._conn.execute(
            "UPDATE team_tasks SET plan_hash = ?, status = 'open' WHERE id = ?",
            (plan_hash, task_id),
        )
        self._conn.commit()

    def set_draft_plan(self, task_id: str, steps: list[dict[str, Any]], plan_hash: str) -> None:
        """Persist a PROPOSED (not yet confirmed) DAG: writes the steps + `plan_hash`
        but leaves `status` at `planning` — the task is not dispatchable yet.

        Called once, at `assign_team_task`'s preview step, right after decomposition +
        validation succeed. `plan_hash` is `task_decomposition.decomposition_content_hash`
        of the SAME steps — the CEO's later "xác nhận" must present this exact hash back
        (via `confirm_plan`) or the confirm is rejected as stale/tampered.
        """
        _steps.replace_steps(self._conn, task_id, steps)
        self._conn.execute(
            "UPDATE team_tasks SET plan_hash = ? WHERE id = ?", (plan_hash, task_id),
        )
        self._conn.commit()

    def confirm_plan(self, task_id: str, expected_hash: str) -> bool:
        """TOCTOU-proof confirm: flips a `planning` task to `open` IFF `expected_hash`
        matches the `plan_hash` persisted by `set_draft_plan` — and does NOTHING else.

        Deliberately does NOT re-run decomposition or re-write steps ("re-materialization
        forbidden" — the plan the CEO approves is byte-for-byte the plan that was
        previewed, never a freshly recomputed one that merely claims the same hash).
        Returns False (no-op, task left untouched) when the task is missing, has no
        draft plan, or the hash no longer matches (e.g. a second preview overwrote the
        draft between preview and confirm) — the caller reports this as "kế hoạch đã
        thay đổi, xác nhận lại" rather than silently dispatching a different plan.
        """
        row = self._conn.execute(
            "SELECT plan_hash, status FROM team_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            return False
        plan_hash, status = row
        if status != "planning" or plan_hash != expected_hash:
            return False
        self._conn.execute("UPDATE team_tasks SET status = 'open' WHERE id = ?", (task_id,))
        self._conn.commit()
        return True

    def get(self, task_id: str) -> TeamTask | None:
        row = self._conn.execute(
            "SELECT * FROM team_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            return None
        cols = [d[0] for d in self._conn.execute("SELECT * FROM team_tasks LIMIT 0").description]
        data = dict(zip(cols, row, strict=True))
        steps = _steps.steps_for_task(self._conn, task_id)
        return TeamTask(
            id=data["id"], title=data["title"], original_request=data["original_request"],
            status=data["status"], created_at=data["created_at"], assigned_by=data["assigned_by"],
            cost_usd_total=float(data["cost_usd_total"]), plan_hash=data["plan_hash"],
            decompose_cost_usd=float(data["decompose_cost_usd"]),
            aggregate_cost_usd=float(data["aggregate_cost_usd"]),
            escalated_at=data["escalated_at"], pic_id=str(data.get("pic_id") or ""),
            room_id=str(data.get("room_id") or ""),
            steps=steps,
        )

    def list_open(self) -> list[TeamTask]:
        """VISIBILITY list (status views/room feeds) — includes `planning` drafts.
        NEVER use this to decide what the ticker may dispatch; see `list_dispatchable`.
        """
        rows = self._conn.execute(
            f"SELECT id FROM team_tasks WHERE status IN "
            f"({','.join('?' * len(_OPEN_TASK_STATUSES))}) ORDER BY created_at",
            _OPEN_TASK_STATUSES,
        ).fetchall()
        tasks = [self.get(r[0]) for r in rows]
        return [t for t in tasks if t is not None]

    def list_workrooms(self) -> list[dict]:
        """v16 rooms-list surface: tasks grouped by EFFECTIVE workroom (`room_id or id`),
        newest first. Excludes `planning` (an unconfirmed preview draft is not a room
        yet) and `cancelled` (an abandoned draft never becomes one). Rollup: any
        stalled -> 'ket'; else any non-done -> 'dang-chay'; else 'xong'."""
        rows = self._conn.execute(
            "SELECT id, title, status, created_at, COALESCE(room_id, '') AS room_id "
            "FROM team_tasks WHERE status NOT IN ('planning', 'cancelled') "
            "ORDER BY created_at"
        ).fetchall()
        rooms: dict[str, dict] = {}
        for task_id, title, status, created_at, room_id in rows:
            key = room_id or task_id
            room = rooms.setdefault(key, {
                "room_id": key, "title": title, "task_count": 0,
                "statuses": [], "updated_at": created_at,
            })
            room["task_count"] += 1
            room["statuses"].append(status)
            room["updated_at"] = max(room["updated_at"], created_at)
        out = []
        for room in rooms.values():
            statuses = room.pop("statuses")
            if any(s == "stalled" for s in statuses):
                room["status"] = "ket"
            elif any(s != "done" for s in statuses):
                room["status"] = "dang-chay"
            else:
                room["status"] = "xong"
            out.append(room)
        out.sort(key=lambda r: r["updated_at"], reverse=True)
        return out

    def tasks_in_room(self, room_id: str) -> list[TeamTask]:
        """Every non-draft task whose EFFECTIVE workroom is `room_id` (v16 QA/chat
        surface) — includes done/stalled tasks `list_open` hides, excludes
        planning/cancelled drafts like `list_workrooms`."""
        rows = self._conn.execute(
            "SELECT id FROM team_tasks WHERE status NOT IN ('planning', 'cancelled') "
            "AND (room_id = ? OR (COALESCE(room_id, '') = '' AND id = ?)) "
            "ORDER BY created_at",
            (room_id, room_id),
        ).fetchall()
        return [t for (task_id,) in rows if (t := self.get(task_id)) is not None]

    def list_recent_tasks(self, limit: int = 200, *,
                          include_planning: bool = False) -> list[TeamTask]:
        """Read-only newest-first task list for cross-room surfaces (outputs hub /
        kanban board). Excludes `cancelled` always; excludes `planning` drafts unless
        the caller is a board that wants the draft column. NEVER a dispatch source —
        see `list_dispatchable`."""
        excluded = ("cancelled",) if include_planning else ("cancelled", "planning")
        rows = self._conn.execute(
            f"SELECT id FROM team_tasks WHERE status NOT IN "
            f"({','.join('?' * len(excluded))}) ORDER BY created_at DESC LIMIT ?",
            (*excluded, int(limit)),
        ).fetchall()
        return [t for (task_id,) in rows if (t := self.get(task_id)) is not None]

    def list_dispatchable(self) -> list[TeamTask]:
        """DISPATCH list — the ONLY task set the coordinator ticker may act on.

        `open`/`running` only: a `planning` task is a CEO-previewed but NOT YET
        `confirm_plan`-confirmed draft. Confirm is the one gate that flips a task out
        of `planning` (see `confirm_plan`'s docstring); the ticker must never
        second-guess that gate by acting on a task still sitting in it.
        """
        rows = self._conn.execute(
            f"SELECT id FROM team_tasks WHERE status IN "
            f"({','.join('?' * len(_DISPATCHABLE_TASK_STATUSES))}) ORDER BY created_at",
            _DISPATCHABLE_TASK_STATUSES,
        ).fetchall()
        tasks = [self.get(r[0]) for r in rows]
        return [t for t in tasks if t is not None]

    def set_task_status(self, task_id: str, status: str) -> None:
        if status not in _TASK_STATUSES:
            raise ValueError(
                f"invalid team task status {status!r}; expected one of {_TASK_STATUSES}"
            )
        self._conn.execute("UPDATE team_tasks SET status = ? WHERE id = ?", (status, task_id))
        self._conn.commit()

    def cancel_draft(self, task_id: str) -> bool:
        """CEO "huỷ" at preview time: terminalize an unconfirmed `planning` draft so it
        can never be picked up by the ticker later. Returns False (no-op) when the task
        is missing or already past `planning` (e.g. confirmed/dispatched in the race
        between preview and this call) — cancelling a live task is `cancel_task`'s job,
        not this one's; a draft is only cancellable while still a draft."""
        cur = self._conn.execute(
            "UPDATE team_tasks SET status = 'cancelled' WHERE id = ? AND status = 'planning'",
            (task_id,),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def record_task_cost(self, task_id: str, *, decompose: float | None = None,
                          aggregate: float | None = None) -> None:
        """Add to `decompose_cost_usd` / `aggregate_cost_usd` (coordinator-level LLM
        spend, distinct from per-step cost). Either kwarg may be omitted."""
        if decompose is not None:
            self._conn.execute(
                "UPDATE team_tasks SET decompose_cost_usd = decompose_cost_usd + ? WHERE id = ?",
                (decompose, task_id),
            )
        if aggregate is not None:
            self._conn.execute(
                "UPDATE team_tasks SET aggregate_cost_usd = aggregate_cost_usd + ? WHERE id = ?",
                (aggregate, task_id),
            )
        self._conn.commit()

    def sum_cost(self, task_id: str) -> float:
        """Total cost for a task = sum of step costs + decompose + aggregate cost."""
        task = self.get(task_id)
        if task is None:
            return 0.0
        step_total = sum(s.cost_usd or 0.0 for s in task.steps)
        return step_total + task.decompose_cost_usd + task.aggregate_cost_usd

    # ---- step lifecycle (delegates to team_task_steps) -----------------------

    def get_step(self, task_id: str, step_id: str) -> TeamStep | None:
        return _steps.get_step(self._conn, task_id, step_id)

    def next_pending_step(self, task_id: str) -> TeamStep | None:
        """The lowest-`seq` `pending` step whose deps are ALL `done` — or None if no
        step is ready yet (either everything is done, or the ready step is blocked on
        a still-running/failed dependency)."""
        return _steps.next_pending_step(self._conn, task_id)

    def reserve_step(self, task_id: str, step_id: str) -> str:
        """Claim a step for a fresh spawn attempt: issues a new `attempt_id`, marks the
        step `running`, sets `spawned_at`/`last_seen`/`lease_expires_at`. Returns the
        `attempt_id` (the lease token the worker must present back on `--attempt-id`).

        Always claims — the caller (the ticker) owns the re-reserve decision (lease
        expired AND outcome artifact absent) BEFORE calling this.
        """
        attempt_id = _steps.reserve_step(
            self._conn, task_id, step_id, lease_ttl_s=self._lease_ttl_s
        )
        self._conn.commit()
        return attempt_id

    def lease_expired(self, task_id: str, step_id: str, *, now: datetime | None = None) -> bool:
        """True when the step's `lease_expires_at` is set and in the past (or the step
        has no lease at all, e.g. still `pending`)."""
        return _steps.lease_expired(self._conn, task_id, step_id, now=now)

    def verify_attempt(self, task_id: str, step_id: str, attempt_id: str) -> bool:
        """True iff the step is `running` with EXACTLY this `attempt_id` — the check a
        worker makes before doing any work, so a stale/forged/absent attempt-id is a
        clean no-op rather than a duplicate spawn racing the legitimate one."""
        return _steps.verify_attempt(self._conn, task_id, step_id, attempt_id)

    def record_spawn(self, task_id: str, step_id: str, pid: int) -> None:
        _steps.record_spawn(self._conn, task_id, step_id, pid)
        self._conn.commit()

    def heartbeat(self, task_id: str, step_id: str) -> None:
        """Refresh `last_seen` + push `lease_expires_at` out another TTL window — the
        long-running-but-alive path (distinct from a dead lease)."""
        _steps.heartbeat(self._conn, task_id, step_id, lease_ttl_s=self._lease_ttl_s)
        self._conn.commit()

    def mark_running(self, task_id: str, step_id: str) -> None:
        _steps.set_step_status(self._conn, task_id, step_id, "running")
        self._conn.commit()

    def mark_awaiting_approval(self, task_id: str, step_id: str, *,
                                attempt_id: str | None = None,
                                approval_id: int | None = None) -> bool:
        """Mark a step paused on an approval gate. Same `attempt_id` no-op guard as
        `mark_done` — the worker that hit the gate passes its own attempt_id; the
        ticker's later resume-path call (re-spawn) passes none (it holds no lease).

        `approval_id` (the `ApprovalStore` row id the gateway queued this write under,
        `GatewayResult.approval_id`) is persisted on the step so the ticker can later
        poll that SAME approval and resume the step once a human decides — a step
        marked `awaiting_approval` with no `approval_id` (e.g. every test double that
        gates on a plain bool, or any future gate not backed by `ApprovalStore`) is
        simply never auto-resumed by the ticker; it stays exactly as un-pollable as
        before this field existed.
        """
        updated = _steps.set_step_status(
            self._conn, task_id, step_id, "awaiting_approval", attempt_id=attempt_id,
            approval_id=approval_id,
        )
        self._conn.commit()
        return updated

    def mark_waiting_clarify(self, task_id: str, step_id: str, *,
                             attempt_id: str | None = None,
                             clarify_id: int | None = None) -> bool:
        """v34 P2: mark a step paused mid-graph on a CEO clarify interrupt. Mirrors
        `mark_awaiting_approval` exactly: worker-only write (holds + passes its own
        attempt_id), `clarify_id` persisted so the ticker can poll the ClarifyStore
        and resume once the CEO answers (or the question expires). A row without a
        clarify_id is never auto-resumed — same un-pollable contract as an
        awaiting_approval row without an approval_id."""
        updated = _steps.set_step_status(
            self._conn, task_id, step_id, "waiting_clarify", attempt_id=attempt_id,
            clarify_id=clarify_id,
        )
        self._conn.commit()
        return updated

    def mark_done(self, task_id: str, step_id: str, *, outcome_ref: str | None = None,
                  cost_usd: float | None = None, attempt_id: str | None = None,
                  split_proposal_json: str | None = None) -> bool:
        """Mark a step done. When `attempt_id` is given, the write only applies if that
        is still the step's CURRENT lease (see `team_task_steps.set_step_status`) —
        returns False (no-op) if a newer attempt has since reserved the step.
        `split_proposal_json` (v34 P4): the fan-out proposal this step delivered
        instead of content — the ticker's fanout-insert rule consumes it."""
        updated = _steps.set_step_status(
            self._conn, task_id, step_id, "done", outcome_ref=outcome_ref, cost_usd=cost_usd,
            attempt_id=attempt_id, split_proposal_json=split_proposal_json,
        )
        self._conn.commit()
        return updated

    def mark_failed(self, task_id: str, step_id: str, *, outcome_ref: str | None = None,
                     cost_usd: float | None = None, attempt_id: str | None = None) -> bool:
        """Mark a step failed. Same `attempt_id` no-op guard as `mark_done`."""
        updated = _steps.set_step_status(
            self._conn, task_id, step_id, "failed", outcome_ref=outcome_ref, cost_usd=cost_usd,
            attempt_id=attempt_id,
        )
        self._conn.commit()
        return updated

    def mark_timeout(self, task_id: str, step_id: str, *, attempt_id: str | None = None) -> bool:
        """Mark a step timed out. Same `attempt_id` no-op guard as `mark_done`/
        `mark_failed`: the ticker passes the lease it read the step under, so a
        concurrent re-reservation (a second ticker instance, or the worker's own
        terminal write racing this one) makes this a clean no-op instead of clobbering
        a newer attempt's row. Returns True iff a row was actually updated."""
        updated = _steps.set_step_status(
            self._conn, task_id, step_id, "timeout", attempt_id=attempt_id
        )
        self._conn.commit()
        return updated

    def append_outcome(self, task_id: str, step_id: str, outcome_ref: str) -> None:
        """Record the handoff-artifact path a step produced (does not change status)."""
        _steps.append_outcome(self._conn, task_id, step_id, outcome_ref)
        self._conn.commit()

    def insert_step(self, task_id: str, step: dict[str, Any], *,
                    needs_review: bool = False) -> None:
        """Append one ticker-minted row (review/rework/sub/gather) — see
        `team_task_steps.insert_step`'s docstring for the `system_inserted` forcing
        and the explicit `needs_review` opt-in (gather rows only)."""
        _steps.insert_step(self._conn, task_id, step, needs_review=needs_review)
        self._conn.commit()

    def insert_steps_atomic(self, task_id: str,
                            rows: list[tuple[dict[str, Any], bool]]) -> None:
        """Append SEVERAL ticker-minted rows in ONE transaction (v34 P4 fan-out mints
        N subs + 1 gather together — a crash between per-row commits would strand
        subs without their gather forever, since the children-exist idempotency guard
        then refuses a re-mint). `rows` = [(step_dict, needs_review)]. All-or-nothing:
        any failure rolls the whole mint back."""
        try:
            for step, needs_review in rows:
                _steps.insert_step(self._conn, task_id, step, needs_review=needs_review)
        except Exception:
            self._conn.rollback()
            raise
        self._conn.commit()

    def consume_split_proposal(self, task_id: str, step_id: str) -> None:
        """NULL a step's split proposal (v34 P4: an invalid proposal is consumed so
        the fanout rule never re-fires for it). Dedicated method because
        `set_step_status`'s COALESCE writes can never express NULL."""
        _steps.clear_split_proposal(self._conn, task_id, step_id)
        self._conn.commit()

    # ---- amendment drafts (delegates to team_task_amend) ---------------------

    def set_amendment_draft(
        self, task_id: str, *, base_plan_hash: str, new_plan_hash: str,
        new_pending_steps: list[dict[str, Any]], old_pending_step_ids: list[str],
    ) -> str:
        """Persist a full-replan draft (preview time); terminalizes any prior LIVE
        draft for the same task first. See `team_task_amend` module docstring.

        `old_pending_step_ids`: the step_ids `pending` right now (draft time) — the
        exact set this amend intends to replace; `confirm_amendment` re-verifies every
        one of these is STILL `pending` at confirm time (see `team_task_amend
        .set_amendment_draft`'s docstring for why `base_plan_hash` alone can't catch a
        bare status race)."""
        # v34 P4 (review M2): an amend swaps ALL pending rows — pending subs/gather
        # included. That would orphan a split parent forever on its "Đã chia bước"
        # notice (the gather that was to replace it is gone), so drafting is refused
        # while any fan-out child is still un-done. The CEO can amend again once the
        # split finishes (or cancel the task).
        unfinished_fanout = self._conn.execute(
            "SELECT COUNT(*) FROM team_steps WHERE task_id = ? AND system_inserted = 1 "
            "AND step_type = 'work' AND parent_step_id IS NOT NULL AND status != 'done'",
            (task_id,),
        ).fetchone()[0]
        if unfinished_fanout:
            raise ValueError(
                "việc này đang có bước được chia nhỏ chạy song song — đợi các việc con "
                "xong (hoặc huỷ việc) rồi mới chỉnh kế hoạch được"
            )
        amendment_id = _amend.set_amendment_draft(
            self._conn, task_id, base_plan_hash=base_plan_hash, new_plan_hash=new_plan_hash,
            new_pending_steps=new_pending_steps, old_pending_step_ids=old_pending_step_ids,
        )
        self._conn.commit()
        return amendment_id

    def get_amendment_draft(self, amendment_id: str) -> AmendmentDraft | None:
        return _amend.get_draft(self._conn, amendment_id)

    def cancel_amendment_draft(self, amendment_id: str) -> bool:
        """CEO "huỷ" at preview time — only a still-`draft` row is cancellable."""
        cancelled = _amend.cancel_amendment_draft(self._conn, amendment_id)
        self._conn.commit()
        return cancelled

    def confirm_amendment(self, task_id: str, amendment_id: str) -> ConfirmAmendmentResult:
        """TOCTOU-proof confirm for a full replan: ONE `BEGIN IMMEDIATE` transaction
        that re-validates the draft's `base_plan_hash` against the task's CURRENT
        full-DAG hash, swaps the `pending` step set, binds the new `plan_hash`, and
        consumes the draft. See `team_task_amend.confirm_amendment`'s docstring for
        the full TOCTOU rationale; commits/rolls back internally, never leaves an
        open transaction on this connection."""
        return _amend.confirm_amendment(self._conn, task_id, amendment_id)

    def cleanup_stale_amendment_drafts(self, *, ttl_s: int = _amend.DEFAULT_DRAFT_TTL_S) -> int:
        """Terminalize abandoned drafts older than `ttl_s` — best-effort hygiene, not
        correctness-critical (see `team_task_amend.cleanup_stale_drafts`'s docstring)."""
        expired = _amend.cleanup_stale_drafts(self._conn, ttl_s=ttl_s)
        self._conn.commit()
        return expired

    def close(self) -> None:
        self._conn.close()
