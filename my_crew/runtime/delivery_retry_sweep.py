"""Delivery-retry sweep (v67 P1) — re-send a `done` task's persisted summary when the
room milestone never landed, so "task finished" can never silently miss the CEO.

`aggregate_and_deliver` persists `final_summary` + `delivery_status` before/after its
one delivery attempt; this sweep owns every attempt after that. Pure store reads to
detect (`list_undelivered`: `done` + `pending`/`failed` — `pending` also covers the
crash window between mark-done and the delivery write), then per task:

- attempts < `MAX_DELIVERY_ATTEMPTS`: re-send the SAME persisted summary through the
  ticker's `deliver_room` callable (never re-runs the aggregate LLM call), bump
  `delivery_attempts`; success flips the task to `delivered` and stops the story.
- attempts reaches the cap on a still-failing task: escalate `delivery_failed` exactly
  once (the attempts==cap transition is the dedup — later sweeps see attempts already
  at cap and skip), then leave the task `failed`. The escalation itself already rides
  two independent channels (room milestone + direct Telegram, `make_escalate`), which
  is the floor: a system whose room store AND Telegram are both down has nothing left
  to notify with.

Same posture as `follow_up_sweep`: called every team tick, try/degrade, never breaks
the tick, never touches execution `status`.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Total sweep re-sends per task after the aggregate's own first attempt.
MAX_DELIVERY_ATTEMPTS = 3


def run_delivery_retry_sweep(store, deliver_room, escalate) -> int:
    """One sweep over undelivered `done` tasks. Returns how many were re-delivered.

    `deliver_room`/`escalate` are the ticker's own collaborators (same callables
    `CoordinatorDeps` carries) so a delivery retried here is byte-identical to the
    one `aggregate_and_deliver` sent."""
    try:
        undelivered = store.list_undelivered()
    except Exception:  # noqa: BLE001 — detect must never break the tick
        logger.warning("delivery-retry detect failed", exc_info=True)
        return 0

    redelivered = 0
    for task in undelivered:
        try:
            if task.delivery_attempts >= MAX_DELIVERY_ATTEMPTS:
                continue  # already escalated at the attempts==cap transition below
            summary = task.final_summary or ""
            attempts = store.increment_delivery_attempts(task.id)
            delivered = False
            if summary:
                # deliver_room's contract is "never raises", but the cap escalation
                # below is this sweep's whole reason to exist — a contract-violating
                # raise here must read as a failed attempt, never skip the escalation
                # (review 2026-08-04 M1).
                try:
                    delivered = deliver_room(task, summary) is not False
                except Exception:  # noqa: BLE001
                    logger.warning("deliver_room raised for %s (treated as failed)",
                                   task.id, exc_info=True)
            if delivered:
                store.set_delivery(task.id, status="delivered")
                redelivered += 1
                continue
            store.set_delivery(task.id, status="failed")
            if attempts >= MAX_DELIVERY_ATTEMPTS:
                # A row with no persisted summary (pre-v67 / crash window) was never
                # actually re-sent — say so instead of claiming N tries.
                reason = (
                    f"sau {attempts + 1} lần thử"
                    if summary
                    else "bản tổng kết không còn được lưu để giao lại"
                )
                escalate(
                    task, None, "delivery_failed",
                    f"Việc '{task.title}' đã XONG nhưng không đăng được kết quả vào "
                    f"phòng làm việc ({reason}) — xem trực tiếp bằng "
                    f"`list_team_tasks` hoặc hỏi lại kết quả việc này.",
                )
        except Exception:  # noqa: BLE001 — one task's retry must not block the rest
            logger.warning("delivery retry failed for %s", task.id, exc_info=True)
    return redelivered
