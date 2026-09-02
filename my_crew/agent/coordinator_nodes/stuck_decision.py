"""What the coordinator does with a step that finished but was not acceptable.

Phase 1 gave such a step the terminal status `needs_decision`: it produced a real
artifact, it just failed its own acceptance criteria, and it blocks its dependents
until somebody judges it. This module is that judgement — the piece that makes the
coordinator an actual supervisor instead of a DAG walker that only ever asked "is the
pid alive?".

Four outcomes, and only four:

- `accept` — the result actually meets the step's own acceptance list and only the
  grader was wrong (measured live: a cohort analysis carrying every required figure
  was failed twice for "not mentioning" them). Take it as it stands: the step is
  `done` with the worker's artifact, no re-run, no reassign, no coordinator rewrite.
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

_VALID_DECISIONS = frozenset({"accept", "retry_with_guidance", "reassign", "give_up"})

#: How much of the CEO's original request the judge is shown. `task.title` is the
#: request's first paragraph cut at 120 chars, so a judge given only the title reads a
#: brief that literally ends mid-word — and rules from that (observed live: "brief gốc
#: bị cắt ngọn ... cần CEO rõ ràng 3 tiêu chí", on a request that named all three).
_MAX_REQUEST_CHARS = 2000


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
    from my_crew.tools.search_result_formatter import (
        format_internal_content,
        truncate_preserving_delimiters,
    )

    artifact = read_step_artifact(team_tasks_root(), task.id, step.seq) or {}
    result_text = str(artifact.get("result_text") or "")[:2000]
    body = format_internal_content(result_text, label="ket-qua-buoc") or result_text
    # The step's own grader already named what was missing, and that list is written to
    # the artifact this function opens anyway. Leaving it out made the judge re-derive
    # the diagnosis from the raw output — the one input that cannot show what ISN'T
    # there — so its guidance came back generic ("làm lại cho đúng tiêu chí") instead of
    # naming the gap. These are the same failures `rework` is handed, kept unformatted
    # because they are our grader's words, not fetched content.
    failures = [str(f) for f in (artifact.get("self_check_failures") or []) if str(f).strip()]
    failure_block = (
        "\nBước tự chấm trượt ở những điểm sau:\n"
        + "\n".join(f"- {f}" for f in failures)
        if failures else ""
    )
    # The judge's OWN earlier orders, accumulated by `append_step_guidance`. Without
    # them the second ruling cannot know what the first one demanded, so it re-derives
    # the same direction from the same inputs — measured live (lanes6, both music
    # cases): attempt-2 and attempt-3 work orders carried near-verbatim identical
    # guidance, burning the intervention cap on a repeat. Like `failures`, this is our
    # own system's text, not fetched content, so it stays unwrapped.
    prior_guidance = (step.guidance or "").strip()
    guidance_block = (
        f"\nChỉ dẫn ĐÃ RA ở (các) lần can thiệp trước — bước vẫn trượt sau khi làm "
        f"theo:\n{prior_guidance}"
        if prior_guidance else ""
    )
    request = truncate_preserving_delimiters(
        (task.original_request or "").strip(), _MAX_REQUEST_CHARS,
    )
    request_block = f"Yêu cầu gốc của CEO (đầy đủ):\n{request}\n" if request else ""
    return (
        f"Việc: {task.title}\n"
        f"{request_block}"
        f"Bước đang kẹt: {step.title}\n"
        f"Người đang làm: {step.assigned_to}\n"
        f"Tiêu chí đạt: {step.acceptance or '(không ghi rõ)'}\n"
        f"Số lần đã can thiệp: {step.intervention_count}"
        f"{guidance_block}"
        f"{failure_block}\n"
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


def intervention_cap(deps: CoordinatorDeps, step: TeamStep) -> int:
    """How many rulings THIS step gets before the coordinator must conclude.

    `MAX_INTERVENTIONS` is the general cap. A terminal step (`final_deliverable`, the
    one whose artifact IS the task's answer) on a coordinator that can write that
    answer itself (`self_do_step` wired) gets ONE ruling: after a guided retry has
    failed, a second round of guidance/reassign spends more than the coordinator
    simply finishing the deliverable from the finished upstream work — which is what
    give-up does here (`try_self_resolve`). Non-terminal steps keep the full cap: the
    coordinator cannot stand in for a step whose output others still depend on.
    """
    if deps.self_do_step is not None and bool(getattr(step, "final_deliverable", False)):
        return 1
    return MAX_INTERVENTIONS


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
    cap = intervention_cap(deps, step)
    if count > cap:
        return _give_up(
            deps, task, step,
            f"đã can thiệp {cap} lần mà bước '{step.title}' vẫn không đạt",
        )

    judgement = _judge(deps, task, step)
    if judgement.decision == "accept":
        return _accept(deps, task, step, judgement)
    # Retry-first policy: the FIRST ruling on a step never reassigns. Measured across a
    # day of live tasks the judge chose reassign on the first failure 5 of 6 times, and
    # it was the wrong call every time — the original assignee fixed it on retry once
    # given the failure list, while the new assignee started from zero (and twice was a
    # deep_agent that could not even run the web search the step needed). A reassign is
    # allowed from the second ruling, when guidance demonstrably did not help.
    if judgement.decision == "reassign" and count <= 1:
        # Unconditional: a judge that proposed reassign with NO guidance and NO reason
        # (observed live — the first coercion attempt had a both-empty escape hatch and
        # the very next ruling slipped through it) still coerces; the fallback guidance
        # tells the author to re-grade its own output against the acceptance list,
        # which is exactly the information the failed self-check already produced.
        coerced = StuckJudgement(
            decision="retry_with_guidance",
            guidance=(judgement.guidance.strip()
                      or (f"Làm lại theo đúng tiêu chí; lý do trượt: {judgement.reason}"
                          if judgement.reason.strip()
                          else "Làm lại bước theo ĐÚNG các tiêu chí nghiệm thu của bước: "
                               "đọc kỹ từng dòng tiêu chí, tự kiểm tra kết quả đạt từng "
                               "mục (đủ số lượng, có link nguồn thật) rồi mới nộp.")),
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


def _accept(
    deps: CoordinatorDeps, task: TeamTask, step: TeamStep, judgement: StuckJudgement,
) -> TickResult:
    """Take the failed-self-check result as the step's answer.

    The worker's artifact stays as written (it IS the accepted content); only its
    status flips to `done` so dependents and the aggregate read it as finished work,
    and the acceptance reason is recorded on it for the CEO's audit. The row write is
    `mark_done_by_coordinator`: `done` from a `needs_decision` row only, attempt-
    guarded, review flag dropped — the judge's reading was the review.

    EXCEPT on a plan routed as do+review: there the CEO asked for an independent
    reviewer of the deliverable, and the judge only settled a self-check dispute —
    it never read the work as a reviewer would. Measured live: the accept dropped
    the flag, no review row was ever minted, and the task closed "sau soát chéo"
    with nobody having cross-checked anything. On that shape the planned flag stays,
    so `maybe_insert_review` still mints the reviewer row.
    """
    from my_crew.agent.coordinator_graph import TickResult
    from my_crew.agent.crew_shape import DO_REVIEW_SHAPE
    from my_crew.agent.team_task_artifact import read_step_artifact, write_step_artifact
    from my_crew.runtime.team_task_paths import team_tasks_root

    reason = " ".join(judgement.reason.split()) or "kết quả đã đạt tiêu chí của bước"
    route = deps.store.get_route(task.id) or {}
    keep_review = route.get("shape") == DO_REVIEW_SHAPE
    if not deps.store.mark_done_by_coordinator(
        task.id, step.step_id, outcome_ref=step.outcome_ref, attempt_id=step.attempt_id,
        keep_review=keep_review,
    ):
        logger.warning(
            "team-tick: accept on %s/%s matched no row (not needs_decision on attempt %s)",
            task.id, step.step_id, step.attempt_id or "<none>",
        )
        return TickResult(
            task_id=task.id, action="none", detail=f"{step.step_id} accept matched no row",
        )
    try:
        artifact = read_step_artifact(team_tasks_root(), task.id, step.seq)
        if artifact:
            write_step_artifact(
                team_tasks_root(), task.id, step.seq,
                {**artifact, "status": "done", "accepted_by_coordinator": reason},
            )
    except Exception:  # noqa: BLE001 — the row is the source of truth; the note is audit
        logger.exception(
            "team-tick: could not annotate accepted artifact %s/%s", task.id, step.step_id,
        )
    deps.escalate(
        task, step, "stuck",
        f"Bước '{step.title}' tự chấm trượt nhưng điều phối đọc lại thấy đã đạt tiêu chí "
        f"— nhận kết quả như đang có: {reason[:300]}",
    )
    return TickResult(task_id=task.id, action="stuck_accepted", detail=f"{step.step_id}: {reason}")


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
        # Refusing the move is right; ENDING the task on it is not. Live task
        # c357f5481bf5 stalled exactly here: with `needs_web` declared and only the
        # researcher holding `web_search`, no reassign target could ever pass this
        # gate, so the judge spending ruling #2 on one traded away the last real
        # attempt for a move that was unreachable by construction. Since ruling #1 is
        # always coerced to retry, that left the capable original holder with a single
        # guided attempt instead of two. Degrade to the retry this should have been —
        # `_retry` keeps the step with its current (capable) assignee, and the
        # intervention cap above still concludes the task once attempts are truly spent.
        logger.info(
            "team-tick: unreachable reassign for %s/%s (%s lacks the step's tools) "
            "degraded to retry_with_guidance",
            task.id, step.step_id, new_assignee,
        )
        # The escalation still has to NAME the missing capability: "đổi người không
        # được" alone tells a CEO nothing they can act on, while "X thiếu công cụ" points
        # at the two real choices (grant the tool, or accept the gap).
        deps.escalate(
            task, step, "stuck",
            f"Không đổi được người cho bước '{step.title}': {new_assignee} thiếu công cụ "
            f"bước này cần, nên {step.assigned_to} tự làm lại.",
        )
        return _retry(deps, task, step, StuckJudgement(
            decision="retry_with_guidance",
            guidance=(judgement.guidance.strip()
                      or "Không có người khác đủ công cụ cho bước này, nên bạn tự làm "
                         "lại: đọc kỹ từng tiêu chí nghiệm thu, tra đủ nguồn cho từng "
                         "mục còn thiếu, và ghi rõ nguồn cho mỗi số liệu."),
            reason=judgement.reason,
        ))
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
    """Conclude that the assignee cannot complete the step — and decide what the
    coordinator does about it.

    First the coordinator tries to resolve it itself (`try_self_resolve`): write the
    result with its own model call, or — for a non-terminal work step — skip it with a
    gap note so the pipeline keeps going. Only when neither applies does the TASK die
    with the step: the step is marked `failed` and the task is concluded through
    `conclude_task_failed`, so the CEO receives an honest "không làm được vì X" with
    the best finished work attached rather than silence or a fake success.
    """
    from my_crew.agent.coordinator_nodes.self_resolve import try_self_resolve
    from my_crew.agent.coordinator_nodes.stall_conclusion import conclude_task_failed

    resolved = try_self_resolve(deps, task, step, reason)
    if resolved is not None:
        return resolved
    # attempt-guarded like every other ticker-side terminal write: `step` is a snapshot
    # read at the top of this tick, so a concurrent re-reservation (a CEO's manual
    # retry, a second ticker) must make this a clean no-op rather than clobber the
    # newer attempt's row and orphan its live worker.
    if not deps.store.mark_failed(
        task.id, step.step_id, outcome_ref=step.outcome_ref, attempt_id=step.attempt_id,
        quiet=True,
    ):
        # The guard matched no row. Live-worker races are not the only way that happens:
        # a `_retry` earlier in this same decision sequence calls `reset_step_to_pending`,
        # which CLEARS attempt_id, so `step`'s snapshot then names a lease the row no
        # longer carries and the terminal write silently vanishes — leaving a `stalled`
        # task holding a `pending` step, which `retry_stalled_step` cannot rescue
        # (`_dead_steps` only matches failed/timeout) and only cancel can clear.
        # A released row has no worker to protect, so retry unguarded but pinned to the
        # status we are actually concluding from.
        if not deps.store.mark_failed_if_pending(task.id, step.step_id):
            logger.warning(
                "team-tick: give_up could not terminate step %s/%s — it is neither on "
                "attempt %s nor pending; leaving it as-is",
                task.id, step.step_id, step.attempt_id or "<none>",
            )
    return conclude_task_failed(
        deps, task,
        f"Việc '{task.title}' KHÔNG LÀM ĐƯỢC: bước '{step.title}' — {reason}.",
        step=step, event_kind="gave_up", reflect_outcome="stalled",
        reflect_detail=f"gave up on step '{step.title}': {reason}",
        action="gave_up", detail=f"{step.step_id}: {reason}",
    )
