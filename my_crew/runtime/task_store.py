"""Assigned-task store (v6 M15) — multi-day work an agent tracks, not one-shot commands.

M12 chat-command is one mention → one queued action → executed → DONE. A task is
different: it LIVES for days. "Theo dõi PR #45 tới khi merge, nhắc mỗi sáng" is one row
here that the runner revisits each tick until a CODE-decided stop condition fires.

Persisted in SQLite under the agent's data dir (same posture as ApprovalStore) so tasks
survive a service restart — a task assigned Monday is still watched Wednesday.

Lifecycle (status): open → (each check) running → done | cancelled | stalled.
- done: the stop condition fired (PR merged, issue closed, deadline passed).
- cancelled: the operator cancelled it.
- stalled: N consecutive checks errored (infra excluded) — surfaced, not silently looped.

Every check appends a HistoryEntry (ts + one-line summary + cost) so the board and the
"báo kết quả" reply can show what happened without re-deriving it.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: Cap on OPEN tasks per agent — a runaway assignment loop must not fill the store.
MAX_OPEN_TASKS = 10
#: Consecutive non-infra check failures before a task is marked `stalled`.
STALL_AFTER = 3

_OPEN_STATUSES = ("open", "running")


@dataclass(frozen=True)
class HistoryEntry:
    ts: str
    summary: str
    cost_usd: float | None = None


@dataclass(frozen=True)
class Task:
    id: int
    kind: str  # "watch" (M15a); "report"/"qa" later (M15b)
    params: dict[str, Any]  # type-specific (e.g. {"target": "pr", "number": 45})
    schedule: str  # cron string for the reminder cadence
    status: str  # open | running | done | cancelled | stalled
    created_at: str
    assigned_by: str  # who assigned it (chat user id) — for the audit trail
    fail_streak: int
    history: tuple[HistoryEntry, ...] = field(default_factory=tuple)


class TaskStore:
    """SQLite-backed queue of assigned multi-day tasks for one agent."""

    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS tasks ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  kind TEXT NOT NULL,"
            "  params_json TEXT NOT NULL,"
            "  schedule TEXT NOT NULL,"
            "  status TEXT NOT NULL DEFAULT 'open',"
            "  created_at TEXT NOT NULL,"
            "  assigned_by TEXT NOT NULL DEFAULT '',"
            "  fail_streak INTEGER NOT NULL DEFAULT 0,"
            "  history_json TEXT NOT NULL DEFAULT '[]'"
            ")"
        )
        self._conn.commit()

    def _now(self) -> str:
        return datetime.now(UTC).isoformat()

    def open_count(self) -> int:
        row = self._conn.execute(
            f"SELECT COUNT(*) FROM tasks WHERE status IN ({','.join('?' * len(_OPEN_STATUSES))})",
            _OPEN_STATUSES,
        ).fetchone()
        return int(row[0]) if row else 0

    def create(self, *, kind: str, params: dict[str, Any], schedule: str,
               assigned_by: str = "") -> int:
        """Add an OPEN task; returns its id. Raises RuntimeError past the open-task cap
        (a bounded blast radius — the runaway-assignment backstop, R1)."""
        if self.open_count() >= MAX_OPEN_TASKS:
            raise RuntimeError(
                f"đã đạt giới hạn {MAX_OPEN_TASKS} việc đang mở — hoàn tất/huỷ bớt "
                "trước khi giao thêm."
            )
        cur = self._conn.execute(
            "INSERT INTO tasks (kind, params_json, schedule, status, created_at, assigned_by) "
            "VALUES (?, ?, ?, 'open', ?, ?)",
            (kind, json.dumps(params, ensure_ascii=False), schedule, self._now(), assigned_by),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def _row_to_task(self, row: Any) -> Task:
        (id_, kind, params_json, schedule, status, created_at, assigned_by,
         fail_streak, history_json) = row
        try:
            params = json.loads(params_json)
        except (json.JSONDecodeError, TypeError):
            params = {}
        try:
            history = tuple(
                HistoryEntry(h["ts"], h["summary"], h.get("cost_usd"))
                for h in json.loads(history_json)
            )
        except (json.JSONDecodeError, TypeError, KeyError):
            history = ()
        return Task(int(id_), str(kind), dict(params), str(schedule), str(status),
                    str(created_at), str(assigned_by), int(fail_streak), history)

    def get(self, task_id: int) -> Task | None:
        row = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._row_to_task(row) if row else None

    def list_open(self) -> list[Task]:
        rows = self._conn.execute(
            f"SELECT * FROM tasks WHERE status IN ({','.join('?' * len(_OPEN_STATUSES))}) "
            "ORDER BY id",
            _OPEN_STATUSES,
        ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def list_all(self) -> list[Task]:
        rows = self._conn.execute("SELECT * FROM tasks ORDER BY id DESC").fetchall()
        return [self._row_to_task(r) for r in rows]

    def append_history(self, task_id: int, entry: HistoryEntry) -> None:
        task = self.get(task_id)
        if task is None:
            return
        history = [*task.history, entry]
        self._conn.execute(
            "UPDATE tasks SET history_json = ? WHERE id = ?",
            (json.dumps([e.__dict__ for e in history], ensure_ascii=False), task_id),
        )
        self._conn.commit()

    def set_status(self, task_id: int, status: str) -> None:
        self._conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))
        self._conn.commit()

    def set_fail_streak(self, task_id: int, streak: int) -> None:
        self._conn.execute("UPDATE tasks SET fail_streak = ? WHERE id = ?", (streak, task_id))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
