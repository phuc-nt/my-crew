"""What the coordinator does with a step that finished but was not acceptable.

Phase 1 gave such a step the terminal status `needs_decision`: it produced a real
artifact, it just failed its own acceptance criteria, and it blocks its dependents
until somebody judges it. This module is that judgement — the piece that makes the
coordinator an actual supervisor instead of a DAG walker that only ever asked "is the
pid alive?".

Three outcomes, and only three:

- `retry_with_guidance` — the result is fixable and the same staffer can fix it, given
  concrete direction about what was missing. The step goes back to `pending` with the
  guidance appended to its handoff, so the next attempt actually sees it.
- `reassign` — the staffer is the wrong one for this (the UAT case: a researcher with
  no search tool cannot research). Re-point the step at someone who can, then re-run.
  Gated by `roster_ok`, so the LLM cannot invent an assignee.
- `give_up` — nothing here is recoverable. Say so out loud, in the final summary, and
  stop. An honest "không làm được vì X" is a legitimate ending; silently retrying
  forever is not.

The anti-loop bound is `intervention_count` per step, and it is a hard gate, not a
hint: at the cap this module concludes `give_up` WITHOUT consulting the model at all —
deterministic, free, and impossible to talk out of. An LLM that fails or returns
nonsense also degrades to `give_up` rather than leaving the task hanging.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from my_crew.agent.coordinator_graph import CoordinatorDeps, TickResult
    from my_crew.runtime.team_task_steps import TeamStep
    from my_crew.runtime.team_task_store import TeamTask

logger = logging.getLogger(__name__)

#: How many times the coordinator may intervene on ONE step before it must conclude.
#: Two attempts past the original is enough to fix a fixable step (once with guidance,
#: once with a different person); a third would just be spending money to re-learn the
#: same thing.
MAX_INTERVENTIONS = 2

_VALID_DECISIONS = frozenset({"retry_with_guidance", "reassign", "give_up"})


@dataclass(frozen=True)
class StuckJudgement:
    """The coordinator's ruling on one stuck step. `guidance` is what the next attempt
    is told; `assign_to` names the replacement staffer for `reassign`; `reason` is the
    CEO-facing explanation when giving up."""

    decision: str
    guidance: str = ""
    assign_to: str = ""
    reason: str = ""


def build_stuck_brief(deps: CoordinatorDeps, task: TeamTask, step: TeamStep) -> str:
    """Everything the judge needs to rule on this step, as ONE text block.

    The step's own output is included because a decision made without reading the
    result is exactly the mechanical DAG-walking this phase exists to replace. That
    output is untrusted data — it may echo an injection phrase the step absorbed from a
    web search — so it goes through `format_internal_content`, the same delimiter +
    spotlight treatment `make_aggregate` gives step results.
    """
    from my_crew.agent.team_task_artifact import read_step_artifact
    from my_crew.runtime.team_task_paths import team_tasks_root
    from my_crew.tools.search_result_formatter import format_internal_content

    artifact = read_step_artifact(team_tasks_root(), task.id, step.seq) or {}
    result_text = str(artifact.get("result_text") or "")[:2000]
    body = format_internal_content(result_text, label="ket-qua-buoc") or result_text
    return (
        f"Việc: {task.title}\n"
        f"Bước đang kẹt: {step.title}\n"
        f"Người đang làm: {step.assigned_to}\n"
        f"Tiêu chí đạt: {step.acceptance or '(không ghi rõ)'}\n"
        f"Số lần đã can thiệp: {step.intervention_count}\n"
        f"Kết quả bước đã nộp (KHÔNG đạt tiêu chí trên):\n{body or '(trống)'}"
    )


def _coerce(raw: Any) -> StuckJudgement:
    """Force whatever the seam returned into one of the three legal rulings.

    Anything unrecognised becomes `give_up`: an unparseable judgement is not a reason
    to keep a task alive in limbo, and silently defaulting to "retry" would turn a
    broken seam into the infinite loop the cap exists to prevent.
    """
    if isinstance(raw, StuckJudgement):
        judgement = raw
    elif isinstance(raw, dict):
        judgement = StuckJudgement(
            decision=str(raw.get("decision") or ""),
            guidance=str(raw.get("guidance") or ""),
            assign_to=str(raw.get("assign_to") or ""),
            reason=str(raw.get("reason") or ""),
        )
    else:
        return StuckJudgement(decision="give_up", reason="không phán đoán được")
    if judgement.decision not in _VALID_DECISIONS:
        return StuckJudgement(decision="give_up", reason="không phán đoán được")
    return judgement


def _judge(deps: CoordinatorDeps, task: TeamTask, step: TeamStep) -> StuckJudgement:
    """Ask the seam for a ruling, degrading to `give_up` on any failure — the judgement
    call is best-effort in exactly the way `aggregate` is: never allowed to raise into
    the tick and lose work the tick already did."""
    try:
        return _coerce(deps.judge_stuck_step(build_stuck_brief(deps, task, step), step))
    except Exception:  # noqa: BLE001 — a broken judge must not wedge the task
        logger.exception(
            "team-tick: judge_stuck_step failed for task %s step %s", task.id, step.step_id
        )
        return StuckJudgement(decision="give_up", reason="không phán đoán được")


def decide_stuck_step(
    deps: CoordinatorDeps, task: TeamTask, step: TeamStep,
) -> TickResult:
    """Rule on one `needs_decision` step and carry the ruling out.

    Always returns an actionable `TickResult` — this function never leaves the step in
    `needs_decision`, because a step nobody ruled on would stall the task exactly the
    way the old mechanical walk did.
    """

    # Spend the intervention BEFORE judging, and read the cap off the committed value:
    # a judge call that crashes or a process that dies mid-decision must still have
    # burned the attempt, or a crash-looping judge would retry forever for free.
    count = deps.store.bump_intervention(task.id, step.step_id)
    if count > MAX_INTERVENTIONS:
        return _give_up(
            deps, task, step,
            f"đã can thiệp {MAX_INTERVENTIONS} lần mà bước '{step.title}' vẫn không đạt",
        )

    judgement = _judge(deps, task, step)
    # Retry-first policy: the FIRST ruling on a step never reassigns. Measured across a
    # day of live tasks the judge chose reassign on the first failure 5 of 6 times, and
    # it was the wrong call every time — the original assignee fixed it on retry once
    # given the failure list, while the new assignee started from zero (and twice was a
    # deep_agent that could not even run the web search the step needed). A reassign is
    # allowed from the second ruling, when guidance demonstrably did not help.
    if judgement.decision == "reassign" and count <= 1:
        if judgement.guidance.strip() or judgement.reason.strip():
            coerced = StuckJudgement(
                decision="retry_with_guidance",
                guidance=(judgement.guidance.strip()
                          or f"Làm lại theo đúng tiêu chí; lý do trượt: {judgement.reason}"),
                reason=judgement.reason,
            )
            logger.info(
                "team-tick: first-ruling reassign for %s/%s coerced to retry_with_guidance",
                task.id, step.step_id,
            )
            return _retry(deps, task, step, coerced)
    if judgement.decision == "reassign":
        return _reassign(deps, task, step, judgement)
    if judgement.decision == "retry_with_guidance":
        return _retry(deps, task, step, judgement)
    return _give_up(deps, task, step, judgement.reason or "không nêu lý do")


def _retry(
    deps: CoordinatorDeps, task: TeamTask, step: TeamStep, judgement: StuckJudgement,
) -> TickResult:
    from my_crew.agent.coordinator_graph import TickResult

    guidance = judgement.guidance.strip()
    if not guidance:
        # "Try again" with no direction is just burning an attempt on the same failure.
        return _give_up(deps, task, step, "không đưa được chỉ dẫn cụ thể để làm lại")
    deps.store.append_step_guidance(task.id, step.step_id, guidance)
    deps.store.reset_step_to_pending(task.id, step.step_id)
    deps.escalate(
        task, step, "stuck",
        f"Bước '{step.title}' chưa đạt — giao lại kèm chỉ dẫn: {guidance[:300]}",
    )
    return TickResult(
        task_id=task.id, action="stuck_retry",
        detail=f"{step.step_id} retry_with_guidance",
    )


def _reassign(
    deps: CoordinatorDeps, task: TeamTask, step: TeamStep, judgement: StuckJudgement,
) -> TickResult:
    from my_crew.agent.coordinator_graph import TickResult

    new_assignee = judgement.assign_to.strip()
    # The roster is the authority on who may hold a step, exactly as at dispatch time —
    # a judgement naming an unknown, disabled, or non-assignable id is refused outright
    # rather than written and left to fail later at spawn.
    if not new_assignee or new_assignee == step.assigned_to or not deps.roster_ok(new_assignee):
        return _give_up(
            deps, task, step,
            f"không đổi được người làm bước '{step.title}' (đề xuất không hợp lệ)",
        )
    # Moving work to a different NAME is not the same as moving it toward capability.
    # A web data-collection step handed to an agent with no search tool is dispatchable
    # and doomed — it can only report the gap, or invent the numbers. Refusing here
    # concludes the task honestly ("thiếu công cụ") instead of spending the remaining
    # interventions rotating the step between agents that all lack the same tool.
    if not deps.can_do_step(new_assignee, step):
        return _give_up(
            deps, task, step,
            f"không có người đủ công cụ cho bước '{step.title}' "
            f"({new_assignee} thiếu công cụ bước này cần)",
        )
    deps.store.reassign_step(task.id, step.step_id, new_assignee)
    if judgement.guidance.strip():
        deps.store.append_step_guidance(task.id, step.step_id, judgement.guidance.strip())
    deps.store.reset_step_to_pending(task.id, step.step_id)
    deps.escalate(
        task, step, "stuck",
        f"Bước '{step.title}' chưa đạt — chuyển cho {new_assignee} làm lại.",
    )
    return TickResult(
        task_id=task.id, action="stuck_reassigned",
        detail=f"{step.step_id} -> {new_assignee}",
    )


def _give_up(
    deps: CoordinatorDeps, task: TeamTask, step: TeamStep, reason: str,
) -> TickResult:
    """Conclude that the task cannot be completed, and say why.

    The step is marked `failed` (it is genuinely over) and the TASK is stalled with a
    `final_summary` naming the reason, so the existing delivery path carries an honest
    "không làm được vì X" to the CEO rather than silence or a fake success.
    """
    from my_crew.agent.coordinator_graph import TickResult, _reflect_safely

    summary = f"Việc '{task.title}' KHÔNG LÀM ĐƯỢC: bước '{step.title}' — {reason}."
    # attempt-guarded like every other ticker-side terminal write: `step` is a snapshot
    # read at the top of this tick, so a concurrent re-reservation (a CEO's manual
    # retry, a second ticker) must make this a clean no-op rather than clobber the
    # newer attempt's row and orphan its live worker.
    deps.store.mark_failed(
        task.id, step.step_id, outcome_ref=step.outcome_ref, attempt_id=step.attempt_id,
    )
    deps.store.set_delivery(task.id, status="pending", summary=summary)
    deps.store.set_task_status(task.id, "stalled")
    delivered = deps.deliver_room(task, summary) is not False
    deps.store.set_delivery(task.id, status="delivered" if delivered else "failed")
    deps.escalate(task, step, "gave_up", summary)
    _reflect_safely(deps, task, "stalled", f"gave up on step '{step.title}': {reason}")
    return TickResult(task_id=task.id, action="gave_up", detail=f"{step.step_id}: {reason}"[:80])
