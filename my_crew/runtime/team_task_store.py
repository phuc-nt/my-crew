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

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from my_crew.runtime import team_task_amend as _amend
from my_crew.runtime import team_task_steps as _steps
from my_crew.runtime.team_task_amend import (  # re-exported for callers
    AmendmentDraft,
    ConfirmAmendmentResult,
    full_dag_plan_hash,
)
from my_crew.runtime.team_task_paths import team_tasks_db_path, team_tasks_root
from my_crew.runtime.team_task_steps import TeamStep  # re-exported for callers

logger = logging.getLogger(__name__)

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
    # v63 autopilot: True ⇒ this task opted OUT of autopilot ("vụ này để anh duyệt") —
    # every manual gate (plan confirm, Lớp B approval, stall decisions) stays with the
    # CEO for it even while the global autopilot flag is on.
    require_ceo_approval: bool = False
    # v63 autopilot: stall auto-resolutions already spent on this task (capped in
    # `autopilot_sweep` — auto-recovery must converge, never loop).
    autopilot_attempts: int = 0
    # Times this task was revived from `stalled`. Keys the reflection cooldown marker so
    # each stall-after-retry is reflected on once, rather than only the very first stall.
    reopen_count: int = 0
    # v67 delivery split — execution status (`status`) vs "did the final summary
    # actually reach the room milestone". Only the ticker's aggregate path uses these;
    # CEO-interactive completions (accept_stalled_result, cancel) stay 'not_applicable'.
    delivery_status: str = "not_applicable"
    delivery_attempts: int = 0
    final_summary: str | None = None
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
        # v63 autopilot columns: `require_ceo_approval` (per-task opt-OUT of autopilot —
        # this task keeps every manual gate) + `autopilot_attempts` (how many stall
        # auto-resolutions autopilot already spent on this task, hard-capped by
        # `autopilot_sweep` so auto-recovery can never loop). Neither enters plan_hash.
        for ddl in (
            "ALTER TABLE team_tasks ADD COLUMN last_follow_up_at TEXT",
            "ALTER TABLE team_tasks ADD COLUMN follow_up_level INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE team_tasks ADD COLUMN require_ceo_approval INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE team_tasks ADD COLUMN autopilot_attempts INTEGER NOT NULL DEFAULT 0",
            # v67 delivery split: a task can be `done` (execution) while its final
            # summary never reached the room milestone (delivery). `final_summary` is
            # persisted BEFORE the first delivery attempt so a retry re-sends the same
            # text instead of re-running the aggregate LLM call.
            "ALTER TABLE team_tasks ADD COLUMN delivery_status TEXT NOT NULL "
            "DEFAULT 'not_applicable'",
            "ALTER TABLE team_tasks ADD COLUMN delivery_attempts INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE team_tasks ADD COLUMN final_summary TEXT",
            # How many times this task came back from `stalled` (`reopen_stalled`). The
            # reflection cooldown marker is keyed by it, so the stall AFTER a CEO retry
            # — the most informative one, since the first fix demonstrably did not work
            # — gets its own reflection instead of being swallowed as "already looked at".
            "ALTER TABLE team_tasks ADD COLUMN reopen_count INTEGER NOT NULL DEFAULT 0",
            # v78 routing log: which way the team-vs-sprint router sent this task and
            # on what evidence. Nullable on purpose — tasks assigned before v78 have no
            # honest answer and are left NULL rather than backfilled with a guess. It
            # sits in this table, not a separate log, so one query puts the routing
            # decision next to the outcome columns (wall time, cost, rework) that say
            # whether it was the right one.
            "ALTER TABLE team_tasks ADD COLUMN route_json TEXT",
        ):
            try:
                self._conn.execute(ddl)
            except sqlite3.OperationalError:
                pass  # column already exists
        _steps.create_schema(self._conn)
        _amend.create_schema(self._conn)
        from my_crew.runtime.store_schema_meta import ensure_schema_meta

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
        return self._task_from_data(data, _steps.steps_for_task(self._conn, task_id))

    def _task_from_data(self, data: dict, steps: tuple[TeamStep, ...]) -> TeamTask:
        return TeamTask(
            id=data["id"], title=data["title"], original_request=data["original_request"],
            status=data["status"], created_at=data["created_at"], assigned_by=data["assigned_by"],
            cost_usd_total=float(data["cost_usd_total"]), plan_hash=data["plan_hash"],
            decompose_cost_usd=float(data["decompose_cost_usd"]),
            aggregate_cost_usd=float(data["aggregate_cost_usd"]),
            escalated_at=data["escalated_at"], pic_id=str(data.get("pic_id") or ""),
            room_id=str(data.get("room_id") or ""),
            require_ceo_approval=bool(int(data.get("require_ceo_approval") or 0)),
            autopilot_attempts=int(data.get("autopilot_attempts") or 0),
            reopen_count=int(data.get("reopen_count") or 0),
            delivery_status=str(data.get("delivery_status") or "not_applicable"),
            delivery_attempts=int(data.get("delivery_attempts") or 0),
            final_summary=data.get("final_summary"),
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
        # Bulk hydration (2 queries total) — the per-id get() loop this replaces was
        # ~2 queries per task, which at the board's 200-task limit meant ~400 queries
        # per page load.
        cur = self._conn.execute(
            f"SELECT * FROM team_tasks WHERE status NOT IN "
            f"({','.join('?' * len(excluded))}) ORDER BY created_at DESC LIMIT ?",
            (*excluded, int(limit)),
        )
        cols = [d[0] for d in cur.description]
        datas = [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
        steps_by_task = _steps.steps_for_tasks(self._conn, [d["id"] for d in datas])
        return [self._task_from_data(d, steps_by_task.get(d["id"], ())) for d in datas]

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

    def list_stalled(self) -> list[TeamTask]:
        """Every `stalled` task, no recency cap — the autopilot sweep and the
        waiting-decision surfaces must see ALL of them (review M3: a stalled task
        older than the N newest would otherwise silently never be swept/counted)."""
        rows = self._conn.execute(
            "SELECT id FROM team_tasks WHERE status = 'stalled' ORDER BY created_at DESC"
        ).fetchall()
        return [t for (task_id,) in rows if (t := self.get(task_id)) is not None]

    def cancelled_tasks_with_running_steps(self) -> list[TeamTask]:
        """Every `cancelled` task that still has at least one `running` step — the
        cancel-reap sweep's work list (`team_task_halt`). Cancelled tasks leave
        `list_dispatchable`, so without this query their in-flight workers are never
        polled or killed again and keep billing (the A9 post-cancel drift). Derived
        fresh from the tables each call, so every cancel surface is covered without
        registering itself anywhere; an empty list is the steady state."""
        rows = self._conn.execute(
            "SELECT DISTINCT t.id FROM team_tasks t JOIN team_steps s ON s.task_id = t.id "
            "WHERE t.status = 'cancelled' AND s.status = 'running' ORDER BY t.created_at"
        ).fetchall()
        return [t for (task_id,) in rows if (t := self.get(task_id)) is not None]

    def reopen_stalled(self, task_id: str) -> bool:
        """Status-guarded `stalled → open` transition (review M2): the stall handlers
        and the autopilot sweep both act on a read snapshot — the WHERE guard makes a
        raced reopen (task already reopened/cancelled by the other actor) a clean
        no-op instead of resurrecting a task from an arbitrary state.

        `reopen_count` rides the SAME guarded UPDATE, so a raced/no-op reopen never
        inflates it — the counter means "times this task actually came back to life",
        which is exactly the generation the reflection cooldown marker keys on."""
        cur = self._conn.execute(
            "UPDATE team_tasks SET status = 'open', reopen_count = reopen_count + 1 "
            "WHERE id = ? AND status = 'stalled'",
            (task_id,),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def set_require_ceo_approval(self, task_id: str, value: bool) -> None:
        """v63 per-task autopilot opt-out — set at assign time ("vụ này để anh duyệt")."""
        self._conn.execute(
            "UPDATE team_tasks SET require_ceo_approval = ? WHERE id = ?",
            (1 if value else 0, task_id),
        )
        self._conn.commit()

    def set_route(self, task_id: str, route: dict) -> None:
        """v78: ghi bản ghi định tuyến (mode/source/reason/signals) cho task này."""
        import json

        self._conn.execute(
            "UPDATE team_tasks SET route_json = ? WHERE id = ?",
            (json.dumps(route, ensure_ascii=False), task_id),
        )
        self._conn.commit()

    def get_route(self, task_id: str) -> dict | None:
        """Bản ghi định tuyến đã lưu, hoặc None nếu chưa có / JSON hỏng.

        Nuốt lỗi giải mã có chủ ý: đây là dữ liệu quan sát, không phải dữ liệu vận
        hành. Một dòng log hỏng không được phép làm hỏng đường đi của task.
        """
        import json

        row = self._conn.execute(
            "SELECT route_json FROM team_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not row or not row[0]:
            return None
        try:
            value = json.loads(row[0])
        except (ValueError, TypeError):
            return None
        return value if isinstance(value, dict) else None

    def list_routes(self, limit: int = 500) -> list[tuple[dict, str]]:
        """Các bản ghi định tuyến gần đây kèm trạng thái task: `[(route, status), ...]`.

        Một truy vấn cho cả bảng thay vì `get_route` từng task: người gọi duy nhất là
        lệnh thống kê, nó cần TOÀN BỘ để đếm — vòng lặp N+1 ở đây chỉ tổ đọc chậm cùng
        một dữ liệu.

        Bỏ qua dòng JSON hỏng như `get_route`: thống kê thiếu một dòng vẫn dùng được,
        thống kê nổ thì không.
        """
        import json

        rows = self._conn.execute(
            "SELECT route_json, status FROM team_tasks "
            "WHERE route_json IS NOT NULL AND route_json != '' "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        out: list[tuple[dict, str]] = []
        for raw, status in rows:
            try:
                value = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if isinstance(value, dict):
                out.append((value, str(status or "")))
        return out

    def increment_autopilot_attempts(self, task_id: str) -> int:
        """v63: bump + return this task's spent stall auto-resolutions (sweep cap)."""
        self._conn.execute(
            "UPDATE team_tasks SET autopilot_attempts = autopilot_attempts + 1 WHERE id = ?",
            (task_id,),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT autopilot_attempts FROM team_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        return int(row[0]) if row else 0

    _DELIVERY_STATUSES = ("not_applicable", "pending", "delivered", "failed")

    def set_delivery(self, task_id: str, *, status: str, summary: str | None = None) -> None:
        """v67: record the delivery leg of a finished task. `summary` is only
        written when given (the pending-write persists it once; the later
        delivered/failed flips leave it untouched)."""
        if status not in self._DELIVERY_STATUSES:
            raise ValueError(
                f"invalid delivery status {status!r}; expected one of {self._DELIVERY_STATUSES}"
            )
        if summary is not None:
            self._conn.execute(
                "UPDATE team_tasks SET delivery_status = ?, final_summary = ? WHERE id = ?",
                (status, summary, task_id),
            )
        else:
            self._conn.execute(
                "UPDATE team_tasks SET delivery_status = ? WHERE id = ?", (status, task_id),
            )
        self._conn.commit()

    def increment_delivery_attempts(self, task_id: str) -> int:
        """v67: bump + return this task's delivery retry count (sweep cap bookkeeping)."""
        self._conn.execute(
            "UPDATE team_tasks SET delivery_attempts = delivery_attempts + 1 WHERE id = ?",
            (task_id,),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT delivery_attempts FROM team_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        return int(row[0]) if row else 0

    def list_undelivered(self) -> list[TeamTask]:
        """v67: `done` tasks whose summary never reached the room (`pending` — the
        crash window between mark-done and the delivery write — or `failed`). The
        delivery-retry sweep is the only caller; it owns the attempts cap."""
        rows = self._conn.execute(
            "SELECT id FROM team_tasks WHERE status = 'done' "
            "AND delivery_status IN ('pending', 'failed') ORDER BY created_at"
        ).fetchall()
        return [t for (task_id,) in rows if (t := self.get(task_id)) is not None]

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

    def cancel_task(self, task_id: str) -> bool:
        """CEO "huỷ" a LIVE task (open/running/stalled) — the `cancel_draft` sibling for
        every status past `planning`. Same TOCTOU-proof shape as `confirm_plan`/
        `reopen_stalled`: one guarded UPDATE, no read-then-write — two concurrent cancels
        (or a cancel racing the ticker's own terminal write) leave exactly one winner,
        the other a clean no-op via `rowcount == 0`.

        Deliberately does NOT touch `team_steps` here: a cancelled task drops out of
        `list_dispatchable` on the next read, and any step still `running` is reaped by
        `team_task_halt.run_cancel_reap_sweep` (runs every tick — see that module's
        docstring for why the kill lives there and not inline in every cancel caller).
        Returns False when the task is missing or already in a terminal state
        (`done`/`cancelled`) or still `planning` (use `cancel_draft` for that one)."""
        cur = self._conn.execute(
            "UPDATE team_tasks SET status = 'cancelled' WHERE id = ? "
            "AND status IN ('open', 'running', 'stalled')",
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

    def reserve_step(self, task_id: str, step_id: str, *,
                     only_if_pending: bool = False,
                     only_if_attempt: str | None = None) -> str | None:
        """Claim a step for a fresh spawn attempt: issues a new `attempt_id`, marks the
        step `running`, sets `spawned_at`/`last_seen`/`lease_expires_at`. Returns the
        `attempt_id` (the lease token the worker must present back on `--attempt-id`).

        Always claims — the caller (the ticker) owns the re-reserve decision (lease
        expired AND outcome artifact absent) BEFORE calling this.

        With `only_if_pending` (first dispatch) or `only_if_attempt` (re-reserve of a
        dead/expired `running` row), the claim is conditional and returns None when
        another ticker already took it. See `team_task_steps.reserve_step` for why
        each dispatch shape needs its own condition.
        """
        attempt_id = _steps.reserve_step(
            self._conn, task_id, step_id, lease_ttl_s=self._lease_ttl_s,
            only_if_pending=only_if_pending, only_if_attempt=only_if_attempt,
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

    def _terminal_write(self, task_id: str, step_id: str, status: str, *,
                         attempt_id: str | None, quiet: bool = False, **kwargs) -> bool:
        """One terminal status write, with the no-op made audible.

        Every `mark_*` below is the LAST thing that happens to a step, so a write that
        silently matches no row leaves the step alive in a task that has already moved
        on — a `stalled` task holding a `pending` step is exactly that hybrid, and it
        went unnoticed because the boolean was dropped at every call site. The guard
        doing its job (a concurrent re-reservation) and the guard misfiring (a stale
        snapshot's attempt_id) are indistinguishable from here, so this logs rather
        than raises; callers that can repair the miss check the return value and pass
        `quiet=True` so their own recovery attempt does not log a miss they handle.
        """
        updated = _steps.set_step_status(
            self._conn, task_id, step_id, status, attempt_id=attempt_id, **kwargs,
        )
        self._conn.commit()
        if not updated and not quiet:
            logger.warning(
                "team-step terminal write matched no row: task=%s step=%s status=%s "
                "attempt_id=%s — step keeps its current status",
                task_id, step_id, status, attempt_id or "<none>",
            )
        return updated

    def mark_done(self, task_id: str, step_id: str, *, outcome_ref: str | None = None,
                  cost_usd: float | None = None, attempt_id: str | None = None,
                  split_proposal_json: str | None = None) -> bool:
        """Mark a step done. When `attempt_id` is given, the write only applies if that
        is still the step's CURRENT lease (see `team_task_steps.set_step_status`) —
        returns False (no-op) if a newer attempt has since reserved the step.
        `split_proposal_json` (v34 P4): the fan-out proposal this step delivered
        instead of content — the ticker's fanout-insert rule consumes it."""
        return self._terminal_write(
            task_id, step_id, "done", attempt_id=attempt_id, outcome_ref=outcome_ref,
            cost_usd=cost_usd, split_proposal_json=split_proposal_json,
        )

    def mark_needs_decision(self, task_id: str, step_id: str, *,
                            outcome_ref: str | None = None,
                            cost_usd: float | None = None,
                            attempt_id: str | None = None) -> bool:
        """Mark a step as produced-but-not-acceptable. Same `attempt_id` no-op guard as
        `mark_done`.

        The step ran to completion and wrote a real artifact — `outcome_ref` is the
        whole point, since the coordinator has to READ that artifact to decide what
        happens next. That is what separates this from `mark_failed`, where there is
        nothing to read. Downstream steps do not treat it as a satisfied dependency, so
        an unacceptable result never becomes another step's input.
        """
        return self._terminal_write(
            task_id, step_id, "needs_decision", attempt_id=attempt_id,
            outcome_ref=outcome_ref, cost_usd=cost_usd,
        )

    def mark_failed(self, task_id: str, step_id: str, *, outcome_ref: str | None = None,
                     cost_usd: float | None = None, attempt_id: str | None = None,
                     quiet: bool = False) -> bool:
        """Mark a step failed. Same `attempt_id` no-op guard as `mark_done`.

        `quiet` suppresses the no-op warning for the one caller that recovers from a
        guard miss itself (`stuck_decision._give_up`) — it retries via
        `mark_failed_if_pending` and logs only if that fails too.
        """
        return self._terminal_write(
            task_id, step_id, "failed", attempt_id=attempt_id, outcome_ref=outcome_ref,
            cost_usd=cost_usd, quiet=quiet,
        )

    def mark_failed_if_pending(self, task_id: str, step_id: str) -> bool:
        """Terminate a step that is `pending` — no attempt guard, by design.

        The recovery path for `mark_failed`'s guard matching nothing because the row
        was RELEASED rather than re-reserved: `reset_step_to_pending` clears attempt_id,
        so a caller holding a pre-reset snapshot guards on a lease that no longer
        exists. A pending row has no worker in flight to clobber, so the attempt guard
        buys nothing here; `only_if_status` supplies the atomicity instead, keeping the
        write a clean no-op if the step got re-reserved in the meantime.
        """
        return self._terminal_write(
            task_id, step_id, "failed", attempt_id=None, only_if_status="pending",
        )

    def halt_step(self, task_id: str, step_id: str, *, attempt_id: str | None) -> bool:
        """Atomic running→failed for the in-flight brake (`team_task_halt`). Guarded
        on BOTH the attempt AND the status still being `running` — unlike the
        lease-expiry kill (worker presumed dead), the brake races a LIVE worker whose
        own terminal write keeps the attempt_id, so `mark_failed`'s attempt guard
        alone would let a halt clobber a `done` row the worker landed a moment
        earlier. Returns True iff this call actually terminated the row."""
        updated = _steps.set_step_status(
            self._conn, task_id, step_id, "failed",
            attempt_id=attempt_id, only_if_status="running",
        )
        self._conn.commit()
        return updated

    def mark_timeout(self, task_id: str, step_id: str, *, attempt_id: str | None = None) -> bool:
        """Mark a step timed out. Same `attempt_id` no-op guard as `mark_done`/
        `mark_failed`: the ticker passes the lease it read the step under, so a
        concurrent re-reservation (a second ticker instance, or the worker's own
        terminal write racing this one) makes this a clean no-op instead of clobbering
        a newer attempt's row. Returns True iff a row was actually updated."""
        return self._terminal_write(task_id, step_id, "timeout", attempt_id=attempt_id)

    def append_outcome(self, task_id: str, step_id: str, outcome_ref: str) -> None:
        """Record the handoff-artifact path a step produced (does not change status)."""
        _steps.append_outcome(self._conn, task_id, step_id, outcome_ref)
        self._conn.commit()

    def reset_step_to_pending(self, task_id: str, step_id: str, *,
                              attempt_id: str | None = None) -> bool:
        """v63 stall recovery (`retry_stalled_step` on a dead step): put a terminal
        `failed`/`timeout` step back to `pending` with its lease fields cleared, so the
        next tick re-dispatches it as a fresh attempt. The `attempt_id` guard mirrors
        `mark_done`'s: pass the attempt the row was READ under so a concurrent
        re-reservation turns this into a no-op instead of clobbering it."""
        updated = _steps.reset_step_to_pending(
            self._conn, task_id, step_id, attempt_id=attempt_id,
        )
        self._conn.commit()
        if updated:
            self._clear_step_checkpoint(task_id, step_id)
        return updated

    def _clear_step_checkpoint(self, task_id: str, step_id: str) -> None:
        """A reset/reassign means REDO, not resume: a mid-run checkpoint left by a
        killed attempt would otherwise be adopted by the next attempt, which then
        resumes PAST `perceive` — so it never reads the coordinator's fresh guidance
        (guidance enters the context at perceive) and, if the saved position is the
        toolless `rework` node, it cannot search either. Observed live (task
        dfdc472c423c): consecutive retries re-emitted the identical 'xin cấp quyền tra
        cứu' letter within minutes because each adopted the same rework-node
        checkpoint. Crash-continuity resume (same attempt, no ruling) is untouched —
        this clears only when a ruling/CEO explicitly ordered a redo. Best-effort:
        checkpoints are an optimization, their DB must never break a store write."""
        try:
            from my_crew.runtime.team_task_paths import team_checkpoints_db_path

            thread_id = f"team:{task_id}:{step_id}"
            con = sqlite3.connect(team_checkpoints_db_path(), timeout=5)
            try:
                for table in ("checkpoints", "writes"):
                    try:
                        con.execute(f"delete from {table} where thread_id = ?", (thread_id,))
                    except sqlite3.OperationalError:
                        pass  # table absent (fresh/older schema) — nothing to clear
                con.commit()
            finally:
                con.close()
        except Exception:  # noqa: BLE001 — best-effort by contract
            logger.warning("could not clear checkpoint thread for %s/%s",
                           task_id, step_id, exc_info=True)

    def bump_intervention(self, task_id: str, step_id: str) -> int:
        """Record one coordinator intervention on a stuck step; returns the new total so
        the caller can enforce the intervention cap against a freshly-committed value."""
        total = _steps.bump_intervention(self._conn, task_id, step_id)
        self._conn.commit()
        return total

    def append_step_guidance(self, task_id: str, step_id: str, guidance: str) -> bool:
        """Attach coordinator direction to a step, preserving any earlier round's."""
        updated = _steps.append_step_guidance(self._conn, task_id, step_id, guidance)
        self._conn.commit()
        return updated

    def reassign_step(self, task_id: str, step_id: str, assigned_to: str) -> bool:
        """Hand a not-in-flight step to a different staffer (the coordinator's
        `reassign` decision). Callers MUST validate `assigned_to` against the roster
        first — this write trusts the id it is given.

        Re-stamps `plan_hash` in the SAME transaction as the assignee write. `assigned_to`
        is one of the fields `decomposition_content_hash` covers, so changing it
        without re-stamping would make the next tick's `_verify_plan_hash` recompute a
        different digest, stall the task, and escalate a tampering alarm about a change
        the coordinator itself made. WHO does a step is the coordinator's operational
        call; WHAT the steps are is the CEO's confirmed plan and still cannot change
        here (only `assigned_to` is written). Recomputed over the `system_inserted=0`
        subset — exactly what `_verify_plan_hash` compares against — so a task carrying
        auto-inserted review/rework rows re-stamps to the digest that check expects.
        Both writes share one commit: a tick reading between them would see a mismatch.
        """
        # A reassign is likewise a REDO under a new owner — never adopt the old
        # owner's mid-run checkpoint (see _clear_step_checkpoint).
        self._clear_step_checkpoint(task_id, step_id)
        updated = _steps.reassign_step(self._conn, task_id, step_id, assigned_to)
        if updated:
            self._conn.execute(
                "UPDATE team_tasks SET plan_hash = ? WHERE id = ?",
                (self._confirmed_plan_hash(task_id), task_id),
            )
        self._conn.commit()
        return updated

    def _confirmed_plan_hash(self, task_id: str) -> str:
        """The digest `coordinator_graph._verify_plan_hash` recomputes on every tick:
        `decomposition_content_hash` over the CEO-confirmed (`system_inserted = 0`) rows
        in `seq` order, read fresh from the connection so it reflects writes made earlier
        in the current (uncommitted) transaction.

        MUST select every column the hash reads — the conditional flags (`needs_shell`,
        `external_write`, `needs_web`, `needs_mail`) included. The verify side hashes real
        `TeamStep` rows where those flags resolve to their persisted values; reconstructing
        here without them silently hashes them as False, so re-stamping any task whose
        confirmed plan carries a True flag (every research plan sets `needs_web`) writes
        a digest the next tick can never reproduce — a permanent, self-inflicted
        plan_hash-mismatch stall right after a stuck-reassign."""
        from my_crew.agent.task_decomposition import decomposition_content_hash

        rows = self._conn.execute(
            "SELECT step_id, title, assigned_to, deps_json, needs_shell, external_write, "
            "needs_web, needs_mail FROM team_steps "
            "WHERE task_id = ? AND system_inserted = 0 ORDER BY seq",
            (task_id,),
        ).fetchall()
        steps = [
            SimpleNamespace(
                step_id=r[0], title=r[1], assigned_to=r[2],
                deps=tuple(json.loads(r[3] or "[]")),
                needs_shell=bool(r[4]), external_write=bool(r[5]), needs_web=bool(r[6]),
                needs_mail=bool(r[7]),
            )
            for r in rows
        ]
        return decomposition_content_hash(SimpleNamespace(steps=steps))

    def mark_step_dropped(self, task_id: str, step_id: str, *, outcome_ref: str | None = None,
                          attempt_id: str | None = None) -> bool:
        """Mark a given-up-on step `done` AND clear its `needs_review` in the same
        write — a dropped step delivers a placeholder artifact, and minting a peer
        review over a placeholder would immediately fail it back into the rework loop
        dropping exists to break. Two callers: v63 stall recovery (`drop_stalled_step`,
        dead `failed`/`timeout` rows) and the coordinator's skip-with-gap (a
        `needs_decision` row its judge ruled unrecoverable). The write also retires
        the attempt lease — see `_steps.mark_step_dropped` for why."""
        updated = _steps.mark_step_dropped(
            self._conn, task_id, step_id, outcome_ref=outcome_ref, attempt_id=attempt_id,
        )
        self._conn.commit()
        return updated

    def mark_done_by_coordinator(self, task_id: str, step_id: str, *,
                                 outcome_ref: str | None = None,
                                 cost_usd: float | None = None,
                                 attempt_id: str | None = None,
                                 keep_review: bool = False) -> bool:
        """The coordinator's own result lands on a step its assignee could not
        finish — see `_steps.mark_done_by_coordinator` for the status guard, why
        the attempt lease stays while the review flag falls, and when `keep_review`
        keeps it. Attempt-guarded like the drop: a concurrent re-reservation makes
        this a no-op, never a clobber."""
        updated = _steps.mark_done_by_coordinator(
            self._conn, task_id, step_id, outcome_ref=outcome_ref, cost_usd=cost_usd,
            attempt_id=attempt_id, keep_review=keep_review,
        )
        self._conn.commit()
        return updated

    def insert_step(self, task_id: str, step: dict[str, Any], *,
                    needs_review: bool = False, needs_web: bool = False,
                    needs_mail: bool = False) -> None:
        """Append one ticker-minted row (review/rework/sub/gather) — see
        `team_task_steps.insert_step`'s docstring for the `system_inserted` forcing
        and the explicit `needs_review`/`needs_web`/`needs_mail` opt-ins (gather /
        split-sub / rework rows)."""
        _steps.insert_step(self._conn, task_id, step, needs_review=needs_review,
                           needs_web=needs_web, needs_mail=needs_mail)
        self._conn.commit()

    def insert_steps_atomic(self, task_id: str,
                            rows: list[tuple[dict[str, Any], bool] |
                                       tuple[dict[str, Any], bool, bool] |
                                       tuple[dict[str, Any], bool, bool, bool]]) -> None:
        """Append SEVERAL ticker-minted rows in ONE transaction (v34 P4 fan-out mints
        N subs + 1 gather together — a crash between per-row commits would strand
        subs without their gather forever, since the children-exist idempotency guard
        then refuses a re-mint). `rows` = [(step_dict, needs_review)] or
        [(step_dict, needs_review, needs_web)] (v74 split subs) or
        [(step_dict, needs_review, needs_web, needs_mail)] (v92). All-or-nothing:
        any failure rolls the whole mint back."""
        try:
            for row in rows:
                step, needs_review = row[0], row[1]
                needs_web = bool(row[2]) if len(row) > 2 else False
                needs_mail = bool(row[3]) if len(row) > 3 else False
                _steps.insert_step(self._conn, task_id, step, needs_review=needs_review,
                                   needs_web=needs_web, needs_mail=needs_mail)
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
