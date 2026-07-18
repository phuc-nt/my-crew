"""History search index (v33 P5) — FTS5 over what the team already produced.

"Tuần trước team quyết gì?" needs SEARCH over past work, then a summary — never a raw
dump (Hermes `session_search` pattern). Sources indexed in v1:

- **step artifacts**: every delivered team-task step's `result_text` (the same
  done + work/rework filter every other surface applies);
- **audit entries**: each agent's gateway audit JSONL — tool + summary + rationale
  (already secret-redacted at write time by `audit_log.record`).

The index is a DISPOSABLE side table (`history_search.sqlite3` at the shared root):
every row can be rebuilt from its source, so schema changes are a delete-and-resweep,
never a migration. Incremental sweep via per-source watermarks; rows are capped
(`_ROW_CHARS`) so the index never stores more than a search needs.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

_ROW_CHARS = 2000
_DB_NAME = "history_search.sqlite3"


def history_search_db_path() -> Path:
    from my_crew.runtime.team_task_paths import team_tasks_root

    return team_tasks_root() / _DB_NAME


class HistorySearchIndex:
    def __init__(self, db_path: Path | None = None) -> None:
        path = db_path or history_search_db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5("
            "  text, source UNINDEXED, ref UNINDEXED, agent_id UNINDEXED, ts UNINDEXED)"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS sweep_meta (source TEXT PRIMARY KEY, watermark TEXT)"
        )
        # Dedup gate (review M4): two processes sweeping concurrently (ticker + a
        # search-triggered sweep) both pass the watermark check for the same new rows;
        # the FTS table has no uniqueness, so inserts are gated by this PK instead.
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS indexed_refs ("
            "  source TEXT NOT NULL, ref TEXT NOT NULL, agent_id TEXT NOT NULL,"
            "  PRIMARY KEY (source, ref, agent_id))"
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # --- sweep -----------------------------------------------------------------

    def sweep(self) -> int:
        """Incremental index pass over all sources. Returns rows added. Best-effort
        per source: one broken source never blocks the others."""
        import time as _time

        started = _time.monotonic()
        added = 0
        for name, fn in (("steps", self._sweep_steps), ("audit", self._sweep_audit)):
            try:
                added += fn()
            except Exception:  # noqa: BLE001 — sweep is hygiene, never fatal
                logger.warning("history sweep source %s failed", name, exc_info=True)
        if added:
            self._conn.commit()
        elapsed = _time.monotonic() - started
        if elapsed > 5.0:
            # The audit source re-parses whole JSONL files each sweep (watermark
            # filters after parse) — this log is the tripwire that says it's time to
            # move to per-file byte offsets (backlog, review M1).
            logger.warning("history sweep chậm: %.1fs (added=%d)", elapsed, added)
        return added

    def _claim(self, source: str, ref: str, agent_id: str) -> bool:
        """True iff (source, ref, agent) was NOT indexed yet — claims it atomically."""
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO indexed_refs (source, ref, agent_id) VALUES (?, ?, ?)",
            (source, ref, agent_id),
        )
        return cur.rowcount == 1

    def _watermark(self, source: str) -> str:
        row = self._conn.execute(
            "SELECT watermark FROM sweep_meta WHERE source = ?", (source,)
        ).fetchone()
        return row[0] if row else ""

    def _set_watermark(self, source: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO sweep_meta (source, watermark) VALUES (?, ?) "
            "ON CONFLICT(source) DO UPDATE SET watermark = excluded.watermark",
            (source, value),
        )

    def _sweep_steps(self) -> int:
        from my_crew.agent.team_task_artifact import read_step_artifact
        from my_crew.runtime.team_task_paths import team_tasks_db_path, team_tasks_root
        from my_crew.runtime.team_task_store import TeamTaskStore

        mark = self._watermark("steps")
        newest = mark
        added = 0
        store = TeamTaskStore(team_tasks_db_path())
        try:
            tasks = store.list_recent_tasks(500)
        finally:
            store.close()
        for t in tasks:
            for s in t.steps:
                if s.status != "done" or s.step_type not in ("work", "rework"):
                    continue
                ts = s.last_seen or s.spawned_at or t.created_at
                if not ts or ts <= mark:
                    continue
                try:
                    artifact = read_step_artifact(team_tasks_root(), t.id, s.seq)
                except Exception:  # noqa: BLE001 — one unreadable artifact: skip
                    continue
                text = str((artifact or {}).get("result_text") or "")
                if not text:
                    continue
                ref = f"{t.id}:{s.seq}"
                if not self._claim("step", ref, s.assigned_to):
                    newest = max(newest, ts)
                    continue
                self._conn.execute(
                    "INSERT INTO search_index (text, source, ref, agent_id, ts) "
                    "VALUES (?, 'step', ?, ?, ?)",
                    (f"{t.title} — {s.title}\n{text}"[:_ROW_CHARS],
                     ref, s.assigned_to, ts),
                )
                added += 1
                newest = max(newest, ts)
        if newest != mark:
            self._set_watermark("steps", newest)
        return added

    def _sweep_audit(self) -> int:
        from my_crew.runtime.agent_paths import agent_data_dir
        from my_crew.runtime.registry import load_registry

        mark = self._watermark("audit")
        newest = mark
        added = 0
        try:
            entries = load_registry()
        except Exception:  # noqa: BLE001 — registry unreadable: skip this source
            return 0
        for entry in entries:
            audit_path = agent_data_dir(entry.id) / "audit" / "audit.jsonl"
            if not audit_path.is_file():
                continue
            try:
                lines = audit_path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = str(row.get("timestamp") or "")
                if not ts or ts <= mark:
                    continue
                text = " · ".join(
                    str(row.get(k) or "") for k in
                    ("tool", "verdict", "reason", "result_summary", "rationale")
                    if row.get(k)
                )
                if not text.strip():
                    continue
                if not self._claim("audit", ts, entry.id):
                    newest = max(newest, ts)
                    continue
                self._conn.execute(
                    "INSERT INTO search_index (text, source, ref, agent_id, ts) "
                    "VALUES (?, 'audit', ?, ?, ?)",
                    (text[:_ROW_CHARS], ts, entry.id, ts),
                )
                added += 1
                newest = max(newest, ts)
        if newest != mark:
            self._set_watermark("audit", newest)
        return added

    # --- query -----------------------------------------------------------------

    def search(self, query: str, *, days: int = 0, agent: str = "",
               limit: int = 8) -> list[dict]:
        """Top matches, newest-first among rank ties. Each hit carries its source ref
        so the caller can cite (task/step or audit ts). The raw query is escaped into
        quoted FTS5 terms — MATCH syntax from the caller is data, not operators."""
        terms = [t.replace('"', '""') for t in str(query).split() if t.strip()]
        if not terms:
            return []
        match = " ".join(f'"{t}"' for t in terms)
        sql = ("SELECT snippet(search_index, 0, '»', '«', '…', 24), source, ref,"
               " agent_id, ts FROM search_index WHERE search_index MATCH ?")
        params: list = [match]
        if agent:
            sql += " AND agent_id = ?"
            params.append(agent)
        if days > 0:
            cutoff = (_dt.datetime.now(_dt.UTC) - _dt.timedelta(days=days)).isoformat()
            sql += " AND ts >= ?"
            params.append(cutoff)
        sql += " ORDER BY rank, ts DESC LIMIT ?"
        params.append(int(limit))
        try:
            rows = self._conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            logger.warning("history search query failed", exc_info=True)
            return []
        return [
            {"excerpt": r[0][:500], "source": r[1], "ref": r[2],
             "agent_id": r[3], "ts": r[4]}
            for r in rows
        ]
