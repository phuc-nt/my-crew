"""Clarification store (v33 P4) — questions an agent asks the CEO, answered from web
or Telegram buttons, delivered into the task's NEXT step context.

Design points that carry weight:
- **first-answer-wins**: `apply_answer` is a conditional UPDATE on `status='pending'`
  — a web click and a Telegram tap racing each other cannot both land.
- **cap per agent** (`MAX_PENDING_PER_AGENT`): a misbehaving agent cannot flood the
  CEO's queue; excess questions are refused at create.
- **expiry**: a question the CEO never answers flips to `expired` after its TTL and
  the asking task simply proceeds on the safe default it already chose — the queue
  can never wedge a task forever.
- `resume_token` is reserved for v34's LangGraph `interrupt()` upgrade (NULL and
  unused in v33) so that upgrade is a column-reuse, not a migration.
"""

from __future__ import annotations

import datetime as _dt
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

MAX_PENDING_PER_AGENT = 3
DEFAULT_TTL_HOURS = 48
MAX_OPTIONS = 4


class ClarifyCapError(RuntimeError):
    """The asking agent already has the max pending questions — refuse, don't queue."""


@dataclass(frozen=True)
class Clarification:
    id: int
    agent_id: str
    task_id: str
    question: str
    options: tuple[str, ...]
    status: str  # pending | answered | expired
    answer: str
    asked_at: str
    answered_at: str | None
    expires_at: str


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC)


class ClarifyStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS clarifications ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  agent_id TEXT NOT NULL,"
            "  task_id TEXT NOT NULL DEFAULT '',"
            "  question TEXT NOT NULL,"
            "  options TEXT NOT NULL DEFAULT '[]',"
            "  status TEXT NOT NULL DEFAULT 'pending',"
            "  answer TEXT NOT NULL DEFAULT '',"
            "  asked_at TEXT NOT NULL,"
            "  answered_at TEXT,"
            "  expires_at TEXT NOT NULL,"
            "  resume_token TEXT"
            ")"
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def create_question(
        self, *, agent_id: str, task_id: str, question: str,
        options: list[str] | None = None, ttl_hours: int = DEFAULT_TTL_HOURS,
    ) -> int:
        pending = self._conn.execute(
            "SELECT COUNT(*) FROM clarifications WHERE agent_id = ? AND status = 'pending'",
            (agent_id,),
        ).fetchone()[0]
        if pending >= MAX_PENDING_PER_AGENT:
            raise ClarifyCapError(
                f"agent {agent_id!r} đã có {pending} câu hỏi chờ CEO — không nhận thêm"
            )
        now = _now()
        cur = self._conn.execute(
            "INSERT INTO clarifications (agent_id, task_id, question, options, asked_at,"
            " expires_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                agent_id, task_id, question,
                json.dumps(list(options or [])[:MAX_OPTIONS], ensure_ascii=False),
                now.isoformat(),
                (now + _dt.timedelta(hours=ttl_hours)).isoformat(),
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def apply_answer(self, clarify_id: int, answer: str) -> bool:
        """First-answer-wins: True iff THIS call flipped pending → answered."""
        cur = self._conn.execute(
            "UPDATE clarifications SET status = 'answered', answer = ?, answered_at = ? "
            "WHERE id = ? AND status = 'pending'",
            (answer, _now().isoformat(), int(clarify_id)),
        )
        self._conn.commit()
        return cur.rowcount == 1

    def expire_due(self) -> int:
        """Flip overdue pending questions to expired. Returns how many flipped."""
        cur = self._conn.execute(
            "UPDATE clarifications SET status = 'expired' "
            "WHERE status = 'pending' AND expires_at < ?",
            (_now().isoformat(),),
        )
        self._conn.commit()
        return cur.rowcount

    def get(self, clarify_id: int) -> Clarification | None:
        row = self._conn.execute(
            "SELECT id, agent_id, task_id, question, options, status, answer, asked_at,"
            " answered_at, expires_at FROM clarifications WHERE id = ?",
            (int(clarify_id),),
        ).fetchone()
        return self._to_row(row) if row else None

    def list_pending(self) -> list[Clarification]:
        rows = self._conn.execute(
            "SELECT id, agent_id, task_id, question, options, status, answer, asked_at,"
            " answered_at, expires_at FROM clarifications WHERE status = 'pending' "
            "ORDER BY asked_at"
        ).fetchall()
        return [self._to_row(r) for r in rows]

    def answered_for_task(self, task_id: str, limit: int = 5) -> list[Clarification]:
        """Recent answered Q&A for a task — what the next step's context includes."""
        rows = self._conn.execute(
            "SELECT id, agent_id, task_id, question, options, status, answer, asked_at,"
            " answered_at, expires_at FROM clarifications "
            "WHERE task_id = ? AND status = 'answered' ORDER BY answered_at DESC LIMIT ?",
            (task_id, int(limit)),
        ).fetchall()
        return [self._to_row(r) for r in rows]

    @staticmethod
    def _to_row(row) -> Clarification:
        try:
            options = tuple(str(o) for o in json.loads(row[4]))
        except (json.JSONDecodeError, TypeError):
            options = ()
        return Clarification(
            id=row[0], agent_id=row[1], task_id=row[2], question=row[3],
            options=options, status=row[5], answer=row[6], asked_at=row[7],
            answered_at=row[8], expires_at=row[9],
        )
