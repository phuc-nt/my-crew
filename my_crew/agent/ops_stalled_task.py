"""One-touch recovery commands for a `stalled` team task (v63).

A stalled task previously had exactly one exit: the CEO hand-writes an
`adjust_team_task` brief. These three commands cover the common cases in one chat
message each, HITL-style (decide fast, with the evidence already in the escalation):

  - `accept_stalled_result`: the work exists but the last peer review kept failing it
    (`review_rounds_exhausted`) — accept the delivered artifact as-is. Implemented by
    overwriting the failing round's verdict artifact to `passed=True` (with an explicit
    CEO-acceptance note, the original failures kept for the record) and reopening the
    task: the next tick reads the now-passing verdict, the normal all-done → aggregate
    path delivers. No engine change — the ticker rule stays the only DAG mutator.
  - `retry_stalled_step`: one more deliberate attempt. Review-exhausted case → mint ONE
    extra rework round (past `MAX_REVIEW_ROUNDS`, on purpose, with the CEO's note added
    to the rework brief); dead-step case (`failed`/`timeout`) → reset the dead rows to
    `pending` for a fresh dispatch. Each invocation buys exactly one round — a task that
    fails again re-stalls; there is no loop.
  - `drop_stalled_step`: give up on a dead step — mark it done with a placeholder
    artifact (review flag cleared, see `mark_step_dropped`) so the rest of the DAG can
    finish without it. Refused for the PIC's terminal step (dropping the synthesis step
    would deliver a task with no final result — that needs a real `adjust_team_task`).

All three touch ONLY store columns + local artifacts (never an external write), verify
`status == "stalled"` first, and reopen the task by setting status back to `open` so the
coordinator ticker picks it up on its normal cadence.
"""

from __future__ import annotations

import logging

from my_crew.runtime.team_task_paths import team_tasks_db_path, team_tasks_root
from my_crew.runtime.team_task_store import TeamStep, TeamTask, TeamTaskStore
from my_crew.tools.search_result_formatter import scan_for_injection_markers

logger = logging.getLogger(__name__)

#: Placeholder a dropped step delivers to its dependents' handoff readers. Worded as a
#: hard directive, not a neutral note (v64, UAT-found): a summarizing step that read the
#: old bland "(bước bị bỏ qua)" filled the gap with FABRICATED measurements presented as
#: real. The work-step SYSTEM prompt carries the same rule (`team_task_prompt._SYSTEM`)
#: since the content wrapper marks handoff text as data-not-instructions.
#: Stable prefix of that placeholder — the aggregate step detects a dropped step by
#: this prefix (not the full text) so wording tweaks after the prefix don't break the
#: "hoàn thành với khoảng trống" delivery header.
DROP_PLACEHOLDER_PREFIX = "KHÔNG CÓ KẾT QUẢ — bước này đã bị chủ động bỏ qua"

#: Line prefix carrying WHY a step was skipped (coordinator give_up converted to a
#: skip). The aggregate parses this line back out to name the gap in the delivery.
DROP_REASON_PREFIX = "Lý do bỏ qua (phán quyết điều phối): "

_DROPPED_RESULT_TEXT = (
    DROP_PLACEHOLDER_PREFIX + ", không tạo ra bất kỳ dữ liệu "
    "hay số liệu nào. Bước sau TUYỆT ĐỐI không được suy diễn/ước lượng/bịa kết quả "
    "thay cho bước này; nếu sản phẩm cuối phụ thuộc nó, phải ghi rõ 'thiếu dữ liệu "
    "từ bước bị bỏ qua'."
)

#: Line prefix opening the salvaged draft section inside a drop placeholder. The step
#: being dropped usually DID produce something — the worker's `_deliver` writes
#: `result_text` to the artifact even when the self-check fails (that is how the row
#: reached `needs_decision`), and the drop used to overwrite that draft with the bare
#: placeholder. Measured across lanes9-12: 8/10 dropped steps had a real draft thrown
#: away, and every downstream consumer then starved (team matrix delivered a 0/9-cell
#: table). Keeping the draft under this marker lets dependents work with labeled
#: unverified content instead of nothing.
SALVAGE_DRAFT_PREFIX = "BẢN NHÁP CHƯA ĐẠT SOÁT CỦA BƯỚC NÀY (dùng phải dán nhãn):"

