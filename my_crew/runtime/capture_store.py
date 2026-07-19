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

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: Columns the LIST reads (`list_for_task`/`list_recent`) return — deliberately excludes
#: `criteria_json` (v54 P4b) so the fleet/task list views stay lean; the detail read
#: (`get`, below) is the only one that also returns criteria.
_LIST_COLUMNS = (
    "attempt_id", "task_id", "step_id", "agent_id", "engine", "status",
    "step_type", "review_round", "cost_usd", "cost_source",
    "input_tokens", "output_tokens", "started_at", "ended_at", "duration_ms",
    "error", "ts",
)

#: Every column of the captures table, in declared order — used by `get()` (the DETAIL
#: read), which is the one read helper that also surfaces `criteria_json`.
_COLUMNS = (*_LIST_COLUMNS, "criteria_json")


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
        # v54 P4b: per-criterion review detail (JSON dump of the `{criterion, passed, note}`
        # list `team_task_check_prompt`'s rubric produces, computed in `_run_review` and
        # otherwise discarded after being folded into counts for the office event). Same
        # migrate-free ALTER pattern as `approvals.actor` (v46) / `team_steps` columns — a
        # store opened before this column existed gets it added once; the second (and every
        # later) `_create_schema()` call on the same file hits "duplicate column" and is
        # swallowed, so re-opening the store is idempotent.
        try:
            self._conn.execute("ALTER TABLE captures ADD COLUMN criteria_json TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists
        from my_crew.runtime.store_schema_meta import ensure_schema_meta

        ensure_schema_meta(self._conn)
        self._conn.commit()

    def delete_older_than(self, cutoff_iso: str) -> int:
        """Delete telemetry rows written before `cutoff_iso` (ISO-8601). Returns the row
        count removed. Keyed on `ts` (row-write time, always set) so no NULL edge case."""
        cur = self._conn.execute("DELETE FROM captures WHERE ts < ?", (cutoff_iso,))
        self._conn.commit()
        return cur.rowcount

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
        criteria: list[dict[str, Any]] | None = None,
    ) -> None:
        """Upsert one attempt's telemetry row (idempotent on `attempt_id`).

        `criteria` (v54 P4b): the review step's per-criterion list (`{criterion, passed,
        note}`, from `team_task_check_prompt`'s rubric via `review_graph.run_review_step`)
        — JSON-dumped verbatim, or NULL when absent (every non-review attempt, and any
        review attempt that produced no criteria). Never touched by non-review callers.
        """
        criteria_json = json.dumps(criteria, ensure_ascii=False) if criteria else None
        self._conn.execute(
            "INSERT OR REPLACE INTO captures ("
            "  attempt_id, task_id, step_id, agent_id, engine, status,"
            "  step_type, review_round, cost_usd, cost_source,"
            "  input_tokens, output_tokens, started_at, ended_at, duration_ms, error, ts,"
            "  criteria_json"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                attempt_id, task_id, step_id, agent_id, engine, status,
                step_type, review_round, cost_usd, cost_source,
                input_tokens, output_tokens, started_at, ended_at, duration_ms,
                error, datetime.now(UTC).isoformat(), criteria_json,
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
        """Return all rows for a task, oldest-first by write time (read helper for tests/UAT).

        Lean column set (no `criteria_json` — see `get()` for the detail read)."""
        cur = self._conn.execute(
            f"SELECT {', '.join(_LIST_COLUMNS)} FROM captures WHERE task_id = ? ORDER BY ts",
            (task_id,),
        )
        return [dict(zip(_LIST_COLUMNS, row, strict=True)) for row in cur.fetchall()]

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

        Lean column set (no `criteria_json` — see `get()` for the detail read)."""
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
            f"SELECT {', '.join(_LIST_COLUMNS)} FROM captures{where} ORDER BY ts DESC LIMIT ?",
            (*params, clamp),
        )
        return [dict(zip(_LIST_COLUMNS, row, strict=True)) for row in cur.fetchall()]

    def close(self) -> None:
        self._conn.close()
