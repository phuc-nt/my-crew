"""Proactive follow-up sweep (v34 P3) — the coordinator ĐEO BÁM stuck work instead
of letting it sit until the CEO happens to look.

Detection is PURE SQL over the team-task store — no LLM call ever happens here
(wake-gate posture, v31): the ticker runs this every tick, so the detect pass must
cost microseconds. What counts as "stuck":

- a task `stalled` (cost cap, dead-end, hash mismatch — already escalated ONCE at
  the moment it stalled, then silence);
- an `open`/`running` task with NO step progress (no step touched) for
  `STUCK_AFTER_H` hours;
- a step paused on the CEO (`waiting_clarify`/`awaiting_approval`) for longer than
  `WAITING_CEO_AFTER_H` hours — here the CEO is the blocker, so the ladder starts at
  the reminder level.

Escalation ladder — one rung per firing, `COOLDOWN_H` between firings per task, all
templates static (KISS: LLM prose adds nothing to "việc X đứng yên N giờ"):

  1. office event (milestone) — the feed shows "coordinator nhắc việc" (audit trail
     included, it's an append-only room event);
  2. a clarify question to the CEO ("Đợi thêm" / "Huỷ việc" options) — surfaces in
     Duyệt + Telegram buttons through the ONE clarify door (v33 P4); the answer is
     recorded for the CEO's own decision-making (v1 does NOT auto-act on it);
  3. a direct Telegram notice via the admin ops gateway (`operator_notify`).

Level then stays at 3, and the rung-3 Telegram notice is day-bucketed via its dedup
hint — at most MỘT tin nhắn mỗi ngày cho một việc kẹt mãi, never spam. Any progress on
the task naturally stops the sweep from matching it; a task leaving the stuck set
resets its ladder (`follow_up_level = 0`) so a NEW stall starts over at rung 1.

The sweep's own writes touch ONLY the two bookkeeping columns — never step/task
status, never the plan hash. Every rung is best-effort: a failed notify never breaks
the tick.
"""

from __future__ import annotations

import datetime as _dt
import logging

logger = logging.getLogger(__name__)

#: An open/running task with no step activity for this long is "stuck".
STUCK_AFTER_H = 24.0
#: A step waiting on the CEO (clarify/approval) for this long deserves a reminder.
WAITING_CEO_AFTER_H = 4.0
#: Minimum gap between two follow-up firings for the same task.
COOLDOWN_H = 8.0
#: Ladder ceiling — level 3 repeats (one Telegram notice per cooldown), never grows.
MAX_LEVEL = 3


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC)


def run_follow_up_sweep(store, *, now: _dt.datetime | None = None) -> int:
    """One sweep: find stuck tasks, fire at most ONE ladder rung per task (cooldown
    permitting), reset the ladder for tasks that recovered. Returns rungs fired."""
    now = now or _now()
    fired = 0
    try:
        stuck = _detect_stuck(store, now)
    except Exception:  # noqa: BLE001 — detect must never break the tick
        logger.warning("follow-up detect failed", exc_info=True)
        return 0

    stuck_ids = {t["task_id"] for t in stuck}
    _reset_recovered(store, stuck_ids)

    for item in stuck:
        cooldown_ok = _cooldown_elapsed(item["last_follow_up_at"], now)
        if not cooldown_ok:
            continue
        level = min(int(item["follow_up_level"]) + 1, MAX_LEVEL)
        try:
            ok = _fire(level, item, now)
        except Exception:  # noqa: BLE001 — a failed rung must not block other tasks
            logger.warning("follow-up rung %d failed for %s", level, item["task_id"],
                           exc_info=True)
            continue
        if not ok:
            # refused/deduplicated (clarify cap, notify off) — do NOT record a firing,
            # the next sweep retries the same rung (review M2/M3).
            continue
        store._conn.execute(
            "UPDATE team_tasks SET last_follow_up_at = ?, follow_up_level = ? "
            "WHERE id = ?",
            (now.isoformat(), level, item["task_id"]),
        )
        store._conn.commit()
        fired += 1
    return fired


def _cooldown_elapsed(last: str | None, now: _dt.datetime) -> bool:
    if not last:
        return True
    try:
        prev = _dt.datetime.fromisoformat(last)
    except ValueError:
        return True
    return (now - prev) >= _dt.timedelta(hours=COOLDOWN_H)


