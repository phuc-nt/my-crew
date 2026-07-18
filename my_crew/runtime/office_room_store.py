"""Group-chat room store — the SINGLE SOURCE OF TRUTH for the office timeline (v12 M29).

Cross-agent SQLite at `data_dir` ROOT (mirrors `team_task_paths.py`'s pattern — a team
task/the office spans multiple agents, so its shared state cannot live inside one
agent's isolated `.data/agents/<id>/`). **No in-proc event bus**: the coordinator ticker,
each spawned `team-step` worker, and the admin ops agent are all SEPARATE OS processes,
so an in-proc asyncio bus in the web server's event loop would never see their writes —
this store (SQLite **WAL + busy_timeout**, `check_same_thread=False`) is the only
cross-process channel, exactly like `team_task_store.py`.

One row per event: `seq` (AUTOINCREMENT) is the monotonic total-order key — `ts` alone is
not enough for `since_seq` resume/dedup (two events in the same millisecond, clock skew
across processes). Rooms: one room per team task (`room_id = task_id`) plus one "office"
room that receives ONLY `milestone`-kind events (the CEO-facing overview room).

PII firewall AT WRITE TIME: `append` runs every event body through
`office_event_projection.summarize_office_event` BEFORE it is persisted — so the store
never holds an unprojected field and replaying old rows (a client opening the room late)
is exactly as safe as the live stream. `kind` must be one of `office_event_projection
.VALID_KINDS`; an unknown kind is rejected (ValueError) rather than silently stored with
an empty projected body, so a caller's typo is loud in tests/dev, not a silent data-loss.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from my_crew.server.office_event_projection import VALID_KINDS, summarize_office_event

__all__ = ["OfficeMessage", "OfficeRoomStore", "OFFICE_ROOM_ID", "office_room_db_path"]

#: The one "office tổng" room every milestone event also lands in, regardless of which
#: per-task room it originated from (see `append`'s `also_office` param).
OFFICE_ROOM_ID = "office"


def office_room_db_path(data_dir: Path) -> Path:
    """`<data_dir>/office_room.sqlite3` — the one shared office-room store file."""
    return data_dir / "office_room.sqlite3"


@dataclass(frozen=True)
class OfficeMessage:
    seq: int
    room_id: str
    ts: str
    author: str
    kind: str
    body: dict


class OfficeRoomStore:
    """SQLite-backed cross-agent store for the group-chat room timeline.

    `check_same_thread=False` + WAL + `busy_timeout`: multiple OS processes (ticker,
    step workers, admin ops agent) each open their own connection to the SAME file and
    may write concurrently — see `team_task_store.TeamTaskStore`'s identical rationale.
    """

    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False, timeout=30.0)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._create_schema()

    def _create_schema(self) -> None:
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS messages ("
            "  seq INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  room_id TEXT NOT NULL,"
            "  ts TEXT NOT NULL,"
            "  author TEXT NOT NULL,"
            "  kind TEXT NOT NULL,"
            "  body_json TEXT NOT NULL"
            ")"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_room_seq ON messages (room_id, seq)"
        )
        from my_crew.runtime.store_schema_meta import ensure_schema_meta

        ensure_schema_meta(self._conn)
        self._conn.commit()

    def delete_older_than(self, cutoff_iso: str) -> int:
        """Delete room events older than `cutoff_iso`. Returns rows removed. Safe for the
        feed: readers use `list(room_id, since_seq)` with `seq > since_seq` — an advancing
        cursor, so removing low-seq rows only shifts where a fresh replay starts (the FE
        dedups by seq and never assumes a contiguous-from-zero sequence)."""
        cur = self._conn.execute("DELETE FROM messages WHERE ts < ?", (cutoff_iso,))
        self._conn.commit()
        return cur.rowcount

    def _now(self) -> str:
        return datetime.now(UTC).isoformat()

    def append(
        self, room_id: str, *, author: str, kind: str, body: dict, also_office: bool = False,
    ) -> int:
        """Append one event, PII-projected at write time. Returns the new row's `seq`.

        `kind` must be in `office_event_projection.VALID_KINDS` (fail loud on a typo'd
        kind — see module docstring). When `also_office=True` (the coordinator's
        milestone events), the SAME projected body is ALSO appended to the `office`
        overview room under its own `seq` — two independent rows, not a foreign-key
        alias, so each room's `since_seq` cursor stays a simple per-room monotonic count.
        """
        if kind not in VALID_KINDS:
            raise ValueError(f"unknown office event kind {kind!r}; expected one of {VALID_KINDS}")
        projected = summarize_office_event(kind, body)
        seq = self._insert(room_id, author=author, kind=kind, body=projected)
        if also_office and room_id != OFFICE_ROOM_ID:
            self._insert(OFFICE_ROOM_ID, author=author, kind=kind, body=projected)
        return seq

    def _insert(self, room_id: str, *, author: str, kind: str, body: dict) -> int:
        cur = self._conn.execute(
            "INSERT INTO messages (room_id, ts, author, kind, body_json) VALUES (?, ?, ?, ?, ?)",
            (room_id, self._now(), author, kind, json.dumps(body, ensure_ascii=False)),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def list(self, room_id: str, since_seq: int = 0) -> list[OfficeMessage]:
        """Every message in `room_id` with `seq > since_seq`, oldest first."""
        rows = self._conn.execute(
            "SELECT seq, room_id, ts, author, kind, body_json FROM messages "
            "WHERE room_id = ? AND seq > ? ORDER BY seq",
            (room_id, since_seq),
        ).fetchall()
        return [
            OfficeMessage(
                seq=r[0], room_id=r[1], ts=r[2], author=r[3], kind=r[4], body=json.loads(r[5]),
            )
            for r in rows
        ]

    def list_rooms(self) -> list[str]:
        """Distinct room ids that have at least one message, oldest-first-seen order."""
        rows = self._conn.execute(
            "SELECT room_id FROM messages GROUP BY room_id ORDER BY MIN(seq)"
        ).fetchall()
        return [r[0] for r in rows]

    def close(self) -> None:
        self._conn.close()
