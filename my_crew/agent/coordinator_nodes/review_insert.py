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
       - "needs_rework" AND `review_round >= MAX_REVIEW_ROUNDS` -> EXPLICIT stall +
         escalate (v12's `_dead_end_result` cannot see this: every step here is `done`,
         never `failed`/`timeout`).
       - verdict artifact missing/stale (`stale_artifact`, the reviewed content re-ran
         since this review was queued) -> mint a FRESH review-step (round unchanged) so
         a new reviewer run grades the CURRENT artifact instead of leaving the task stuck
         on a review that graded content nobody will ever see delivered.
  3. A `rework` step reaches `done` -> mint a NEW review-step for it (`review_round + 1`)
     — the rework's own freshly-written artifact becomes the next round's locked target.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from my_crew.runtime.office_room_append import append_office_event, room_for_task
from my_crew.runtime.team_task_store import TeamStep, TeamTask

if TYPE_CHECKING:
    from my_crew.agent.coordinator_graph import CoordinatorDeps

#: Peer review is capped at this many rework rounds (`review_round` col, 0-indexed) —
#: round `MAX_REVIEW_ROUNDS` still failing means the ticker stalls + escalates instead
#: of ever minting a 3rd rework attempt (R "oscillation rework" in the phase's risk
#: register).
MAX_REVIEW_ROUNDS = 2


def _review_child(task: TeamTask, content_step_id: str, step_type: str) -> TeamStep | None:
    """The most-recently-inserted `step_type` child of `content_step_id`, or None.
    `steps_for_task`/`task.steps` is seq-ordered, so the LAST match is the newest round
    — needed because a 2-round review keeps BOTH round-0 and round-1 review rows (each
    verdict artifact is filed under its own round number, never overwritten)."""
    matches = [
        s for s in task.steps if s.step_type == step_type and s.parent_step_id == content_step_id
    ]
    return matches[-1] if matches else None


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
    if done_step.step_type != "work" or not done_step.needs_review:
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

    _insert_review_step(deps, task, done_step, reviewer=reviewer, review_round=0)
    return True


def maybe_handle_review_done(deps: CoordinatorDeps, task: TeamTask, review_step: TeamStep) -> bool:
    """After a `review` step turns `done`: act on its verdict artifact. Returns True
    iff this tick minted a row / changed task status (caller re-reads the task before
    continuing)."""
    if review_step.step_type != "review" or review_step.parent_step_id is None:
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
        if _review_child(task, content_step_id, "review") is review_step:
            _insert_review_step(
                deps, task, content_step, reviewer=review_step.assigned_to,
                review_round=review_step.review_round,
            )
            return True
        return False

    if bool(verdict.get("passed")):
        return False  # normal DAG continuation — nothing more to insert.

    if review_step.review_round >= MAX_REVIEW_ROUNDS:
        deps.store.set_task_status(task.id, "stalled")
        deps.escalate(
            task, content_step, "review_rounds_exhausted",
            f"Việc '{task.title}' bị dừng: bước '{content_step.title}' soát chéo "
            f"không đạt sau {MAX_REVIEW_ROUNDS + 1} lượt sửa — cần CEO xem lại.",
        )
        return True

    # Scoped to THIS review's own round — a prior round's rework row (e.g. round 0's,
    # already `done` and superseded by this round-1 review) must never be mistaken for
    # "round 1's rework already minted"; each round mints its own rework exactly once.
    rework_this_round = any(
        s.step_type == "rework" and s.parent_step_id == content_step_id
        and s.review_round == review_step.review_round for s in task.steps
    )
    if rework_this_round:
        return False  # rework already minted this round — avoid a double insert.
    _insert_rework_step(deps, task, content_step, review_round=review_step.review_round)
    return True


def maybe_insert_review_after_rework(
    deps: CoordinatorDeps, task: TeamTask, rework_step: TeamStep
) -> bool:
    """After a `rework` step turns `done`: mint the NEXT round's review-step (its
    parent is the ORIGINAL content step, not the rework row itself — `review_round`
    increments so the new verdict artifact never clobbers the prior round's)."""
    if rework_step.step_type != "rework" or rework_step.parent_step_id is None:
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
    _insert_review_step(
        deps, task, content_step, reviewer=reviewer, review_round=next_round,
        source_step_id=rework_step.step_id,
    )
    return True


def _insert_review_step(
    deps: CoordinatorDeps, task: TeamTask, content_step: TeamStep, *, reviewer: str,
    review_round: int, source_step_id: str | None = None,
) -> None:
    """Mint one review-step row. `source_step_id` (defaults to `content_step.step_id`)
    is the row whose FRESH artifact this review locks onto — round >=1 reviews lock the
    latest rework's artifact, not the original content step's.

    `step_id` includes a `-<n>` mint-count suffix (n = how many review rows already
    exist for this content step, at ANY round) rather than JUST `-review-<round>` —
    a stale-artifact re-mint (`maybe_handle_review_done`'s "verdict is None" branch)
    inserts a SECOND review row at the SAME round as an already-`done` one, which would
    otherwise collide on `UNIQUE(task_id, step_id)`. The round number a reader cares
    about (idempotency, `review_round` column, verdict artifact filename) is unaffected
    — it lives in the `review_round` column, never parsed back out of `step_id`.
    """
    locked_on = source_step_id or content_step.step_id
    mint_count = len([s for s in task.steps if s.step_type == "review"
                      and s.parent_step_id == content_step.step_id])
    step_id = f"{content_step.step_id}-review-{review_round}-{mint_count}"
    deps.store.insert_step(task.id, {
        "step_id": step_id, "title": f"Soát chéo: {content_step.title}",
        "assigned_to": reviewer, "deps": [locked_on], "step_type": "review",
        "parent_step_id": content_step.step_id, "review_round": review_round,
    })


def _insert_rework_step(
    deps: CoordinatorDeps, task: TeamTask, content_step: TeamStep, *, review_round: int,
) -> None:
    """Mint one rework-step row, same original author, `deps=[review_step_id]`.

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
    deps.store.insert_step(task.id, {
        "step_id": step_id, "title": content_step.title,
        "assigned_to": content_step.assigned_to, "deps": [dep_id], "step_type": "rework",
        "parent_step_id": content_step.step_id, "review_round": review_round,
    })