def _detect_stuck(store, now: _dt.datetime) -> list[dict]:
    """The stuck set, one dict per task: {task_id, title, reason, follow_up_level,
    last_follow_up_at}. Pure reads."""
    out: list[dict] = []
    stuck_cutoff = (now - _dt.timedelta(hours=STUCK_AFTER_H)).isoformat()
    ceo_cutoff = (now - _dt.timedelta(hours=WAITING_CEO_AFTER_H)).isoformat()

    rows = store._conn.execute(
        "SELECT id, title, status, created_at, last_follow_up_at, follow_up_level "
        "FROM team_tasks WHERE status IN ('stalled', 'open', 'running')"
    ).fetchall()
    for task_id, title, status, created_at, last_fu, level in rows:
        base = {"task_id": task_id, "title": title,
                "last_follow_up_at": last_fu, "follow_up_level": level or 0}
        if status == "stalled":
            out.append({**base, "reason": "việc đã KẸT (stalled) và chưa ai xử lý"})
            continue
        # a step waiting on the CEO too long — the CEO is the blocker here
        waiting = store._conn.execute(
            "SELECT COUNT(*) FROM team_steps WHERE task_id = ? "
            "AND status IN ('waiting_clarify', 'awaiting_approval') "
            "AND COALESCE(last_seen, spawned_at, ?) < ?",
            (task_id, created_at, ceo_cutoff),
        ).fetchone()[0]
        if waiting:
            out.append({**base, "reason":
                        f"{waiting} bước đang chờ CEO (duyệt/trả lời) quá "
                        f"{WAITING_CEO_AFTER_H:.0f} giờ"})
            continue
        # no step progress at all for too long
        newest = store._conn.execute(
            "SELECT MAX(COALESCE(last_seen, spawned_at)) FROM team_steps "
            "WHERE task_id = ?",
            (task_id,),
        ).fetchone()[0]
        if (newest or created_at) < stuck_cutoff:
            out.append({**base, "reason":
                        f"không có tiến triển nào suốt {STUCK_AFTER_H:.0f} giờ"})
    return out


def _reset_recovered(store, stuck_ids: set[str]) -> None:
    """Tasks that left the stuck set start their ladder over on the next stall."""
    store._conn.execute(
        "UPDATE team_tasks SET follow_up_level = 0 "
        "WHERE follow_up_level > 0 AND status = 'done'"
    )
    if stuck_ids:
        placeholders = ",".join("?" * len(stuck_ids))
        store._conn.execute(
            f"UPDATE team_tasks SET follow_up_level = 0 "
            f"WHERE follow_up_level > 0 AND status IN ('open', 'running') "
            f"AND id NOT IN ({placeholders})",
            tuple(stuck_ids),
        )
    else:
        store._conn.execute(
            "UPDATE team_tasks SET follow_up_level = 0 "
            "WHERE follow_up_level > 0 AND status IN ('open', 'running')"
        )
    store._conn.commit()


def _fire(level: int, item: dict, now: _dt.datetime) -> bool:
    """One ladder rung. Static templates; every transport is an existing door.
    Returns True iff the rung actually LANDED — a refusal (clarify cap) or a
    deduplicated/failed notify reads as not-fired so the ladder does not advance
    past a rung nobody saw (review M2/M3)."""
    task_id, title, reason = item["task_id"], item["title"], item["reason"]
    if level == 1:
        from src.runtime.office_room_append import append_office_event, room_for_task

        append_office_event(
            room_for_task(task_id), author="coordinator", kind="milestone",
            body={"task_id": task_id, "task_title": title, "milestone": "follow_up",
                  "message": f"⏰ Nhắc việc: {reason}."},
            also_office=True,
        )
        return True
    if level == 2:
        from src.runtime.clarify_service import ask_ceo

        _note, clarify_id = ask_ceo(
            agent_id="coordinator", task_id=task_id,
            question=f"Việc \"{title}\" — {reason}. Xử lý thế nào?",
            options=["Đợi thêm", "Huỷ việc này"],
        )
        return clarify_id is not None
    from src.runtime.operator_notify import notify_operator_best_effort

    # Day-bucketed dedup hint: the gateway's dedup store has no TTL, so a stable hint
    # would silence rung 3 forever after its first send. One notice per task per DAY
    # is the intended anti-spam ceiling for a forever-stuck task.
    return notify_operator_best_effort(
        f"⏰ Việc \"{title}\" vẫn kẹt: {reason}. Xem mục Duyệt/Văn phòng để xử lý.",
        dedup_hint=f"follow-up-{task_id}-{now:%Y%m%d}",
        rationale="follow-up: việc đội đứng yên quá ngưỡng",
    )