_DROPPED_WITH_DRAFT_TEXT = (
    DROP_PLACEHOLDER_PREFIX + " vì không qua được kiểm tra chất lượng — nhưng bản "
    "nháp cuối của nó được giữ lại bên dưới. Bước sau ĐƯỢC dùng nội dung nháp, với "
    "điều kiện dán nhãn 'dữ liệu chưa qua soát' ngay cạnh mọi số liệu/kết luận lấy "
    "từ nháp; TUYỆT ĐỐI không bịa thêm gì ngoài những điều nháp đã ghi."
)

#: Ceiling for the salvaged draft carried inside the placeholder — same spirit as the
#: task-level `_MAX_SALVAGE_CHARS` (6000) one shape up, smaller because this text rides
#: every dependent's handoff prompt, not just the final delivery.
_MAX_DRAFT_SALVAGE_CHARS = 4000

#: Below this, a "draft" is more likely an error string or a refusal stub than content
#: worth handing downstream — the bare placeholder is more honest.
_MIN_DRAFT_SALVAGE_CHARS = 200


def _cost_cap_note_marker() -> str:
    """The literal, format-independent head of `COST_CAP_GAP_NOTE`.

    Derived from the constant rather than copied so a reword cannot leave this scan
    matching a string the guard no longer emits — the note is the only thing standing
    between a capped step and a dependent that believes nothing was produced.
    """
    from my_crew.runtime_backends.loop_cost_guard import COST_CAP_GAP_NOTE

    return COST_CAP_GAP_NOTE.split("{", 1)[0]


def _carries_cost_cap_note(text: str) -> bool:
    """Did the spend ceiling write this text, rather than a failing tool or a refusal?"""
    return _cost_cap_note_marker() in text


def _salvageable_draft(artifact: dict | None) -> str:
    """The dropped step's own prior draft worth keeping, or "" for the bare placeholder.

    Guards: no artifact / empty text (a dead `failed`/`timeout` row may never have
    delivered), an already-dropped placeholder (a re-drop must not nest placeholders),
    stub-length text (see `_MIN_DRAFT_SALVAGE_CHARS`), and text that trips the
    injection scan. The scan guard exists because the dependents' handoff wraps this
    artifact through `format_internal_content`, which quarantines the WHOLE text on
    one marker hit — attaching such a draft would erase even the placeholder and
    reason for every dependent (measured live in the first salvage bench: a draft
    containing the benign phrase 'bỏ qua yêu cầu tìm kiếm' blanked the entire
    handoff). A draft that cannot ride is worse than no draft.
    """
    text = str((artifact or {}).get("result_text") or "").strip()
    if text.startswith(DROP_PLACEHOLDER_PREFIX):
        return ""
    # The length floor filters error strings and refusal stubs, which are short BECAUSE
    # they carry no content. A cost-cap note is short for the opposite reason: the ceiling
    # stopped the loop before it could produce prose, and the note is then the entire
    # result_text. Measured live (L1): 191 chars against a floor of 200, so the one
    # sentence explaining WHY the work is incomplete was dropped nine characters short,
    # and every dependent saw "no result" with no reason. The note is code-authored and
    # never a stub, so it earns its keep at any length.
    if len(text) < _MIN_DRAFT_SALVAGE_CHARS and not _carries_cost_cap_note(text):
        return ""
    if scan_for_injection_markers(text):
        return ""
    if len(text) > _MAX_DRAFT_SALVAGE_CHARS:
        cut = text.rfind("\n", 0, _MAX_DRAFT_SALVAGE_CHARS)
        text = text[:cut if cut > 0 else _MAX_DRAFT_SALVAGE_CHARS].rstrip()
        text += "\n(… nháp dài hơn, đã cắt bớt)"
    return text


