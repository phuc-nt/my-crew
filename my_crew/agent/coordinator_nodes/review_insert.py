"""Peer-review/rework insert rule for the coordinator ticker (M32) — split out of
`tick_actions.py` to keep that module under the repo's ~200 LOC guideline (this rule
is also a genuinely separate concern: it decides WHAT dynamic rows to mint, `tick_actions`
decides WHICH step to poll/dispatch next).

Called from `coordinator_graph._act_on_task`, once per tick, BEFORE the normal
ready/poll/aggregate dispatch decisions — a `done` content/review/rework step is
inspected exactly once per tick for whether it needs a follow-up row minted. This is a
TICKER RULE: every decision here is plain Python over store columns, never an LLM call
— the review verdict (an LLM call) already happened inside the review-step's own worker
run (`review_graph.run_review_step`); this module only reacts to its STORED verdict.

Three sub-rules, each independently idempotent (checked via "does a child row already
exist" before minting one) so re-running this on the SAME already-handled step across
multiple ticks is always a safe no-op:

  1. A `work` step (`needs_review=True`) reaches `done` with no review-step child yet
     -> mint one (`pick_reviewer`; `None` -> skip + room event, never stall).
  2. A `review` step reaches `done` -> read its verdict artifact:
       - `passed` -> nothing to do, the DAG's normal `next_pending_step`/aggregate path
         takes it from here (the review step itself has no downstream dep in the
         confirmed DAG, so no other step is unblocked by it directly — it exists only
         to gate whether a rework is needed).
       - "needs_rework" AND `review_round < MAX_REVIEW_ROUNDS` -> mint a rework-step
         (same original author, carries prior output + failures).
       - "needs_rework" AND `review_round >= MAX_REVIEW_ROUNDS` -> the chain ENDS with
         no further mint: the content is done, so the task delivers normally and the
         aggregate surfaces the unresolved objections as a deterministic "Soát chéo
         chưa đạt" header (`team_tick_collaborators`). Stalling here instead was the
         pre-lanes10 behaviour and it turned reviewer flip-flop (ambiguous ground
         truth, verdict oscillating each round) into a task that delivered NOTHING
         despite every content step being done — measured 3/4 stalled cases in
         lanes9b. Cùng nhánh đó còn một trần TẦNG TASK
         (`_task_review_budget_exhausted`): tổng row review+rework của cả task vượt
         ngân sách -> cũng kết thúc chuỗi như trên dù round của bước này chưa cạn.
       - verdict artifact missing/stale (`stale_artifact`, the reviewed content re-ran
         since this review was queued) -> mint a FRESH review-step (round unchanged) so
         a new reviewer run grades the CURRENT artifact instead of leaving the task stuck
         on a review that graded content nobody will ever see delivered.
  3. A `rework` step reaches `done` -> mint a NEW review-step for it (`review_round + 1`)
     — the rework's own freshly-written artifact becomes the next round's locked target.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING

from my_crew.runtime.office_room_append import append_office_event, room_for_task
from my_crew.runtime.team_task_steps import is_content_step, is_dropped_step
from my_crew.runtime.team_task_store import TeamStep, TeamTask

if TYPE_CHECKING:
    from my_crew.agent.coordinator_graph import CoordinatorDeps

logger = logging.getLogger(__name__)

#: Peer review is capped at this many rework rounds (`review_round` col, 0-indexed) —
#: round `MAX_REVIEW_ROUNDS` still failing means the ticker stops minting (no 3rd
#: rework attempt — R "oscillation rework" in the phase's risk register) and the task
#: delivers with the reviewer's unresolved objections quoted in the summary.
MAX_REVIEW_ROUNDS = 2

#: Trần TẦNG TASK cho tổng số row review+rework đã mint — chốt chặn thứ hai bên trên
#: trần theo-từng-bước ở trên. Trần theo bước không thấy được tổng: một task nhiều bước
#: có thể hợp lệ đốt hàng chục row soát/sửa mà không bước nào chạm trần riêng của nó
#: (đo được trong nghiệm thu: task 6 bước mint 11 review + 7 rework, tất cả đúng luật).
#: Ngân sách = _TASK_REVIEW_LOAD_FACTOR × số bước nội dung, nhưng không bao giờ thấp
#: hơn mức một bước đơn lẻ được phép dùng trọn (3 review + 2 rework) — để task 1-2 bước
#: không bị trần task cắt sớm hơn trần bước.
_TASK_REVIEW_LOAD_FACTOR = 2


def _task_review_budget_exhausted(task: TeamTask) -> tuple[bool, int, int]:
    """(exhausted, minted, budget) — tổng row review+rework so với ngân sách tầng task."""
    minted = sum(1 for s in task.steps if s.step_type in ("review", "rework"))
    content = sum(1 for s in task.steps if is_content_step(s))
    floor = (MAX_REVIEW_ROUNDS + 1) + MAX_REVIEW_ROUNDS
    budget = max(_TASK_REVIEW_LOAD_FACTOR * content, floor)
    return minted >= budget, minted, budget


def _review_child(task: TeamTask, content_step_id: str, step_type: str) -> TeamStep | None:
    """The most-recently-inserted `step_type` child of `content_step_id`, or None.
    `steps_for_task`/`task.steps` is seq-ordered, so the LAST match is the newest round
    — needed because a 2-round review keeps BOTH round-0 and round-1 review rows (each
    verdict artifact is filed under its own round number, never overwritten)."""
    matches = [
        s for s in task.steps if s.step_type == step_type and s.parent_step_id == content_step_id
    ]
    return matches[-1] if matches else None


def effective_needs_review(task: TeamTask, step: TeamStep) -> bool:
    """The plan's `needs_review` flag adjusted by the assignee's autonomy band (v76).

    This RUNTIME gate is the ONLY thing a band may change (plan invariant, pinned by
    `test_band_autonomy_invariants`): supervised → every work step gets a review row
    regardless of the plan flag/waiver; trusted → the review the plan flagged is
    waived for INTERNAL steps — including the terminal (the v64 policy only ever
    flags terminals + external writes, so a trusted rule that spared terminals was a
    live no-op, v76 UAT finding) — EXCEPT a `sprint` step, which keeps its review ở
    mọi band vì đó là hàng rào duy nhất giữa một tiến trình đơn lẻ và bản giao cho
    CEO; an `external_write` step keeps its review no matter
    how trusted the author — a write leaving the company always gets a second pair of
    eyes. `trusted` only ever enters via the CEO's `set_band`, so this IS the CEO
    consciously relaxing the v64 terminal rule for one proven agent. normal → the
    plan flag, byte-identical to pre-v76. Reads the band via `band_for` (no store
    file ⇒ normal, broken store ⇒ supervised — fail-strict)."""
    from my_crew.runtime.band_store import BAND_SUPERVISED, BAND_TRUSTED, band_for

    # A dropped step (skip-with-gap / CEO drop) outranks every band, supervised
    # included: its artifact is a placeholder, and the drop already retired the
    # attempt lease — so a review minted over it locks version "" against an artifact
    # that keeps the pre-drop version, a mismatch no re-review can ever clear. Seen
    # live (lanes9): six stale re-reviews per skipped step until the review budget
    # stalled a task whose content steps were ALL done.
    if is_dropped_step(step):
        return False
    band = band_for(step.assigned_to)
    if band == BAND_SUPERVISED:
        return True
    flag = bool(step.needs_review)
    if (band == BAND_TRUSTED and flag
            and not bool(getattr(step, "external_write", False))
            and str(getattr(step, "step_type", "work") or "work") != "sprint"):
        # Sprint là đường zero-eyes duy nhất còn sót: một bước chạy trọn trong một
        # tiến trình, không đồng nghiệp nào đọc giữa chừng, bản giao đi thẳng đến
        # CEO. Một lượt soát chéo là con mắt thứ hai duy nhất — nên trusted không
        # miễn review cho bước sprint (không có đường zero-eyes ở bất kỳ band nào).
        return False
    return flag


def maybe_insert_review(deps: CoordinatorDeps, task: TeamTask, done_step: TeamStep) -> bool:
    """After a `work` step (`needs_review=True`) turns `done`: mint its review-step
    child if one does not already exist. Returns True iff a row was inserted (the
    caller re-reads the task before doing anything else this tick, so a stale in-memory
    `task.steps` is never dispatched against).

    A `None` reviewer (no eligible peer — 1-staff fleet, or every step's only ever had
    this one author) SKIPS review entirely: room event "bỏ qua kiểm định", the content
    step is treated as fully done, no stall — matching the phase's explicit "never
    stall on missing reviewer" contract.
    """
    # `is_content_step`, not `== "work"`: a v77 sprint step is content too, and a
    # supervised band must be able to mint its one final review row (band's only lever).
    if not is_content_step(done_step) or not effective_needs_review(task, done_step):
        return False
    if done_step.split_proposal_json:
        # v34 P4: a split parent delivered only the "Đã chia bước" notice — reviewing
        # a notice is noise; its quality gate moved to the GATHER row, which inherited
        # this step's needs_review at mint time (fanout_insert).
        return False
    if _review_child(task, done_step.step_id, "review") is not None:
        return False

    from my_crew.agent.team_task_roster import assignable_staff, pick_reviewer

    reviewer = pick_reviewer(done_step.assigned_to, assignable_staff())
    if reviewer is None:
        append_office_event(
            room_for_task(task.id), author="coordinator", kind="milestone",
            body={"task_id": task.id, "task_title": task.title, "milestone": "review_skipped",
                  "message": f"Bỏ qua kiểm định cho bước '{done_step.title}' — không có "
                             "đồng nghiệp phù hợp để soát chéo."},
            also_office=True,
        )
        return False

    # False = a concurrent tick minted it first; this tick changed nothing and must not
    # claim the tick, or the caller re-reads the task for an action that never happened.
    return _insert_review_step(deps, task, done_step, reviewer=reviewer, review_round=0)


def maybe_handle_review_done(deps: CoordinatorDeps, task: TeamTask, review_step: TeamStep) -> bool:
    """After a `review` step turns `done`: act on its verdict artifact. Returns True
    iff this tick minted a row / changed task status (caller re-reads the task before
    continuing)."""
    if review_step.step_type != "review" or review_step.parent_step_id is None:
        return False
    if is_dropped_step(review_step):
        # The CEO dropped this dead review row (`drop_stalled_step` has no step_type
        # filter): its "done" is a placeholder, so the verdict read below would come
        # back None and the re-mint branch would resurrect the exact row the CEO just
        # killed. A dropped review ends its chain.
        return False
    content_step_id = review_step.parent_step_id
    content_step = next((s for s in task.steps if s.step_id == content_step_id), None)
    if content_step is None:
        return False

    from my_crew.agent.team_task_artifact import read_review_verdict_artifact
    from my_crew.runtime.team_task_paths import team_tasks_root

    verdict = read_review_verdict_artifact(
        team_tasks_root(), task.id, content_step.seq, review_step.review_round,
    )
    if verdict is None:
        # Stale-artifact re-review (`review_graph.run_review_step` wrote nothing) OR a
        # verdict genuinely not written yet for some other reason — either way, the
        # only ticker-safe move is to mint a FRESH review-step at the SAME round so a
        # new reviewer run grades the CURRENT artifact. Idempotent: only mints once
        # (guarded by `_review_child` returning this exact row as the newest match
        # would prevent a second mint on the next tick once the fresh one exists).
        if is_dropped_step(content_step):
            # The parent was dropped AFTER this review was minted (or the review
            # predates the fix): its placeholder artifact will read stale forever.
            # Ending the chain here lets the row count as handled and the task reach
            # aggregate instead of burning the review budget on re-mints.
            logger.info(
                "review-step %s/%s: parent %s da bi bo qua (dropped) — khong mint lai "
                "review, ket thuc chuoi soat", task.id, review_step.step_id,
                content_step_id,
            )
            return False
        if _review_child(task, content_step_id, "review") is review_step:
            # `deps[0]` is `locked_on` — the exact row the lost review was grading
            # (content step at round 0, the latest rework at round >=1). Omitting it
            # made every re-mint fall back to the CONTENT step, so a round-1 re-review
            # graded the artifact the round-0 failure already rejected instead of the
            # rework that answered it.
            return _insert_review_step(
                deps, task, content_step, reviewer=review_step.assigned_to,
                review_round=review_step.review_round,
                source_step_id=review_step.deps[0] if review_step.deps else None,
            )
        return False

    if bool(verdict.get("passed")):
        return False  # normal DAG continuation — nothing more to insert.

    budget_exhausted, _minted, _budget = _task_review_budget_exhausted(task)
    if review_step.review_round >= MAX_REVIEW_ROUNDS or budget_exhausted:
        # Cap reached (per-step rounds or task-level budget): the chain ENDS, with
        # deliberately ZERO side effects. This branch re-runs on the same done row
        # every tick, so anything it did (a status write, an escalate, a reflection)
        # would repeat forever — and the pre-lanes10 alternative, stalling the task,
        # meant a reviewer flip-flopping over ambiguous ground truth could hold a
        # fully-done task hostage (lanes9b: 3/4 cases stalled at review-2-2 with all
        # content steps done). The objection still reaches the CEO: the delivery
        # aggregate reads this failed verdict — a failed review with no rework at its
        # own round or later is exactly "cap exhausted" — and prepends a deterministic
        # "Soát chéo chưa đạt" header quoting the failures. This also subsumes the
        # old v63 override guard: with no stall there is no re-stall race for a
        # CEO-override rework to lose.
        return False

    # Scoped to THIS review's own round — a prior round's rework row (e.g. round 0's,
    # already `done` and superseded by this round-1 review) must never be mistaken for
    # "round 1's rework already minted"; each round mints its own rework exactly once.
    rework_this_round = any(
        s.step_type == "rework" and s.parent_step_id == content_step_id
        and s.review_round == review_step.review_round for s in task.steps
    )
    if rework_this_round:
        return False  # rework already minted this round — avoid a double insert.
    return _insert_rework_step(
        deps, task, content_step, review_round=review_step.review_round
    )


def maybe_insert_review_after_rework(
    deps: CoordinatorDeps, task: TeamTask, rework_step: TeamStep
) -> bool:
    """After a `rework` step turns `done`: mint the NEXT round's review-step (its
    parent is the ORIGINAL content step, not the rework row itself — `review_round`
    increments so the new verdict artifact never clobbers the prior round's)."""
    if rework_step.step_type != "rework" or rework_step.parent_step_id is None:
        return False
    if is_dropped_step(rework_step):
        # Same rule as the other two gates, one row-type over: the CEO can drop a dead
        # rework row, and the next-round review would lock onto its placeholder — a
        # guaranteed-stale grade whose failure would mint yet another rework,
        # resurrecting what the drop meant to end.
        return False
    content_step_id = rework_step.parent_step_id
    content_step = next((s for s in task.steps if s.step_id == content_step_id), None)
    if content_step is None:
        return False
    next_round = rework_step.review_round + 1
    existing = _review_child(task, content_step_id, "review")
    if existing is not None and existing.review_round >= next_round:
        return False  # already minted for this round.

    from my_crew.agent.team_task_roster import assignable_staff, pick_reviewer

    reviewer = pick_reviewer(content_step.assigned_to, assignable_staff())
    if reviewer is None:
        append_office_event(
            room_for_task(task.id), author="coordinator", kind="milestone",
            body={"task_id": task.id, "task_title": task.title, "milestone": "review_skipped",
                  "message": f"Bỏ qua kiểm định vòng {next_round} cho bước "
                             f"'{content_step.title}' — không có đồng nghiệp phù hợp."},
            also_office=True,
        )
        return False
    return _insert_review_step(
        deps, task, content_step, reviewer=reviewer, review_round=next_round,
        source_step_id=rework_step.step_id,
    )


