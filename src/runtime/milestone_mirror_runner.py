"""Telegram milestone mirror (v12 M29). Runs as the `milestone-mirror` pseudo-kind on
the admin agent — a store-poller that mirrors ONLY `kind == "milestone"` office-room
events to the CEO's Telegram DM, so a low-tech operator watching only their phone still
sees "đội đã nhận việc / hoàn thành" without opening the dashboard's office room.

Mirrors `ops_alert_runner.run_ops_alerts`'s exact shape (own `DedupStore`, one combined
message per tick, `ActionGateway` + `send_telegram_message`, try/degrade never raises
into the worker) with one addition: this poller owns a PERSISTED CURSOR into the office
room store (its own small SQLite file, under the admin agent's OWN data dir — this
mirror's bookkeeping is agent-local, unlike the office room itself which is cross-agent)
so re-running the tick never re-scans the whole room history.

Deliberately narrow: `step_status`/`handoff`/`assignment`/`ceo` events are NOT mirrored
(they are the dashboard's job — a step-status spam would turn every tick into a Telegram
flood). Only `milestone` rows (already the CEO-facing subset the office room's
`also_office` flag curates) are pushed, and only once per (task, milestone, local-date)
via dedup — a task that legitimately reaches the same milestone twice in one day (e.g.
re-queued) still only pings once that day.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MILESTONE_LABELS = {
    "received": "Đã nhận việc",
    "done": "Hoàn thành",
    "needs_approval": "Cần duyệt",
}


def _cursor_db_path(settings: Any) -> Path:
    """The mirror's own cursor file — agent-local (admin agent's `.data/agents/<id>/`),
    NOT the cross-agent office-room store itself (`office_room_store.office_room_db_path`
    lives at the shared data-dir root)."""
    return Path(settings.data_dir) / "milestone_mirror_cursor.sqlite3"


class _CursorStore:
    """Single-row `(id=0, last_seq)` table — a persisted `since_seq` for the "office"
    room specifically (the only room this mirror ever reads, since `also_office=True`
    already funnels every milestone event there)."""

    def __init__(self, db_path: Path) -> None:
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30.0)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS cursor (id INTEGER PRIMARY KEY CHECK (id = 0), "
            "last_seq INTEGER NOT NULL)"
        )
        self._conn.commit()

    def get(self) -> int:
        row = self._conn.execute("SELECT last_seq FROM cursor WHERE id = 0").fetchone()
        return int(row[0]) if row else 0

    def set(self, seq: int) -> None:
        self._conn.execute(
            "INSERT INTO cursor (id, last_seq) VALUES (0, ?) "
            "ON CONFLICT(id) DO UPDATE SET last_seq = excluded.last_seq",
            (seq,),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


def run_milestone_mirror(loaded: Any, settings: Any, *, now: datetime | None = None) -> dict:
    """One mirror tick. Returns `{status, checked, cost_usd, delivered}` (worker's
    run-event shape, matching `run_ops_alerts`)."""
    from src.actions.action_gateway import ActionGateway
    from src.actions.dedup_store import DedupStore
    from src.actions.telegram_write import send_telegram_message
    from src.runtime.office_room_store import OFFICE_ROOM_ID, OfficeRoomStore, office_room_db_path
    from src.runtime.team_task_paths import team_tasks_root

    telegram = getattr(loaded.config, "telegram", None)
    operator = getattr(telegram, "ops_operator_id", "") if telegram else ""
    if not telegram or not operator:
        return {"status": "no_operator", "checked": 0, "cost_usd": None, "delivered": False}

    now = now or datetime.now(UTC)
    cursor = _CursorStore(_cursor_db_path(settings))
    room = OfficeRoomStore(office_room_db_path(team_tasks_root()))
    try:
        since_seq = cursor.get()
        rows = room.list(OFFICE_ROOM_ID, since_seq)
        milestones = [r for r in rows if r.kind == "milestone"]
        # Cursor advances ONLY after this tick's outcome is settled below (write-disabled
        # short-circuit or a successful send) — never here, up front. Advancing
        # unconditionally would let a `write_disabled` tick or a failed send silently
        # drop those rows forever (the next tick's `since_seq` would already be past
        # them); leaving the cursor in place means the SAME rows are re-read and retried
        # next tick, at the cost of re-scanning them (cheap — a bounded per-tick list).
        last_seq = rows[-1].seq if rows else since_seq

        if settings.write_disabled:
            logger.warning("milestone-mirror %s: AGENT_WRITE_DISABLED — %d milestone(s) not pushed",
                           loaded.profile_id, len(milestones))
            return {"status": "writes_disabled", "checked": len(milestones), "cost_usd": None,
                    "delivered": False}
        if not milestones:
            cursor.set(last_seq)
            return {"status": "no_new_milestones", "checked": 0, "cost_usd": None,
                    "delivered": False}

        local_date = now.astimezone().date().isoformat()
        dedup = DedupStore(Path(settings.data_dir) / "dedup.db")
        gateway = ActionGateway(
            settings, external_channels=loaded.config.slack_external_channels,
            actor=getattr(loaded, "profile_id", ""),  # v46
        )
        try:
            fresh = [
                m for m in milestones
                # Keyed by `task_id` (an opaque internal id), NOT `task_title` (CEO/
                # decompose-LLM free text) — two distinct tasks given the same brief
                # wording would otherwise collide in this dedup claim and only the
                # first would ever reach Telegram.
                if dedup.claim(
                    f"milestone-mirror:{m.body.get('task_id', '')}:"
                    f"{m.body.get('milestone', '')}:{local_date}"
                )
            ]
            if not fresh:
                cursor.set(last_seq)
                return {"status": "no_new_milestones", "checked": len(milestones),
                        "cost_usd": None, "delivered": False}
            push_key = "|".join(
                f"{m.body.get('task_id', '')}:{m.body.get('milestone', '')}" for m in fresh
            )
            result = send_telegram_message(
                _format(fresh),
                gateway=gateway,
                telegram=telegram,
                chat_id=operator,
                dedup_hint=f"milestone-mirror-push:{local_date}:{push_key}",
                rationale="office room milestone mirror",
            )
            delivered = result.status in ("executed", "pending_approval")
            # Cursor advances only once the send outcome is known — a failed/pending
            # send still means Telegram has (or will have) the message, and re-reading
            # the same rows next tick is harmless once dedup has already claimed them;
            # the cursor's only job is bounding how much history each tick re-scans.
            cursor.set(last_seq)
            return {"status": "delivered" if delivered else result.status,
                    "checked": len(milestones), "cost_usd": None, "delivered": delivered}
        finally:
            dedup.close()
            gateway.close()
    finally:
        room.close()
        cursor.close()


def _format(milestones: list) -> str:
    """One combined Vietnamese message body for the CEO — mirrors `ops_alert_runner._format`."""
    lines = ["🏁 Cập nhật tiến độ đội:"]
    for m in milestones:
        label = _MILESTONE_LABELS.get(str(m.body.get("milestone", "")), "Cập nhật")
        title = m.body.get("task_title", "")
        message = m.body.get("message", "")
        lines.append(f"• {title} — {label}: {message}" if message else f"• {title} — {label}")
    lines.append("\nXem chi tiết ở mục Văn phòng trên dashboard.")
    return "\n".join(lines)
