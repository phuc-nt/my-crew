"""Persistent idempotency store (PDR §7.6).

The Action Gateway must not re-execute an action it already ran — even across
process restarts (a daily cron re-run must not double-post). Phase 0 kept seen
keys in an in-memory set, which re-armed on restart; this backs them with SQLite
under the data dir so dedup survives restarts.

Single-user / local: a SQLite file with a UNIQUE key column is enough. The
INSERT-OR-IGNORE pattern makes "claim this key" atomic.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path


class DedupStore:
    """SQLite-backed set of already-executed action keys."""

    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS seen_keys ("
            "  key TEXT PRIMARY KEY,"
            "  created_at TEXT NOT NULL"
            ")"
        )
        self._conn.commit()

    def seen(self, key: str) -> bool:
        """True if the key was already recorded."""
        cur = self._conn.execute("SELECT 1 FROM seen_keys WHERE key = ?", (key,))
        return cur.fetchone() is not None

    def claim(self, key: str) -> bool:
        """Atomically reserve the key. Returns True if newly claimed, False if it
        already existed (i.e. this is a duplicate). Reserve before executing to
        close the concurrent double-execute window; `release()` on failure."""
        now = datetime.now(UTC).isoformat()
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO seen_keys (key, created_at) VALUES (?, ?)", (key, now)
        )
        self._conn.commit()
        return cur.rowcount == 1

    def release(self, key: str) -> None:
        """Undo a reservation (e.g. when the action did not actually run)."""
        self._conn.execute("DELETE FROM seen_keys WHERE key = ?", (key,))
        self._conn.commit()

    def delete_older_than(self, cutoff_iso: str) -> int:
        """Purge idempotency keys older than `cutoff_iso`. Returns rows removed. The key
        only needs to outlive the re-execution window it guards (a daily cron re-run); a
        short retention keeps the per-agent store from growing without bound. No schema_meta
        here — this is a per-agent store the project does not centrally version."""
        cur = self._conn.execute("DELETE FROM seen_keys WHERE created_at < ?", (cutoff_iso,))
        self._conn.commit()
        return cur.rowcount

    def close(self) -> None:
        self._conn.close()
