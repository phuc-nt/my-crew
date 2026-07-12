"""SQLite store for per-attempt team-step telemetry (the "capture" layer).

One row per step-ATTEMPT (`attempt_id` is the primary key — `reserve_step` mints a fresh
one for every spawn, including review/rework rows, so each attempt is captured distinctly).
A row records who ran what on which engine, how it ended, its cost + token counts + cost
provenance, and wall-clock timing.

This is INTERNAL state — like the team-task store and the memory node, it never routes
through the Action Gateway (which governs EXTERNAL mutations only). It is a SEPARATE DB file
from the team-task store so telemetry stays decoupled from task/step state, but it uses the
same multi-writer access pattern (WAL + busy_timeout) because the ticker's spawned workers
write to it concurrently.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: Every column of the captures table, in declared order (used by read helpers to build dicts).
_COLUMNS = (
    "attempt_id", "task_id", "step_id", "agent_id", "engine", "status",
    "step_type", "review_round", "cost_usd", "cost_source",
    "input_tokens", "output_tokens", "started_at", "ended_at", "duration_ms",
    "error", "ts",
)


class CaptureStore:
    """Multi-writer SQLite store; one row per step-attempt keyed by `attempt_id`."""

    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Same relaxed thread check + WAL + widened busy_timeout as the team-task store: the
        # ticker plus each spawned worker open a connection to this same file concurrently.
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False, timeout=30.0)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._create_schema()

    def _create_schema(self) -> None:
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS captures ("
            "  attempt_id TEXT PRIMARY KEY,"
            "  task_id TEXT NOT NULL,"
            "  step_id TEXT NOT NULL,"
            "  agent_id TEXT NOT NULL DEFAULT '',"
            "  engine TEXT NOT NULL DEFAULT 'native',"
            "  status TEXT NOT NULL,"
            "  step_type TEXT NOT NULL DEFAULT 'work',"
            "  review_round INTEGER NOT NULL DEFAULT 0,"
            "  cost_usd REAL,"
            "  cost_source TEXT,"
            "  input_tokens INTEGER,"
            "  output_tokens INTEGER,"
            "  started_at TEXT,"
            "  ended_at TEXT,"
            "  duration_ms INTEGER,"
            "  error TEXT,"
            "  ts TEXT NOT NULL"
            ")"
        )
        self._conn.commit()

    def record(
        self,
        *,
        attempt_id: str,
        task_id: str,
        step_id: str,
        agent_id: str,
        engine: str,
        status: str,
        step_type: str = "work",
        review_round: int = 0,
        cost_usd: float | None = None,
        cost_source: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        started_at: str | None = None,
        ended_at: str | None = None,
        duration_ms: int | None = None,
        error: str | None = None,
    ) -> None:
        """Upsert one attempt's telemetry row (idempotent on `attempt_id`)."""
        self._conn.execute(
            "INSERT OR REPLACE INTO captures ("
            "  attempt_id, task_id, step_id, agent_id, engine, status,"
            "  step_type, review_round, cost_usd, cost_source,"
            "  input_tokens, output_tokens, started_at, ended_at, duration_ms, error, ts"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                attempt_id, task_id, step_id, agent_id, engine, status,
                step_type, review_round, cost_usd, cost_source,
                input_tokens, output_tokens, started_at, ended_at, duration_ms,
                error, datetime.now(UTC).isoformat(),
            ),
        )
        self._conn.commit()

    def get(self, attempt_id: str) -> dict[str, Any] | None:
        """Return the row for `attempt_id` as a dict, or None if absent (read helper)."""
        cur = self._conn.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM captures WHERE attempt_id = ?", (attempt_id,)
        )
        row = cur.fetchone()
        return dict(zip(_COLUMNS, row, strict=True)) if row else None

    def list_for_task(self, task_id: str) -> list[dict[str, Any]]:
        """Return all rows for a task, oldest-first by write time (read helper for tests/UAT)."""
        cur = self._conn.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM captures WHERE task_id = ? ORDER BY ts", (task_id,)
        )
        return [dict(zip(_COLUMNS, row, strict=True)) for row in cur.fetchall()]

    def list_recent(
        self,
        *,
        limit: int = 100,
        since: str | None = None,
        agent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Newest-first rows across all tasks, bounded — the fleet-activity read helper.

        `since` compares against the row's write time `ts` (ISO prefix, same convention
        as AuditLog.query). The clamp mirrors the run-event read bound so a fleet view
        can never pull an unbounded history in one call.
        """
        clauses: list[str] = []
        params: list[Any] = []
        if since:
            clauses.append("ts >= ?")
            params.append(since)
        if agent_id:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        clamp = max(1, min(int(limit), 500))
        cur = self._conn.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM captures{where} ORDER BY ts DESC LIMIT ?",
            (*params, clamp),
        )
        return [dict(zip(_COLUMNS, row, strict=True)) for row in cur.fetchall()]

    def close(self) -> None:
        self._conn.close()
