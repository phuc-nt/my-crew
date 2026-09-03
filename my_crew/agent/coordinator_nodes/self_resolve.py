"""What the coordinator does with a step nobody else could finish: do it itself, or
route around it — and only then let the task die.

The ladder, cheapest-honest first:

1. `_self_do_step` — the coordinator writes the step's result with its own model
   call, from the same handoff the worker had (CEO brief, upstream artifacts,
   acceptance criteria) plus whatever the failed attempt left behind (its draft and the
   findings against it). The row becomes `done` with `needs_review = 0` — a
   coordinator's fallback is the LAST word on the step, not a fresh draft to peer-
   review back into the loop it just broke. The aggregate names it in a code-built
   header so the CEO knows who actually wrote that part.
2. `_skip_step_with_gap` — for a non-terminal work step whose dependents can carry an
   honest hole, drop it with a placeholder artifact and keep the pipeline running.
3. `None` — the caller concludes the task with a delivered failure summary.

Why the coordinator may do work at all: the CEO's rule for this crew is that the agent
who assigns work decides the next step when a result is missing or wrong, and does
the work itself if that is what it takes to conclude. A conclusion built from the
coordinator's own best effort beats a stall that hands the CEO nothing.

Guards: no `self_do_step` collaborator (no API key ⇒ None from the factory), a task
under `require_ceo_approval` (the CEO asked for gates on this one — the coordinator
must not quietly substitute itself), and only content step types (`work`, `sprint`,
`rework`) — a review row has no deliverable to write, and a sub/gather row's parent
owns the fan-out contract.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from my_crew.agent.coordinator_graph import CoordinatorDeps, TickResult
    from my_crew.runtime.team_task_steps import TeamStep
    from my_crew.runtime.team_task_store import TeamTask

logger = logging.getLogger(__name__)

#: `version` stamped on an artifact the coordinator wrote in a worker's place when the
#: row carries no attempt lease to inherit.
SELF_DO_VERSION = "coordinator-self"

#: Artifact key marking a coordinator-written result; the value is the reason the
#: assignee's attempt did not finish. The aggregate builds its header from it.
COORDINATOR_FALLBACK_KEY = "coordinator_fallback"

_SELF_DO_STEP_TYPES = frozenset({"work", "sprint", "rework"})

#: How much of the failed attempt's draft rides into the coordinator's handoff. A
#: draft is a starting point, not the deliverable — a long one is cut at a line
#: boundary rather than crowding out the brief and upstream context.
_MAX_PRIOR_DRAFT_CHARS = 6000
_MAX_BRIEF_CHARS = 2000

_ROLE_NOTE = (
    "VAI TRÒ: bạn là điều phối viên, tự làm bước này thay người được giao vì họ không "
    "hoàn thành. Bạn KHÔNG có công cụ tìm kiếm hay dữ liệu mới: chỉ dùng bối cảnh dưới "
    "đây và kiến thức nền; chỗ nào không có nguồn kiểm chứng phải ghi rõ 'chưa xác "
    "minh' thay vì bịa số liệu. Viết thẳng kết quả của bước, không viết lời dẫn."
)


def _is_skippable(task: TeamTask, step: TeamStep) -> bool:
    """May this stuck step be skipped (dropped with a gap note) instead of killing
    the task?

    Measured (bench lanes5-8): every team-lane stall hit `_give_up` on the FIRST
    research step, so 0/5 rounds ever delivered anything — the all-or-nothing pipeline
    was the team lane's whole failure mode. A non-terminal step's gap can ride the
    handoff honestly (the placeholder text forbids downstream fabrication), so the
    task should degrade and continue instead of dying.

    Deliberately narrow: plain `work` steps only. A terminal step (no other content
    step consumes it) IS the deliverable — skipping it delivers nothing, so it keeps
    the real give_up + salvage. Review/rework rows are excluded because a rework
    REPLACES its parent's artifact: a placeholder at the rework's seq would leave the
    parent's rejected content as the surviving handoff, delivering exactly what the
    review refused. And there must be at least one other live step left — skipping the
    only remaining work just delays the same conclusion by one tick.
    """
    if step.step_type != "work":
        return False
    content_dep_targets = {
        d for s in task.steps if s.step_type in ("work", "sprint") for d in s.deps
    }
    if step.step_id not in content_dep_targets:
        return False  # terminal: nothing downstream consumes it — it IS the delivery
    # `needs_decision` counts as live: a stuck sibling may itself be skipped or
    # resumed on its own tick (same liveness set the dispatcher uses) — two stuck
    # steps must not talk each other into killing a task the skip path could save.
    return any(
        s.step_id != step.step_id
        and s.status in ("pending", "running", "awaiting_approval",
                         "waiting_clarify", "needs_decision")
        for s in task.steps
    )


def _skip_step_with_gap(
    deps: CoordinatorDeps, task: TeamTask, step: TeamStep, reason: str,
) -> TickResult | None:
    """Convert a non-terminal give_up ruling into a skip: placeholder artifact with
    the judge's reason, step dropped, task keeps running. Returns None when the step
    must not (or could not) be skipped — the caller then falls through to the real
    give_up. A refused store write (attempt guard matched no row) also returns None:
    the legacy path's pending-pinned fallback already knows how to terminate safely.
    """
    from my_crew.agent.coordinator_graph import TickResult, _reflect_safely
    from my_crew.agent.ops_stalled_task import drop_step_with_placeholder

    if not _is_skippable(task, step):
        return None
    if not drop_step_with_placeholder(deps.store, task, step, reason=reason):
        # Refused write: this snapshot's attempt lease is stale. Re-read before
        # falling back — if the row is already `done`, a CONCURRENT decider (their
        # tick overlapped ours across the judge LLM call) skipped it first, and the
        # legacy give_up would stall a task whose pipeline is validly running. The
        # drop clears attempt_id, so acknowledging the sibling's skip is the only
        # correct move. Any other status means a genuine reset/reassign happened:
        # fall through to the legacy path, whose pending-pinned fallback knows how
        # to terminate safely.
        fresh = deps.store.get_step(task.id, step.step_id)
        if fresh is not None and fresh.status == "done":
            logger.info(
                "team-tick: skip-with-gap on %s/%s already done by a concurrent "
                "decider — acknowledging", task.id, step.step_id,
            )
            return TickResult(
                task_id=task.id, action="step_skipped",
                detail=f"{step.step_id}: đã bỏ qua bởi phiên điều phối song song",
            )
        logger.warning(
            "team-tick: skip-with-gap on %s/%s refused by attempt guard — falling "
            "back to give_up", task.id, step.step_id,
        )
        return None
    note = (
        f"Bước '{step.title}' bỏ qua vì {reason} — đội chạy tiếp các bước còn lại, "
        "kết quả cuối sẽ ghi rõ khoảng trống này."
    )
    deps.escalate(task, step, "stuck", note)
    _reflect_safely(deps, task, "stuck", f"skipped step '{step.title}': {reason}")
    return TickResult(
        task_id=task.id, action="step_skipped",
        detail=f"{step.step_id}: {reason}"[:80],
    )


def _prior_attempt_block(task: TeamTask, step: TeamStep) -> str:
    """The failed attempt's own draft and the findings against it, when the artifact
    still holds them. A `needs_decision` row always has one (it produced a real
    artifact that failed its criteria); a `failed`/`timeout` row usually does not."""
    from my_crew.agent.ops_stalled_task import DROP_PLACEHOLDER_PREFIX
    from my_crew.agent.team_task_artifact import read_step_artifact
    from my_crew.runtime.team_task_paths import team_tasks_root

    artifact = read_step_artifact(team_tasks_root(), task.id, step.seq) or {}
    text = str(artifact.get("result_text") or "").strip()
    if text.startswith(DROP_PLACEHOLDER_PREFIX):
        text = ""
    failures = [
        str(f).strip()
        for f in (artifact.get("failures") or artifact.get("check_failures") or [])
        if str(f).strip()
    ]
    parts: list[str] = []
    if failures:
        parts.append(
            "ĐIỂM CHƯA ĐẠT Ở LẦN LÀM TRƯỚC (phải sửa cho bằng được):\n"
            + "\n".join(f"- {f}" for f in failures[:10])
        )
    if text:
        if len(text) > _MAX_PRIOR_DRAFT_CHARS:
            cut = text.rfind("\n", 0, _MAX_PRIOR_DRAFT_CHARS)
            text = text[: cut if cut > 0 else _MAX_PRIOR_DRAFT_CHARS].rstrip()
            text += "\n(… nháp dài hơn, đã cắt bớt)"
        parts.append(f"BẢN NHÁP CỦA LẦN LÀM TRƯỚC (dùng làm điểm xuất phát):\n{text}")
    return "\n\n".join(parts)


def _build_self_do_handoff(task: TeamTask, step: TeamStep, reason: str) -> str:
    """The same context the worker had, plus what the coordinator knows about why
    the worker did not finish. Upstream artifacts are read through the worker's own
    deps-aware reader so a review dep and a fan-in read exactly as they would for a
    fresh attempt; a read failure degrades to "no upstream" rather than blocking the
    fallback — the brief and criteria alone still describe the step."""
    from my_crew.tools.search_result_formatter import truncate_preserving_delimiters

    parts = [
        _ROLE_NOTE,
        f"Lý do người được giao không hoàn thành: {reason}",
        "YÊU CẦU GỐC CỦA CEO (toàn việc — bám sát chủ thể nêu ở đây):\n"
        + truncate_preserving_delimiters(task.original_request or "", _MAX_BRIEF_CHARS),
    ]
    try:
        from my_crew.agent.team_task_graph import _read_deps_handoff
        from my_crew.runtime.team_task_paths import team_tasks_root

        upstream = _read_deps_handoff(
            team_tasks_root(), task.id, tuple(step.deps), cap_dep_chars=True,
        )
    except Exception:  # noqa: BLE001 — upstream is context, not a precondition
        logger.warning(
            "team-tick: could not read upstream handoff for self-do %s/%s",
            task.id, step.step_id, exc_info=True,
        )
        upstream = ""
    if upstream.strip():
        parts.append(f"KẾT QUẢ CÁC BƯỚC TRƯỚC:\n{upstream.strip()}")
    if (step.acceptance or "").strip():
        parts.append(f"TIÊU CHÍ NGHIỆM THU:\n{step.acceptance.strip()}")
    prior = _prior_attempt_block(task, step)
    if prior:
        parts.append(prior)
    return "\n\n".join(parts)


def _append_self_do_event(task: TeamTask, step: TeamStep) -> None:
    """Room mirror of the fallback, same `step_status` shape the worker posts on its
    own `done` — best-effort, the store row is the truth."""
    try:
        from my_crew.runtime.office_room_append import append_office_event, room_for_task

        append_office_event(
            room_for_task(task.id), author="coordinator", kind="step_status",
            body={"task_title": task.title, "step_title": step.title,
                  "status": "done", "assigned_to": "coordinator"},
            also_office=True,
        )
    except Exception:  # noqa: BLE001 — a missed room line never blocks the step
        logger.warning("team-tick: self-do room event failed for %s", task.id, exc_info=True)


def keeps_planned_review(deps: CoordinatorDeps, task: TeamTask) -> bool:
    """Whether a coordinator write over a step must leave its planned review flag up.

    On a plan routed as do+review the CEO asked for an independent reader of the
    deliverable. Whatever settles the step in the coordinator's hands — a stuck
    judgement, or the coordinator writing the text itself — is not that reader, so
    the flag stays and `maybe_insert_review` still mints the reviewer row. Measured
    live twice before this rule reached both paths: the flag fell, no review row was
    ever minted, and the task closed "sau soát chéo" with nobody having cross-checked.
    On every other shape the coordinator's word is the last word (dropping the flag
    is what ends the rework loop the fallback exists to end)."""
    from my_crew.agent.crew_shape import DO_REVIEW_SHAPE

    route = deps.store.get_route(task.id) or {}
    return route.get("shape") == DO_REVIEW_SHAPE


def _self_do_step(
    deps: CoordinatorDeps, task: TeamTask, step: TeamStep, reason: str,
) -> TickResult | None:
    """The coordinator writes the step's result itself. None ⇒ not attempted or not
    usable (no collaborator, guarded task/step type, model returned nothing, store
    write refused) — the caller moves down the ladder. On a do+review plan the
    written step keeps its review flag (`keeps_planned_review`)."""
    from my_crew.agent.coordinator_graph import TickResult, _reflect_safely
    from my_crew.agent.team_task_artifact import write_step_artifact
    from my_crew.runtime.team_task_paths import team_tasks_root

    if deps.self_do_step is None:
        return None
    if task.require_ceo_approval or step.step_type not in _SELF_DO_STEP_TYPES:
        return None
    try:
        outcome = deps.self_do_step(task, step, _build_self_do_handoff(task, step, reason))
    except Exception:  # noqa: BLE001 — a failed fallback is "not attempted", never a crash
        logger.exception("team-tick: coordinator self-do raised for %s/%s", task.id, step.step_id)
        return None
    if not outcome:
        return None
    text, cost_usd = outcome
    text = (text or "").strip()
    if not text:
        return None
    version = step.attempt_id or SELF_DO_VERSION
    write_step_artifact(
        team_tasks_root(), task.id, step.seq,
        {"status": "done", "result_text": text, "version": version,
         "attempt_id": version, "self_check_failed": False,
         COORDINATOR_FALLBACK_KEY: " ".join(reason.split())},
    )
    if not deps.store.mark_done_by_coordinator(
        task.id, step.step_id,
        outcome_ref=f"team-tasks/{task.id}/step-{step.seq}.json", cost_usd=cost_usd,
        attempt_id=step.attempt_id, keep_review=keeps_planned_review(deps, task),
    ):
        logger.warning(
            "team-tick: self-do on %s/%s refused by the store guard — falling through",
            task.id, step.step_id,
        )
        return None
    _append_self_do_event(task, step)
    deps.escalate(
        task, step, "stuck",
        f"Điều phối tự làm bước '{step.title}' vì {reason} — đội chạy tiếp; kết quả "
        "cuối sẽ ghi rõ phần này do điều phối viết.",
    )
    _reflect_safely(deps, task, "stuck", f"coordinator did step '{step.title}': {reason}")
    return TickResult(
        task_id=task.id, action="self_did", detail=f"{step.step_id}: {reason}"[:80],
    )


def try_self_resolve(
    deps: CoordinatorDeps, task: TeamTask, step: TeamStep, reason: str,
) -> TickResult | None:
    """Self-do, then skip-with-gap; None when neither applied and the caller must
    conclude the task. Self-do goes first because a real result beats an honest hole
    — the gap is the fallback for when the coordinator cannot (or may not) write one.
    """
    done = _self_do_step(deps, task, step, reason)
    if done is not None:
        return done
    return _skip_step_with_gap(deps, task, step, reason)