def drop_step_with_placeholder(
    store: TeamTaskStore, task: TeamTask, step: TeamStep, *, reason: str = "",
) -> bool:
    """Mark one step dropped and write its honest placeholder artifact.

    The single primitive both drop paths share: the CEO's `drop_stalled_step` (no
    reason — the placeholder text is the whole message) and the coordinator's
    skip-with-gap on a non-terminal give_up (reason = the stuck judge's ruling, so
    dependents and the final delivery can name WHY the gap exists). Returns False when
    the attempt-guarded store write matched no row — the caller decides what a refused
    drop means (skip the step in a batch, or fall back to a full give_up).
    """
    from my_crew.agent.team_task_artifact import read_step_artifact, write_step_artifact

    # Read BEFORE the store write: the placeholder below overwrites this artifact, and
    # what it currently holds is the step's last failed draft (the worker writes
    # `result_text` even on a failed self-check — that is how the row got here).
    draft = _salvageable_draft(read_step_artifact(team_tasks_root(), task.id, step.seq))
    outcome_ref = f"team-tasks/{task.id}/step-{step.seq}.json"
    if not store.mark_step_dropped(
        task.id, step.step_id, outcome_ref=outcome_ref, attempt_id=step.attempt_id,
    ):
        return False
    text = _DROPPED_WITH_DRAFT_TEXT if draft else _DROPPED_RESULT_TEXT
    # The reason is one LINE by contract: the aggregate finds it back with a
    # line-prefix scan, so a multiline judge verdict would silently lose everything
    # after its first newline. Collapse whitespace instead of trusting the LLM.
    # A reason tripping the injection scan is dropped for the same reason a draft is
    # (see `_salvageable_draft`): one marker hit quarantines the whole artifact in
    # every dependent's handoff, losing far more than the reason line.
    reason_line = " ".join(reason.split())
    if reason_line and scan_for_injection_markers(reason_line):
        reason_line = ""
    if reason_line:
        text = f"{text}\n{DROP_REASON_PREFIX}{reason_line}"
    if draft:
        # Draft LAST, after the placeholder + reason lines: the placeholder prefix
        # must stay the first byte (aggregate detects drops via startswith) and the
        # reason must stay a clean line-prefix hit before free-form draft text.
        text = f"{text}\n{SALVAGE_DRAFT_PREFIX}\n{draft}"
    write_step_artifact(
        team_tasks_root(), task.id, step.seq,
        {"result_text": text, "version": step.attempt_id or "ceo-drop",
         "status": "done"},
    )
    return True


class _StalledTaskContext:
    """Store + task pair with the shared `status == "stalled"` precondition applied."""

    def __init__(self, task_id: str) -> None:
        self.store = TeamTaskStore(team_tasks_db_path())
        task = self.store.get(task_id.strip())
        if task is None:
            self.store.close()
            raise ValueError(f"không tìm thấy việc đội `{task_id.strip()}`")
        if task.status != "stalled":
            self.store.close()
            raise ValueError(
                f"việc `{task.id}` đang ở trạng thái '{task.status}', không phải "
                "'stalled' — lệnh này chỉ dùng cho việc bị dừng chờ xử lý"
            )
        self.task = task

    def close(self) -> None:
        self.store.close()


def _latest_failed_review(task: TeamTask) -> tuple[TeamStep, TeamStep, dict] | None:
    """(review_step, content_step, verdict) of a content step whose NEWEST review
    failed — the row that stalled a `review_rounds_exhausted` task. None when the
    stall came from something else (dead step, cost cap, plan-hash mismatch).

    Only each content step's newest review row counts (review-found v63 H2): a step
    whose history is "round 0 failed → rework → round 1 passed" is FINE — returning
    its long-superseded round-0 verdict would misdiagnose a dead-step stall as a
    review stall and send accept/retry at content that already passed."""
    from my_crew.agent.team_task_artifact import read_review_verdict_artifact

    steps_by_id = {s.step_id: s for s in task.steps}
    seen_parents: set[str] = set()
    for review in sorted(
        (s for s in task.steps if s.step_type == "review" and s.status == "done"),
        key=lambda s: s.seq, reverse=True,
    ):
        parent_id = review.parent_step_id or ""
        if parent_id in seen_parents:
            continue  # an older round of a step whose newest review was already judged
        seen_parents.add(parent_id)
        content = steps_by_id.get(parent_id)
        if content is None:
            continue
        verdict = read_review_verdict_artifact(
            team_tasks_root(), task.id, content.seq, review.review_round,
        )
        if verdict is not None and not bool(verdict.get("passed")):
            return review, content, verdict
    return None


def _dead_steps(task: TeamTask) -> list[TeamStep]:
    return [s for s in task.steps if s.status in ("failed", "timeout")]


def _is_pic_terminal(task: TeamTask, step: TeamStep) -> bool:
    """True iff `step` is the DAG's terminal synthesis step owned by the task's PIC —
    the one row `validate_pic_terminal` guarantees exists on a PIC task; dropping it
    would deliver a task with no final result."""
    if not task.pic_id or step.assigned_to != task.pic_id:
        return False
    dep_targets = {d for s in task.steps for d in s.deps}
    return step.step_id not in dep_targets


