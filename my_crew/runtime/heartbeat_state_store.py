"""Per-agent heartbeat state (v68) — the three things a pulse must remember between runs.

A tiny SQLite file (`<agent_data_dir>/heartbeat.db`, WAL like every other store) holding:

1. `reported` — one row per problem the CEO has already been told about. Per-ITEM, not
   per-snapshot: an unchanged problem stays quiet, a genuinely new one always speaks, and
   a problem that resolves is pruned so its recurrence counts as new again.
2. `failures` — how many heartbeat runs failed BACK TO BACK. Three in a row disables the
   pulse: a proactive channel that is broken should go quiet and say so once, not keep
   failing on a timer forever. Any successful pulse resets the count to zero.
3. `scratch` — things the CEO asked the secretary to keep an eye on ("để ý giùm X"). The
   system has no real signal for these, so it does not pretend to: each one is simply
   echoed back on a slow cadence as a reminder of what the CEO themselves asked for.

Deliberately ONE store rather than three loose files. The heartbeat's original
`heartbeat_state.txt` is migrated in on first open and deleted, so no live problem is
re-announced as a side effect of the upgrade.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_DB_NAME = "heartbeat.db"

#: Three failing runs back-to-back is a broken heartbeat, not bad luck. Chosen to match
#: the escalation contract: report once, then stop rather than fail on a timer forever.
MAX_CONSECUTIVE_FAILURES = 3

#: How long a scratch item stays quiet after being echoed. The CEO asked to be reminded,
#: not nagged — at `every: 30m` a shorter window would repeat the same line 48x a day.
SCRATCH_REMIND_HOURS = 24


def heartbeat_db_path(data_dir: Path) -> Path:
    return Path(data_dir) / _DB_NAME


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class HeartbeatStateStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._path = Path(db_path)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=3000")
        self._conn.executescript(
            "CREATE TABLE IF NOT EXISTS reported ("
            "  item_key TEXT PRIMARY KEY,"
            "  reported_at TEXT NOT NULL"
            ");"
            # Single-row table: `id` is pinned to 1 so an UPSERT can never fan out.
            "CREATE TABLE IF NOT EXISTS health ("
            "  id INTEGER PRIMARY KEY CHECK (id = 1),"
            "  consecutive_failures INTEGER NOT NULL DEFAULT 0,"
            "  disabled_at TEXT,"
            "  disabled_reason TEXT"
            ");"
            "CREATE TABLE IF NOT EXISTS scratch ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  text TEXT NOT NULL,"
            "  created_at TEXT NOT NULL,"
            "  last_echoed_at TEXT"
            ");"
        )
        self._conn.execute("INSERT OR IGNORE INTO health (id) VALUES (1)")
        self._conn.commit()
        self._migrate_legacy_state()

    # --- reported problems -------------------------------------------------------------

    def load_reported(self) -> set[str]:
        rows = self._conn.execute("SELECT item_key FROM reported").fetchall()
        return {str(k) for (k,) in rows}

    def save_reported(self, keys: set[str]) -> None:
        """Replace the whole set. Callers pass only what is still live, so a resolved
        problem drops out and can speak up again if it ever returns."""
        now = _now_iso()
        with self._conn:
            self._conn.execute("DELETE FROM reported")
            self._conn.executemany(
                "INSERT INTO reported (item_key, reported_at) VALUES (?, ?)",
                [(k, now) for k in sorted(keys)],
            )

    # --- failure counter ---------------------------------------------------------------

    def record_success(self) -> None:
        """Any pulse that completes resets the streak — the contract counts CONSECUTIVE
        failures, so one good run means the heartbeat is working again."""
        with self._conn:
            self._conn.execute("UPDATE health SET consecutive_failures = 0 WHERE id = 1")

    def record_failure(self) -> int:
        """Count one failed run and return the new streak length."""
        with self._conn:
            self._conn.execute(
                "UPDATE health SET consecutive_failures = consecutive_failures + 1 "
                "WHERE id = 1"
            )
        return self.consecutive_failures()

    def consecutive_failures(self) -> int:
        row = self._conn.execute(
            "SELECT consecutive_failures FROM health WHERE id = 1"
        ).fetchone()
        return int(row[0]) if row else 0

    # --- self-disable ------------------------------------------------------------------

    def disable(self, reason: str) -> None:
        """Turn the pulse off. Recorded in the store rather than the CEO's profile.yaml:
        a yaml round-trip destroys their comments, and this must be reversible from chat."""
        with self._conn:
            self._conn.execute(
                "UPDATE health SET disabled_at = ?, disabled_reason = ? WHERE id = 1",
                (_now_iso(), reason),
            )

    def enable(self) -> None:
        """Clear the disable AND the streak — otherwise the next single failure would
        immediately re-trip the counter that is already sitting at the limit."""
        with self._conn:
            self._conn.execute(
                "UPDATE health SET disabled_at = NULL, disabled_reason = NULL, "
                "consecutive_failures = 0 WHERE id = 1"
            )

    def disabled_reason(self) -> str | None:
        row = self._conn.execute(
            "SELECT disabled_at, disabled_reason FROM health WHERE id = 1"
        ).fetchone()
        if not row or row[0] is None:
            return None
        return str(row[1] or "không rõ lý do")

    def is_disabled(self) -> bool:
        return self.disabled_reason() is not None

    # --- scratch checklist -------------------------------------------------------------

    def add_scratch(self, text: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO scratch (text, created_at) VALUES (?, ?)", (text, _now_iso()),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def list_scratch(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, text, last_echoed_at FROM scratch ORDER BY id"
        ).fetchall()
        return [{"id": int(i), "text": str(t), "last_echoed_at": e} for i, t, e in rows]

    def remove_scratch(self, item_id: int) -> bool:
        with self._conn:
            cur = self._conn.execute("DELETE FROM scratch WHERE id = ?", (item_id,))
        return cur.rowcount > 0

    def due_scratch(self, *, now: datetime) -> list[dict]:
        """Scratch items not echoed within `SCRATCH_REMIND_HOURS`. Never-echoed items are
        due immediately, so a fresh "để ý giùm X" reaches the CEO on the next pulse."""
        out = []
        for item in self.list_scratch():
            last = item["last_echoed_at"]
            if last is None:
                out.append(item)
                continue
            try:
                when = datetime.fromisoformat(str(last))
            except ValueError:
                out.append(item)  # unparsable ⇒ treat as never echoed
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            if (now - when).total_seconds() >= SCRATCH_REMIND_HOURS * 3600:
                out.append(item)
        return out

    def mark_scratch_echoed(self, ids: list[int], *, now: datetime) -> None:
        with self._conn:
            self._conn.executemany(
                "UPDATE scratch SET last_echoed_at = ? WHERE id = ?",
                [(now.isoformat(), i) for i in ids],
            )

    # --- lifecycle ---------------------------------------------------------------------

    def _migrate_legacy_state(self) -> None:
        """Carry over the pre-store `heartbeat_state.txt` (one item key per line).

        Without this, upgrading would look like "every problem resolved at once" and the
        very next pulse would re-announce all of them. Best-effort: a failed migration
        costs one duplicate report, never a broken pulse.
        """
        legacy = self._path.parent / "heartbeat_state.txt"
        if not legacy.exists():
            return
        try:
            keys = {ln.strip() for ln in legacy.read_text(encoding="utf-8").splitlines()}
            keys.discard("")
            if keys and not self.load_reported():
                self.save_reported(keys)
            legacy.unlink()
        except OSError:
            logger.warning("heartbeat: could not migrate legacy state at %s", legacy)

    def close(self) -> None:
        self._conn.close()


def heartbeat_disabled(data_dir: Path) -> bool:
    """Cheap probe for `service._effective_schedule` — no file ⇒ False without creating
    the DB, so an agent that never tripped a failure keeps a byte-identical schedule."""
    path = heartbeat_db_path(data_dir)
    if not path.exists():
        return False
    store = HeartbeatStateStore(path)
    try:
        return store.is_disabled()
    finally:
        store.close()
