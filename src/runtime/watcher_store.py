"""Watcher state store — last seen hash per watched source (v31 P5, wake-gate).

One row per `<agent_id>:<watcher.id>`. The load-bearing design point is the SPLIT
between `record_check` and `advance_hash`:

- `record_check` runs on EVERY poll: it updates `last_checked_at`/`fail_count`
  bookkeeping (so stale/backoff accounting is correct) and answers "is this hash new
  vs the committed one?" — but it NEVER commits the new hash itself.
- `advance_hash` commits the new hash and is called ONLY AFTER the wake succeeded.

That split is the lost-wake fix: a wake that fails (spawn error, store hiccup) leaves
the old hash in place, so the same diff is still "new" on the next tick and re-fires.
No `wake_pending` flag exists to get stuck.

A separate DB file (`watcher.db`) under the agent's data dir — NOT the DedupStore
(whose `claim()` is one-shot idempotency, not get/set state). Same WAL + busy_timeout
posture as the capture store; in practice only the agent's own watch worker touches it.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


class WatcherStore:
    """SQLite-backed per-watcher poll state (hash / checked-at / fail count)."""

    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False, timeout=30.0)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS watcher_state ("
            "  watcher_id TEXT PRIMARY KEY,"
            "  source_kind TEXT NOT NULL,"
            "  last_hash TEXT,"
            "  last_checked_at TEXT,"
            "  last_advanced_at TEXT,"
            "  fail_count INTEGER DEFAULT 0,"
            "  last_error TEXT,"
            "  ts TEXT NOT NULL"
            ")"
        )
        # A db created before the staleness stamp existed lacks the column; add it in
        # place (same in-place ALTER posture as the team-task store's pic_id column).
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(watcher_state)")]
        if "last_advanced_at" not in cols:
            self._conn.execute(
                "ALTER TABLE watcher_state ADD COLUMN last_advanced_at TEXT"
            )
        self._conn.commit()

    def _now(self) -> str:
        return datetime.now(UTC).isoformat()

    def record_check(
        self, watcher_id: str, source_kind: str, current_hash: str | None,
        error: str | None = None,
    ) -> tuple[bool, str | None]:
        """Record one poll outcome. Returns `(is_new, old_hash)`.

        Poll FAILURE (`current_hash is None`): increments `fail_count`, stores the
        error, touches NOTHING else (hash + last_checked_at keep their values, so a
        failing source correctly drifts toward stale) → `(False, None)`.

        Poll SUCCESS: resets `fail_count`, updates `last_checked_at`, and compares
        `current_hash` against the COMMITTED hash. `is_new` is True when they differ
        (including the very first poll). The hash itself is NOT advanced here.
        """
        state = self.get_state(watcher_id)
        now = self._now()
        if current_hash is None:
            fails = (state["fail_count"] if state else 0) + 1
            self._conn.execute(
                "INSERT INTO watcher_state "
                "(watcher_id, source_kind, last_hash, last_checked_at, fail_count,"
                " last_error, ts) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(watcher_id) DO UPDATE SET "
                "fail_count = ?, last_error = ?, ts = ?",
                (watcher_id, source_kind, None, None, fails, error, now,
                 fails, error, now),
            )
            self._conn.commit()
            return False, None
        old = state["last_hash"] if state else None
        self._conn.execute(
            "INSERT INTO watcher_state "
            "(watcher_id, source_kind, last_hash, last_checked_at, fail_count,"
            " last_error, ts) VALUES (?, ?, NULL, ?, 0, NULL, ?) "
            "ON CONFLICT(watcher_id) DO UPDATE SET "
            "last_checked_at = ?, fail_count = 0, last_error = NULL, ts = ?",
            (watcher_id, source_kind, now, now, now, now),
        )
        self._conn.commit()
        return current_hash != old, old

    def advance_hash(self, watcher_id: str, new_hash: str) -> None:
        """Commit the new hash — call ONLY after the wake succeeded (lost-wake fix).

        Also stamps `last_advanced_at`: staleness ("the source hasn't CHANGED in
        >24h") is measured from the last committed change, never from
        `last_checked_at` (which every successful poll refreshes — comparing against
        it could never exceed the threshold).
        """
        now = self._now()
        self._conn.execute(
            "UPDATE watcher_state SET last_hash = ?, last_advanced_at = ?, ts = ? "
            "WHERE watcher_id = ?",
            (new_hash, now, now, watcher_id),
        )
        self._conn.commit()

    def get_state(self, watcher_id: str) -> dict[str, Any] | None:
        cur = self._conn.execute(
            "SELECT watcher_id, source_kind, last_hash, last_checked_at,"
            " last_advanced_at, fail_count, last_error, ts"
            " FROM watcher_state WHERE watcher_id = ?",
            (watcher_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        keys = ("watcher_id", "source_kind", "last_hash", "last_checked_at",
                "last_advanced_at", "fail_count", "last_error", "ts")
        return dict(zip(keys, row, strict=True))

    def is_stale(self, watcher_id: str, *, max_age_hours: float = 24.0,
                 now: datetime | None = None) -> bool:
        """True when the source hasn't produced a committed CHANGE in `max_age_hours`.

        Measured from `last_advanced_at` (set by `advance_hash` after a successful
        wake). A watcher that has never advanced is not "stale" — the first-poll
        baseline wake sets the stamp immediately in practice, and pure poll failures
        are the backoff/alert path's job, not staleness's.
        """
        state = self.get_state(watcher_id)
        if state is None or not state["last_advanced_at"]:
            return False
        advanced = datetime.fromisoformat(state["last_advanced_at"])
        ref = now or datetime.now(UTC)
        return ref - advanced > timedelta(hours=max_age_hours)

    def close(self) -> None:
        self._conn.close()
