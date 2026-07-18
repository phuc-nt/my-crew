"""Multi-turn conversation state for CEO chat-ops (v6 M14). SQLite-backed.

Unlike M12 chat-command (single-turn: one mention → one queued action), ops chat is a
DIALOGUE: the CEO says "tạo agent HR", the bot asks for the missing project key, the CEO
answers over several turns, then the bot shows a preview and waits for an explicit
"xác nhận". That needs state that survives between messages (the poller is stateless and
each mention is a fresh worker process), so it lives in SQLite under the agent's data dir
— same posture as ApprovalStore.

One row per (conversation_key) — the conversation_key is the operator's chat id, so a
person has exactly one live ops dialogue at a time (a new command replaces the old draft;
ops actions are short, no need to juggle parallel drafts). Rows carry a `updated_at` so a
stale draft (TTL) is ignored and overwritten rather than resumed days later.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

#: A draft older than this (seconds) is treated as absent — the CEO's "xác nhận" three
#: hours after the preview must not fire a config write they've forgotten the details of.
DRAFT_TTL_S = 1800


@dataclass(frozen=True)
class OpsDraft:
    """An in-flight ops command: which command, slots filled so far, and phase."""

    command_id: str
    slots: dict[str, str]
    phase: str  # "collecting" | "awaiting_confirm"
    updated_at: float


class OpsConversationStore:
    """SQLite store of one live ops draft per conversation key (operator chat id)."""

    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS ops_drafts ("
            "  conversation_key TEXT PRIMARY KEY,"
            "  command_id TEXT NOT NULL,"
            "  slots_json TEXT NOT NULL,"
            "  phase TEXT NOT NULL,"
            "  updated_at REAL NOT NULL"
            ")"
        )
        self._conn.commit()

    def load(self, key: str, *, now: float) -> OpsDraft | None:
        """The live draft for this key, or None when absent or older than the TTL."""
        row = self._conn.execute(
            "SELECT command_id, slots_json, phase, updated_at FROM ops_drafts "
            "WHERE conversation_key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        command_id, slots_json, phase, updated_at = row
        if now - float(updated_at) > DRAFT_TTL_S:
            self.clear(key)  # expired: drop it so a fresh command starts clean
            return None
        try:
            slots = json.loads(slots_json)
        except (json.JSONDecodeError, TypeError):
            slots = {}
        return OpsDraft(str(command_id), dict(slots), str(phase), float(updated_at))

    def save(self, key: str, draft: OpsDraft) -> None:
        """Upsert the draft for this key (one live draft per operator)."""
        self._conn.execute(
            "INSERT INTO ops_drafts (conversation_key, command_id, slots_json, phase, "
            "  updated_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(conversation_key) DO UPDATE SET "
            "  command_id=excluded.command_id, slots_json=excluded.slots_json, "
            "  phase=excluded.phase, updated_at=excluded.updated_at",
            (key, draft.command_id, json.dumps(draft.slots, ensure_ascii=False),
             draft.phase, draft.updated_at),
        )
        self._conn.commit()

    def clear(self, key: str) -> None:
        """Drop the draft (command done, cancelled, or expired)."""
        self._conn.execute("DELETE FROM ops_drafts WHERE conversation_key = ?", (key,))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
