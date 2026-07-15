"""Coordinator-tick collaborator factories split out of `team_tick_runner.py` to keep
that module under the repo's ~200 LOC guideline: the aggregate (LLM summarize), room
delivery, and Telegram escalation callables `CoordinatorDeps` needs.
"""

from __future__ import annotations

import logging
from typing import Any

from src.runtime.team_task_paths import team_tasks_root
from src.runtime.team_task_store import TeamStep, TeamTask

logger = logging.getLogger(__name__)

#: Task-level `event_kind`s where the ticker has just moved the WHOLE task to
#: `stalled` (never a single-step-only failure that might still resolve via a later
#: tick's retry/other-step-completes path) — a full replan is the actually-relevant
#: remedy for these, so the escalation gets a suggested `adjust_team_task` command.
_STALL_EVENT_KINDS = frozenset({
    "task_stalled_dead_step", "plan_hash_mismatch", "review_rounds_exhausted",
    "cost_cap_exceeded",
})

#: CONSTANT template, `{task_id}` interpolation ONLY — deliberately never composed
#: from task content/LLM output. A message built from task/step titles (which can
#: carry text absorbed from a hostile CEO brief or a prior step's echoed injection)
#: could smuggle a misleading amend brief the CEO copy-pastes verbatim as a command;
#: this template carries no such content, only the stable, code-assigned task id.
_AMEND_SUGGESTION_TEMPLATE = (
    "\n\nCEO có thể chỉnh kế hoạch: `chỉnh kế hoạch {task_id}: <yêu cầu>`"
)


def make_aggregate(loaded: Any, settings: Any):
    """One LLM call summarizing every step's handoff artifact into a room-ready message.
    Falls back to a deterministic (no-LLM) join of step titles/results on any LLM
    failure — an aggregate must never block a task stuck at 100%-done from being marked
    `done` just because the summarizing call itself failed.

    Second-order injection: each step's `result_text` is not automatically
    trusted just because it was produced inside this codebase — it may itself echo an
    injection phrase absorbed from a web-search result or a hostile CEO brief that step
    read. The LLM-summarize prompt (not the plain-join fallback, which never reaches a
    model) wraps every step's snippet through `search_result_formatter
    .format_internal_content` — same delimiter/scan/spotlight treatment a first-order
    external source gets — before folding it into the aggregate prompt.
    """

    def _aggregate(task: TeamTask) -> tuple[str, float | None]:
        from src.agent.team_task_artifact import read_step_artifact
        from src.tools.search_result_formatter import format_internal_content

        parts: list[str] = []
        for step in sorted(task.steps, key=lambda s: s.seq):
            artifact = read_step_artifact(team_tasks_root(), task.id, step.seq)
            text = ""
            if artifact:
                text = str(artifact.get("result_text") or artifact.get("status") or "")
            snippet = text[:500] if text else "(không có kết quả)"
            parts.append(f"- {step.title}: {snippet}")
        fallback_summary = f"Việc '{task.title}' đã hoàn tất:\n" + "\n".join(parts)

        if not settings.openrouter_api_key:
            return fallback_summary, None
        try:
            from src.llm.client import LlmClient

            wrapped_parts = [
                format_internal_content(p, label=f"step-{i + 1}") or p
                for i, p in enumerate(parts)
            ]
            client = LlmClient(settings)
            prompt = (
                f"Tóm tắt ngắn gọn (tiếng Việt) kết quả của việc '{task.title}' cho "
                f"CEO, dựa trên các bước sau:\n\n" + "\n\n".join(wrapped_parts)
            )
            result = client.complete([{"role": "user", "content": prompt}])
            return result.content or fallback_summary, result.cost_usd
        except Exception:  # noqa: BLE001 — never let a summarizer failure block delivery
            logger.exception("team-tick: aggregate LLM call failed for task %s", task.id)
            return fallback_summary, None

    return _aggregate


def make_deliver_room():
    """Posts the aggregate summary to the group room as a "task done" milestone (also
    mirrored into the shared office room — `also_office=True`). `append_office_event`
    is itself try/degrade, so this callable never raises (a missing/broken room store
    is not a reason to leave a 100%-done task undelivered/un-marked-done)."""

    def _deliver(task: TeamTask, summary: str) -> None:
        from src.runtime.office_room_append import append_office_event, room_for_task

        logger.info("team-tick: task %s aggregate ready: %s", task.id, summary[:200])
        append_office_event(
            room_for_task(task.id), author="coordinator", kind="milestone",
            body={"task_id": task.id, "task_title": task.title, "milestone": "done",
                  "message": summary},
            also_office=True,
        )

    return _deliver


def make_escalate(loaded: Any, settings: Any):
    """Telegram escalation, mirroring `ops_alert_runner.run_ops_alerts`'s exact
    gateway-construction + `send_telegram_message` call shape. try/degrade: any failure
    (no operator configured, gateway/network error) is logged and swallowed — this
    callable's documented contract (`CoordinatorDeps.escalate`) is "never raises"."""

    def _escalate(task: TeamTask, step: TeamStep | None, event_kind: str, message: str) -> None:
        if event_kind in _STALL_EVENT_KINDS:
            message = message + _AMEND_SUGGESTION_TEMPLATE.format(task_id=task.id)

        # Room append comes FIRST and unconditionally: the admin agent's milestone
        # mirror polls the room store and DMs the CEO, so an escalation reaches
        # Telegram even when the coordinator has no bot binding of its own. The direct
        # coordinator-Telegram send below is only the low-latency fast path.
        try:
            from src.runtime.office_room_append import append_office_event, room_for_task

            append_office_event(
                room_for_task(task.id), author="coordinator", kind="milestone",
                body={"task_id": task.id, "task_title": task.title, "milestone": event_kind,
                      "message": message},
                also_office=True,
            )
        except Exception:  # noqa: BLE001 — escalation must never crash the ticker
            logger.exception("team-tick: escalate(%s) room append failed for task %s",
                             event_kind, task.id)
        try:
            from src.actions.action_gateway import ActionGateway
            from src.actions.telegram_write import send_telegram_message

            telegram = getattr(loaded.config, "telegram", None)
            operator = getattr(telegram, "ops_operator_id", "") if telegram else ""
            if not telegram or not operator:
                logger.info(
                    "team-tick: escalate(%s) for task %s has no coordinator Telegram "
                    "binding — delivered via the room milestone mirror only",
                    event_kind, task.id,
                )
                return
            gateway = ActionGateway(
                settings, external_channels=loaded.config.slack_external_channels,
                actor=getattr(loaded, "profile_id", ""),  # v46
            )
            try:
                step_id = step.step_id if step is not None else ""
                send_telegram_message(
                    message,
                    gateway=gateway,
                    telegram=telegram,
                    chat_id=operator,
                    dedup_hint=f"team-tick:{task.id}:{step_id}:{event_kind}",
                    rationale=f"team task escalation: {event_kind}",
                )
            finally:
                gateway.close()
        except Exception:  # noqa: BLE001 — escalation must never crash the ticker
            logger.exception(
                "team-tick: escalate(%s) failed for task %s (continuing — task state "
                "already updated)", event_kind, task.id,
            )

    return _escalate