def _insert_review_step(
    deps: CoordinatorDeps, task: TeamTask, content_step: TeamStep, *, reviewer: str,
    review_round: int, source_step_id: str | None = None,
) -> bool:
    """Mint one review-step row; True when this call is the one that wrote it.

    `source_step_id` (defaults to `content_step.step_id`) is the row whose FRESH artifact
    this review locks onto — round >=1 reviews lock the latest rework's artifact, not the
    original content step's.

    `step_id` includes a `-<n>` mint-count suffix (n = how many review rows already
    exist for this content step, at ANY round) rather than JUST `-review-<round>` —
    a stale-artifact re-mint (`maybe_handle_review_done`'s "verdict is None" branch)
    inserts a SECOND review row at the SAME round as an already-`done` one, which would
    otherwise collide on `UNIQUE(task_id, step_id)`. The round number a reader cares
    about (idempotency, `review_round` column, verdict artifact filename) is unaffected
    — it lives in the `review_round` column, never parsed back out of `step_id`.

    That suffix — and every idempotency guard in this module — is computed from the
    caller's in-memory `task.steps`, which makes them correct only for ticks that do not
    overlap. The daemon runs a poke-triggered team-tick ALONGSIDE the minute cadence
    (`service.run_poked_team_tick`), and its assumption that "the step lease/DB already
    serialize real actions" does not reach here: minting a row takes no lease. Two ticks
    that both read the task before either inserts compute the SAME suffix, and the second
    INSERT hits `UNIQUE(task_id, step_id)`. Measured on a real daemon: 5 crashed ticks,
    every one this path, each right after a poke-triggered tick.

    The unique index already prevents the duplicate row, so losing the race is harmless in
    itself — what was not harmless is the exception escaping into `run_one_tick` and
    killing the WHOLE tick, discarding every other task it would have served. So the loser
    declines instead: the row it wanted exists, which is precisely the post-condition it
    was trying to establish.
    """
    locked_on = source_step_id or content_step.step_id
    mint_count = len([s for s in task.steps if s.step_type == "review"
                      and s.parent_step_id == content_step.step_id])
    step_id = f"{content_step.step_id}-review-{review_round}-{mint_count}"
    try:
        deps.store.insert_step(task.id, {
            "step_id": step_id, "title": f"Soát chéo: {content_step.title}",
            "assigned_to": reviewer, "deps": [locked_on], "step_type": "review",
            "parent_step_id": content_step.step_id, "review_round": review_round,
        })
    except sqlite3.IntegrityError:
        logger.info(
            "review row %s/%s already minted by a concurrent tick — skipping",
            task.id, step_id,
        )
        return False
    return True