def run_accept_stalled_result(slots: dict[str, str]) -> str:
    """Accept a review-stalled task's existing deliverable and let it complete."""
    from my_crew.agent.team_task_artifact import write_review_verdict_artifact

    ctx = _StalledTaskContext(slots["task_id"])
    try:
        task = ctx.task
        found = _latest_failed_review(task)
        all_done = bool(task.steps) and all(s.status == "done" for s in task.steps)
        if found is None and not all_done:
            raise ValueError(
                f"việc `{task.id}` không dừng vì soát chéo (không có verdict trượt nào) "
                "— dùng `retry_stalled_step`/`drop_stalled_step`, hoặc chỉnh kế hoạch"
            )
        if found is not None:
            review, content, verdict = found
            # Overwrite THIS round's verdict in place: passed flips, the reviewer's
            # failures stay on record, and the acceptance note rides `notes` so the
            # final aggregate surfaces it (the passed-with-notes delivery path).
            write_review_verdict_artifact(
                team_tasks_root(), task.id, content.seq, review.review_round,
                {**verdict, "passed": True,
                 "notes": [*list(verdict.get("notes") or []),
                           "CEO chấp nhận kết quả này dù soát chéo chưa đạt."],
                 "ceo_override": True},
            )
        ctx.store.reopen_stalled(task.id)
        detail = (
            f"bước '{found[1].title}' được chấp nhận nguyên trạng" if found is not None
            else "mọi bước đã xong"
        )
        return (f"Đã chấp nhận kết quả của việc `{task.id}` ({detail}) — "
                "đội sẽ tổng hợp và gửi bản chốt trong ít phút.")
    finally:
        ctx.close()


def run_retry_stalled_step(slots: dict[str, str]) -> str:
    """Buy the stalled step exactly one more attempt (rework round or re-dispatch)."""
    from my_crew.agent.team_task_artifact import write_review_verdict_artifact

    note = (slots.get("note") or "").strip()
    ctx = _StalledTaskContext(slots["task_id"])
    try:
        task = ctx.task
        found = _latest_failed_review(task)
        if found is not None:
            review, content, verdict = found
            rework_id = f"{content.step_id}-rework-{review.review_round}"
            if any(s.step_id == rework_id for s in task.steps):
                raise ValueError(
                    f"vòng thử lại {review.review_round} của bước '{content.title}' đã "
                    "tồn tại — chờ nó chạy xong hoặc chỉnh kế hoạch"
                )
            if note:
                # The rework brief IS the verdict artifact's result_text (deps-handoff
                # mechanism) — the CEO's steer belongs inside it, not in a title.
                write_review_verdict_artifact(
                    team_tasks_root(), task.id, content.seq, review.review_round,
                    {**verdict,
                     "result_text": f"{verdict.get('result_text') or ''}"
                                    f"\n\nGhi chú của CEO cho lần sửa này:\n{note}"},
                )
            # Same deps shape as `review_insert._insert_rework_step`: the review brief
            # first, then the content step's own source deps — a reworker that can see
            # the defect list but not the data cannot fix a data defect.
            retry_deps = [review.step_id] + [d for d in content.deps if d != review.step_id]
            # The rework inherits the parent's web-lookup declaration (same as
            # `review_insert._insert_rework_step`): without it the row reads as
            # needing nothing, and a later reassign could legally hand a live
            # data-collection redo to an agent with no search tool.
            ctx.store.insert_step(task.id, {
                "step_id": rework_id, "title": content.title,
                "assigned_to": content.assigned_to, "deps": retry_deps,
                "step_type": "rework", "parent_step_id": content.step_id,
                "review_round": review.review_round,
            }, needs_web=content.needs_web, needs_mail=content.needs_mail)
            ctx.store.reopen_stalled(task.id)
            return (f"Đã mở thêm MỘT vòng sửa cho bước '{content.title}' của việc "
                    f"`{task.id}`" + (" (kèm ghi chú của CEO)." if note else "."))

        dead = _dead_steps(task)
        if not dead:
            raise ValueError(
                f"việc `{task.id}` không có bước chết hay verdict trượt để thử lại — "
                "xem `report_task` hoặc chỉnh kế hoạch"
            )
        reset, moved = [], []
        for s in dead:
            replacement = _dead_step_replacement(s)
            if replacement:
                ctx.store.reassign_step(task.id, s.step_id, replacement)
                moved.append(f"'{s.title}' → {replacement}")
            if ctx.store.reset_step_to_pending(task.id, s.step_id, attempt_id=s.attempt_id):
                reset.append(s.title)
        if not reset:
            raise ValueError(f"không đặt lại được bước nào của việc `{task.id}` — thử lại sau")
        ctx.store.reopen_stalled(task.id)
        names = ", ".join(f"'{t}'" for t in reset)
        moved_note = f" (đổi người: {', '.join(moved)})" if moved else ""
        return (f"Đã đặt lại {len(reset)} bước ({names}) của việc `{task.id}` để chạy lại "
                f"từ đầu{moved_note}.")
    finally:
        ctx.close()


