"""Autopilot stall auto-resolution sweep (v63) — runs inside each coordinator tick.

With `company.autopilot` ON, a task that stalls no longer waits on the CEO: this sweep
resolves it with the SAME one-touch handlers the CEO would use (`ops_stalled_task`),
on a deterministic ladder:

  attempt 1: RETRY — review-stall ⇒ one extra rework round; dead-step ⇒ reset to pending.
  attempt 2: GOAL-REPLAN (v75) — one amend-LLM proposal for a DIFFERENT approach on the
             pending tail, through the CEO amend flow (draft → hash-guarded confirm).
             Fail-closed: LLM error / identity proposal / no pending tail refuse and
             the rung is spent — the ONLY LLM rung, everything else stays code-only.
  attempt 3: review-stall ⇒ ACCEPT the deliverable as-is; dead-step ⇒ DROP the dead rows.
  attempt 4+: leave stalled — the escalation (already sent) stands for the CEO.

`team_tasks.autopilot_attempts` carries the ladder position (incremented BEFORE acting,
so a crash mid-resolution can never re-run the same rung forever). Tasks with
`require_ceo_approval` (per-task opt-out) are never touched. Every decision is audited +
mirrored to the CEO via `record_autopilot_decision`. A handler refusal (ValueError —
e.g. drop refusing the PIC's terminal step) leaves the task stalled for the CEO; the
attempt is spent, matching "auto-recovery must converge, never loop".
"""

from __future__ import annotations

import logging

from my_crew.runtime.team_task_store import TeamTask, TeamTaskStore

logger = logging.getLogger(__name__)

#: Ladder height: retry + goal-replan + accept/drop. Beyond this the CEO decides.
MAX_AUTOPILOT_ATTEMPTS = 3


def run_autopilot_sweep(store: TeamTaskStore) -> int:
    """Resolve stalled tasks under autopilot. Returns how many tasks were acted on."""
    from my_crew.agent.ops_autopilot import autopilot_enabled, record_autopilot_decision

    if not autopilot_enabled():
        return 0

    acted = 0
    for task in store.list_stalled():
        if task.require_ceo_approval:
            continue
        if task.delivery_status == "delivered":
            # The CEO already has this task's ✅ HOÀN THÀNH notice. Resolving it further
            # restarts work on a task they were told was finished, and every rung after
            # that emits more Telegram traffic ON TOP of the completion message —
            # observed live: one brief produced a "done" notice at 21:19 and kept
            # messaging until 21:39. Once delivered, the ladder is over; a stall that
            # survives delivery is the CEO's call, which the escalation already asked for.
            continue
        if task.autopilot_attempts >= MAX_AUTOPILOT_ATTEMPTS:
            continue
        attempt = store.increment_autopilot_attempts(task.id)
        decision, detail = _resolve(task, attempt)
        if decision is None:
            continue
        record_autopilot_decision(
            decision=decision, task_id=task.id, task_title=task.title, detail=detail,
        )
        acted += 1
    return acted


def _resolve(task: TeamTask, attempt: int) -> tuple[str | None, str]:
    """One ladder rung for one stalled task. Returns (decision, detail) —
    (None, ...) when the handler refused / errored (task stays stalled)."""
    from my_crew.agent.ops_stalled_task import (
        run_accept_stalled_result,
        run_drop_stalled_step,
        run_retry_stalled_step,
    )
    from my_crew.runtime.goal_replan import run_goal_replan

    slots = {"task_id": task.id}
    is_review_stall = _has_failed_review(task)
    try:
        if attempt <= 1:
            reply = run_retry_stalled_step(dict(slots))
            return "retry_step", f"Tự thử lại việc '{task.title}' thay CEO — {reply}"
        if attempt == 2:
            reply = run_goal_replan(dict(slots))
            return "goal_replan", (
                f"Tự chỉnh kế hoạch việc '{task.title}' thay CEO (thử lại 1 lần không "
                f"thành, đổi cách tiếp cận) — {reply}"
            )
        if is_review_stall:
            reply = run_accept_stalled_result(dict(slots))
            return "accept_result", (
                f"Tự chấp nhận kết quả việc '{task.title}' thay CEO (đã thử lại 1 lần "
                f"không đạt) — {reply}"
            )
        reply = run_drop_stalled_step(dict(slots))
        return "drop_step", (
            f"Tự bỏ bước chết của việc '{task.title}' thay CEO (đã thử lại 1 lần "
            f"không thành) — {reply}"
        )
    except ValueError as exc:
        # Handler refusal (PIC-terminal drop, nothing actionable, ...) — the stall +
        # its escalation stand for the CEO; the spent attempt prevents a re-loop.
        logger.info("autopilot sweep: task %s rung %s refused: %s", task.id, attempt, exc)
        return None, ""
    except Exception:  # noqa: BLE001 — sweep hygiene: one task's failure never stops the rest
        logger.exception("autopilot sweep: task %s rung %s failed", task.id, attempt)
        return None, ""


def _has_failed_review(task: TeamTask) -> bool:
    from my_crew.agent.ops_stalled_task import _latest_failed_review

    try:
        return _latest_failed_review(task) is not None
    except Exception:  # noqa: BLE001 — classification is best-effort
        return False