def _insert_rework_step(
    deps: CoordinatorDeps, task: TeamTask, content_step: TeamStep, *, review_round: int,
) -> bool:
    """Mint one rework-step row, same original author, `deps=[review_step_id]`.
    True when this call is the one that wrote it.

    The rework brief (prior output + structured failures) is NOT assembled here — it
    already rides inside the review-step's OWN verdict artifact's `result_text` field
    (written by `review_graph.run_review_step`'s `deliver` phase, see that module's
    `_rework_handoff_text` helper). Pointing `deps` at the review-step lets the rework's
    generic `perceive` pick that brief up through the EXISTING `deps`-handoff mechanism
    (`team_task_graph._read_deps_handoff`, which this module must not modify — P1/P3 own
    that graph) — no failures list needs to be threaded through this function itself.
    """
    review_step = _review_child(task, content_step.step_id, "review")
    dep_id = review_step.step_id if review_step is not None else content_step.step_id
    step_id = f"{content_step.step_id}-rework-{review_round}"
    # The rework ALSO inherits the content step's own deps: the review artifact carries
    # the failed output + failures, but fixing "điền số liệu thật vào chỗ placeholder"
    # needs the same SOURCE data the original author had. With deps=[review] only, an
    # honest reworker sees the defect list but not the data — observed live (task
    # fde05a52f0ee): it reported "thiếu dữ liệu từ các bước trước" and degraded the
    # artifact instead of fixing it, twice, straight into the review-round cap.
    rework_deps = [dep_id] + [d for d in content_step.deps if d != dep_id]
    # Same reasoning as the inherited deps, one layer down: the rework REDOES the
    # original work, so it inherits the web grant the author had. Without it a research
    # step's rework is routed to the searchless tier and can only ask the CEO what to do
    # (observed live, task a0865653ed89: "Công cụ tìm kiếm web không khả dụng" →
    # waiting_clarify) — a fix round that cannot re-fetch its own sources is not a fix
    # round. Same argument v74 already accepted for runtime-split subs.
    #
    # The `rework_this_round` guard upstream reads the caller's in-memory snapshot, so it
    # cannot see a row a CONCURRENT tick just inserted — see `_insert_review_step` for the
    # measured poke-vs-cadence overlap. This id is fully deterministic, so the loser of
    # that race collides here; it declines rather than killing the whole tick.
    try:
        deps.store.insert_step(task.id, {
            "step_id": step_id, "title": content_step.title,
            "assigned_to": content_step.assigned_to, "deps": rework_deps,
            "step_type": "rework",
            "parent_step_id": content_step.step_id, "review_round": review_round,
        }, needs_web=content_step.needs_web, needs_mail=content_step.needs_mail)
    except sqlite3.IntegrityError:
        logger.info(
            "rework row %s/%s already minted by a concurrent tick — skipping",
            task.id, step_id,
        )
        return False
    return True
