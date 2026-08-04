"""Per-agent one-shot reminder store (v65) — "3h nhắc anh gọi X".

A tiny SQLite file (`<agent_data_dir>/reminders.db`, WAL like every other store): one
row per reminder, `pending → sent | cancelled`. Writes arrive ONLY through the Action
Gateway (`actions/reminder_write.py` — native types `reminder_create`/`reminder_cancel`),
delivery happens in `runtime/reminder_sweep.py` (a per-minute pseudo-kind synthesized
ONLY while the agent has pending rows — see `service._effective_schedule`), so an agent
with no reminders keeps a byte-identical schedule and zero extra load.

Core-generic on purpose: "deliver message X at time T over the agent's own Telegram"
carries no domain logic — the personal pack owns the CHAT COMMANDS that create rows,
not the machinery.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

_DB_NAME = "reminders.db"


def reminders_db_path(data_dir: Path) -> Path:
    return Path(data_dir) / _DB_NAME


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class ReminderStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=3000")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS reminders ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  chat_id TEXT NOT NULL,"
            "  text TEXT NOT NULL,"
            "  due_at TEXT NOT NULL,"        # RFC3339 WITH offset — compared in UTC
            "  status TEXT NOT NULL DEFAULT 'pending',"
            "  created_at TEXT NOT NULL"
            ")"
        )
        self._conn.commit()

    def add(self, *, chat_id: str, text: str, due_at: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO reminders (chat_id, text, due_at, created_at) VALUES (?, ?, ?, ?)",
            (chat_id, text, due_at, _now_iso()),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def list_pending(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, chat_id, text, due_at FROM reminders WHERE status = 'pending' "
            "ORDER BY due_at"
        ).fetchall()
        return [
            {"id": r[0], "chat_id": r[1], "text": r[2], "due_at": r[3]} for r in rows
        ]

    def due(self, *, now: datetime | None = None) -> list[dict]:
        """Pending rows whose `due_at` has passed. Comparison happens in Python over
        parsed datetimes (NOT string compare — mixed offsets, e.g. +07:00 vs Z, do not
        sort lexicographically). An unparsable `due_at` can't slip in through the
        gateway (shape-checked) but is skipped defensively anyway."""
        now = now or datetime.now(UTC)
        out = []
        for row in self.list_pending():
            try:
                due = datetime.fromisoformat(row["due_at"])
            except ValueError:
                continue
            if due.tzinfo is None:
                due = due.replace(tzinfo=UTC)
            if due <= now:
                out.append(row)
        return out

    def mark_sent(self, reminder_id: int) -> bool:
        cur = self._conn.execute(
            "UPDATE reminders SET status = 'sent' WHERE id = ? AND status = 'pending'",
            (reminder_id,),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def cancel(self, reminder_id: int) -> bool:
        cur = self._conn.execute(
            "UPDATE reminders SET status = 'cancelled' WHERE id = ? AND status = 'pending'",
            (reminder_id,),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def has_pending(self) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM reminders WHERE status = 'pending' LIMIT 1"
        ).fetchone()
        return row is not None

    def close(self) -> None:
        self._conn.close()


def has_pending_reminders(data_dir: Path) -> bool:
    """Cheap existence probe for `service._effective_schedule` — no file ⇒ False
    without even creating the DB (an agent that never set a reminder must not grow
    an empty store as a side effect of every schedule computation)."""
    path = reminders_db_path(data_dir)
    if not path.exists():
        return False
    store = ReminderStore(path)
    try:
        return store.has_pending()
    finally:
        store.close()