def _dead_step_replacement(step: TeamStep) -> str:
    """A different assignee who holds the tools a dead `needs_web`/`needs_mail` step
    requires.

    A dead-step reset that keeps an assignee who CANNOT search dies the same way on
    the next attempt — the deterministic loop that burned the autopilot ladder in
    round 7. Only fires when the step declares the need and its current holder
    fails the live capability probe; picks the first assignable capable colleague
    (registry order — deterministic), and returns "" (keep the current assignee)
    when nobody qualifies — an honest same-agent retry beats an equally-doomed swap.

    A step declaring BOTH needs one agent holding both: swapping to a colleague who
    fixes only half leaves it just as dead, so the candidate must clear every
    capability the step declared.
    """
    from my_crew.agent.team_task_roster import agent_mail_capable, assignable_staff
    from my_crew.runtime.team_tick_runner import agent_web_capable

    def _capable(agent_id: str) -> bool:
        if step.needs_web and not agent_web_capable(agent_id):
            return False
        return not (step.needs_mail and not agent_mail_capable(agent_id))

    if not (step.needs_web or step.needs_mail) or _capable(step.assigned_to):
        return ""
    for agent_id, _domain in assignable_staff():
        if agent_id != step.assigned_to and _capable(agent_id):
            return agent_id
    return ""


def run_drop_stalled_step(slots: dict[str, str]) -> str:
    """Give up on a dead step so the rest of the DAG can finish without it."""
    ctx = _StalledTaskContext(slots["task_id"])
    try:
        task = ctx.task
        dead = _dead_steps(task)
        if not dead:
            hint = (
                "việc dừng vì soát chéo — dùng `accept_stalled_result` để chấp nhận kết quả"
                if _latest_failed_review(task) is not None
                else "không có bước chết nào để bỏ — xem `report_task` hoặc chỉnh kế hoạch"
            )
            raise ValueError(f"việc `{task.id}`: {hint}")
        blocked = [s for s in dead if _is_pic_terminal(task, s)]
        if blocked:
            raise ValueError(
                f"bước '{blocked[0].title}' là bước chốt cuối của PIC ({task.pic_id}) — "
                "bỏ nó thì việc không còn kết quả chốt; hãy chỉnh kế hoạch thay vì bỏ"
            )
        dropped: list[str] = []
        for s in dead:
            if drop_step_with_placeholder(ctx.store, task, s):
                dropped.append(s.title)
        if not dropped:
            raise ValueError(f"không bỏ được bước nào của việc `{task.id}` — thử lại sau")
        ctx.store.reopen_stalled(task.id)
        names = ", ".join(f"'{t}'" for t in dropped)
        return (f"Đã bỏ {len(dropped)} bước kẹt ({names}) của việc `{task.id}` — "
                "các bước còn lại sẽ tiếp tục.")
    finally:
        ctx.close()


def _require_stalled(slots: dict[str, str]) -> None:
    """A preview must only promise what run can deliver: same existence + stalled
    check as the run path, so a bad task id is refused at preview instead of
    surviving to an optimistic "Mình sẽ..." and only failing at confirm."""
    _StalledTaskContext(str(slots.get("task_id") or "")).close()


def preview_accept_stalled_result(slots: dict[str, str]) -> str:
    _require_stalled(slots)
    return (f"Mình sẽ CHẤP NHẬN kết quả hiện có của việc `{slots.get('task_id', '')}` "
            "(bỏ qua verdict soát chéo chưa đạt) và để đội tổng hợp bản chốt.\n"
            "Xác nhận? (trả lời: xác nhận / huỷ)")


def preview_retry_stalled_step(slots: dict[str, str]) -> str:
    _require_stalled(slots)
    return (f"Mình sẽ mở thêm ĐÚNG MỘT lượt thử lại cho bước đang kẹt của việc "
            f"`{slots.get('task_id', '')}`"
            + (" kèm ghi chú của CEO" if (slots.get("note") or "").strip() else "")
            + ".\nXác nhận? (trả lời: xác nhận / huỷ)")


def preview_drop_stalled_step(slots: dict[str, str]) -> str:
    _require_stalled(slots)
    return (f"Mình sẽ BỎ (các) bước chết của việc `{slots.get('task_id', '')}` — phần việc "
            "còn lại chạy tiếp, kết quả cuối sẽ thiếu phần của bước bị bỏ.\n"
            "Xác nhận? (trả lời: xác nhận / huỷ)")
