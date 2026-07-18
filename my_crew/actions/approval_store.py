"""Pending-approval queue for Lớp B actions (PDR §7.9, §5.2).

Reversible-but-sensitive actions (close/merge PR, close/reassign issue, message
external stakeholders) are not auto-executed even when autonomous — the gateway
queues them here and a human approves later via the CLI. Stored in SQLite under
the data dir so the queue survives restarts (a cron-queued action can be approved
the next day).

Status flow: pending -> approved (then executed) | rejected.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PendingApproval:
    id: int
    action: dict[str, Any]
    reason: str
    status: str  # pending | approved | rejected
    created_at: str
    actor: str = ""  # v46: the agent (profile_id) that queued this approval; "" for pre-v46 rows


class ApprovalStore:
    """SQLite-backed queue of Lớp B actions awaiting human approval."""

    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS approvals ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  action_json TEXT NOT NULL,"
            "  reason TEXT NOT NULL,"
            "  status TEXT NOT NULL DEFAULT 'pending',"
            "  rationale TEXT DEFAULT '',"
            "  created_at TEXT NOT NULL"
            ")"
        )
        # v46: attribute each queued approval to the agent that raised it. Migrate-free ALTER (house
        # pattern) — an existing db gets the column once with DEFAULT '' for old rows.
        try:
            self._conn.execute("ALTER TABLE approvals ADD COLUMN actor TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            pass  # column already exists
        self._conn.commit()

    def enqueue(
        self, action: dict[str, Any], *, reason: str, rationale: str = "", actor: str = ""
    ) -> int:
        """Add a pending approval; returns its id.

        The action is redacted before storage (same posture as the audit log) so
        a secret the Lớp A check missed does not sit unredacted in this parallel
        store. Lớp A blocks detectable secrets before they ever reach here.

        `actor` (v46): the agent that raised this action (its profile_id); recorded so a dashboard
        can attribute a queued approval. Default "" ⇒ unattributed (byte-identical to pre-v46).
        """
        from my_crew.actions.secret_patterns import redact

        now = datetime.now(UTC).isoformat()
        safe_action = redact(action)
        cur = self._conn.execute(
            "INSERT INTO approvals (action_json, reason, status, rationale, created_at, actor) "
            "VALUES (?, ?, 'pending', ?, ?, ?)",
            (json.dumps(safe_action, ensure_ascii=False, default=str), reason, rationale, now,
             actor),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def get(self, approval_id: int) -> PendingApproval | None:
        row = self._conn.execute(
            "SELECT id, action_json, reason, status, created_at, actor FROM approvals WHERE id = ?",
            (approval_id,),
        ).fetchone()
        if row is None:
            return None
        return PendingApproval(
            id=row[0], action=json.loads(row[1]), reason=row[2], status=row[3], created_at=row[4],
            actor=row[5] or "",
        )

    def list_pending(self) -> list[PendingApproval]:
        rows = self._conn.execute(
            "SELECT id, action_json, reason, status, created_at, actor FROM approvals "
            "WHERE status = 'pending' ORDER BY id"
        ).fetchall()
        return [
            PendingApproval(
                id=r[0], action=json.loads(r[1]), reason=r[2], status=r[3], created_at=r[4],
                actor=r[5] or "",
            )
            for r in rows
        ]

    def set_status(self, approval_id: int, status: str) -> None:
        self._conn.execute(
            "UPDATE approvals SET status = ? WHERE id = ?", (status, approval_id)
        )
        self._conn.commit()

    def transition_if_pending(self, approval_id: int, new_status: str) -> bool:
        """Atomically move pending -> new_status. Returns True only if THIS call
        won the transition (compare-and-set), so two concurrent approves of the
        same id can't both proceed."""
        cur = self._conn.execute(
            "UPDATE approvals SET status = ? WHERE id = ? AND status = 'pending'",
            (new_status, approval_id),
        )
        self._conn.commit()
        return cur.rowcount == 1

    def close(self) -> None:
        self._conn.close()
