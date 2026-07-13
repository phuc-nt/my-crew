"""One-action bodies for the coordinator ticker (v12 M28b) — split out of
`coordinator_graph.py` to keep that module under the repo's ~200 LOC guideline.

Each function performs exactly the ONE action `coordinator_graph.run_one_tick`
delegates to it and returns a `TickResult`; none of them loop or poll beyond the
single task/step they were called with — the looping/selection logic stays in
`coordinator_graph._act_on_task`.

P2 (M32) adds the peer-review insert rule (`maybe_insert_review`/
`maybe_insert_rework_or_stall`, called from `coordinator_graph._act_on_task` right
after a content/review/rework step turns `done`, BEFORE the next dispatch decision is
made) — see `review_insert.py` for the rule itself; this module only wires it into the
ticker's action list.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.agent.task_decomposition import MAX_STEPS
from src.runtime.office_room_append import append_office_event, room_for_task
from src.runtime.team_task_cost import spawn_headroom_usd, step_cost_estimate_usd
from src.runtime.team_task_store import TeamStep, TeamTask

if TYPE_CHECKING:
    from src.agent.coordinator_graph import CoordinatorDeps, TickResult

#: A dead-pid step is retried exactly once before being marked permanently `failed`.
MAX_STEP_RETRIES = 1


def ready_pending_steps(task: TeamTask) -> list[TeamStep]:
    """Every `pending` step (in stable `seq` order) whose deps are ALL `done` —
    `TeamTaskStore.next_pending_step` returns only the FIRST one of these; the v13
    parallel-cap dispatcher needs the whole ready set for one tick so it can spawn up
    to `concurrency - running_count` of them, not just one."""
    done_ids = {s.step_id for s in task.steps if s.status == "done"}
    return [
        s for s in task.steps
        if s.status == "pending" and all(dep in done_ids for dep in s.deps)
    ]


def dispatch_ready_steps(
    deps: CoordinatorDeps, task: TeamTask, ready: list[TeamStep],
) -> list[TickResult]:
    """Spawn up to `deps.concurrency - running_count` of `ready` this tick, gated by
    DERIVED cost headroom per candidate (v13 M34) — no reservation ledger, see
    `team_task_cost` module docstring.

    Order: `ready` is already `seq`-ordered (oldest-authored-first, same tie-break
    `next_pending_step` used pre-parallel) so a concurrency=1 caller sees byte-identical
    spawn choice to the old single-spawn dispatch. Stops early (returns fewer than
    `slots` spawns) the moment either the concurrency cap or the cost headroom runs out
    — a step that doesn't fit THIS tick is simply reconsidered next tick, never dropped.
    """
    running_count = sum(1 for s in task.steps if s.status == "running")
    slots = deps.concurrency - running_count
    if slots <= 0:
        return []

    estimate = step_cost_estimate_usd(deps.cost_cap_usd, max_steps=MAX_STEPS)
    # `task` is one snapshot for the whole tick (matches every other action in
    # `_act_on_task`), so `spawn_headroom_usd` — which derives its in-flight sum from
    # `task.steps`' `running` count — would not see a step THIS loop just spawned.
    # Track that locally and subtract it from each subsequent headroom check so two
    # spawns in the SAME tick correctly share one shrinking headroom instead of each
    # being checked against the tick-start snapshot independently.
    already_spawned_this_tick = 0
    spawned: list[TickResult] = []
    for step in ready:
        if len(spawned) >= slots:
            break
        headroom = spawn_headroom_usd(
            deps.store, task, cap_usd=deps.cost_cap_usd, step_estimate_usd=estimate,
        ) - (already_spawned_this_tick * estimate)
        if headroom < estimate:
            # Not a hard stop (that is `check_cost_cap`'s job on ACTUAL recorded
            # spend, checked once per tick before dispatch even starts) — just "no
            # projected room for one more concurrent step this tick", so defer to a
            # later tick once a running step completes and its estimate is released.
            break
        spawned.append(reserve_and_spawn(deps, task, step))
        already_spawned_this_tick += 1
    return spawned


def reserve_and_spawn(deps: CoordinatorDeps, task: TeamTask, step: TeamStep) -> TickResult:
    """Reserve-before-spawn: `reserve_step` always claims (idempotency guard already
    passed — this step was either `pending` or an already-caught dead/expired
    `running` step whose caller cleared it back to reservable via `poll_running_step`).

    Dispatch-time role re-check: the step's `assigned_to` was authorized once
    at decompose-validation time, but the registry/roles can drift between confirm and
    dispatch (an agent disabled, removed, or promoted to coordinator/admin since). A
    mismatch here must fail the step + escalate, NEVER spawn a process under a no-longer
    -authorized identity — checked BEFORE `reserve_step` so a rejected step never
    consumes a lease/attempt_id at all.
    """
    from src.agent.coordinator_graph import TickResult

    if not deps.roster_ok(step.assigned_to):
        deps.store.mark_failed(task.id, step.step_id)
        deps.escalate(
            task, step, "step_assignee_unauthorized",
            f"Bước '{step.title}' của việc '{task.title}' bị dừng: người được giao "
            f"'{step.assigned_to}' không còn hợp lệ (đã bị xoá/vô hiệu hoá) — cần CEO xem lại.",
        )
        return TickResult(task_id=task.id, action="failed", detail=step.step_id)

    attempt_id = deps.store.reserve_step(task.id, step.step_id)
    pid = deps.spawn_step(task, step, attempt_id)
    deps.store.record_spawn(task.id, step.step_id, pid)
    # `author` stays "coordinator" (the ticker is the one dispatching this event, not
    # the assignee doing any work yet) but the office-room reducer needs to know WHICH
    # agent's desk should animate — carried via `assigned_to` in the body, not authorship.
    append_office_event(
        room_for_task(task.id), author="coordinator", kind="step_status",
        body={"task_title": task.title, "step_title": step.title, "status": "started",
              "assigned_to": step.assigned_to},
        also_office=True,
    )
    return TickResult(task_id=task.id, action="spawned",
                      detail=f"{step.step_id} attempt={attempt_id} pid={pid}")


def poll_running_step(deps: CoordinatorDeps, task: TeamTask, step: TeamStep) -> TickResult:
    from src.agent.coordinator_graph import TickResult

    pid_dead = step.child_pid is None or not deps.pid_alive(step.child_pid)
    has_artifact = step.outcome_ref is not None
    lease_expired = deps.store.lease_expired(task.id, step.step_id, now=deps.now())

    if pid_dead and not has_artifact:
        retries = deps.retry_tracker.get(task.id, step.step_id)
        if retries >= MAX_STEP_RETRIES:
            # attempt-guarded: the ticker read `step` as a snapshot at the top
            # of this tick — pass its OWN attempt_id so a concurrent re-reservation
            # (another ticker instance, or the worker's own terminal write racing this
            # one) makes this a clean no-op instead of clobbering a newer attempt's row.
            deps.store.mark_failed(task.id, step.step_id, attempt_id=step.attempt_id)
            deps.retry_tracker.clear(task.id, step.step_id)
            deps.escalate(
                task, step, "step_failed",
                f"Bước '{step.title}' của việc '{task.title}' thất bại sau "
                f"{MAX_STEP_RETRIES + 1} lần thử (tiến trình chết, không có kết quả).",
            )
            return TickResult(task_id=task.id, action="failed", detail=step.step_id)
        deps.retry_tracker.increment(task.id, step.step_id)
        # Re-reserve NOW (idempotent: caller already verified pid-dead+no-artifact,
        # the store-level double-spawn guard per M28a's docstring).
        return reserve_and_spawn(deps, task, step)

    if lease_expired:
        if step.child_pid is not None and step.attempt_id is not None:
            deps.kill_pid(step.child_pid, step.attempt_id)
        deps.store.mark_timeout(task.id, step.step_id, attempt_id=step.attempt_id)
        # v17 (red-team M2): the timeout path previously emitted only the escalation
        # milestone — the desk reducer never saw a step_status, so the 3D desk stayed
        # "working" and its bubble hung forever. `failed` is existing vocabulary; the
        # reducer frees the desk back to idle. try/degrade like every room append.
        _append_timeout_step_event(task, step)
        deps.escalate(
            task, step, "step_timeout",
            f"Bước '{step.title}' của việc '{task.title}' quá thời hạn "
            f"({deps.step_timeout_s}s) — đã dừng tiến trình, cần CEO xem lại.",
        )
        return TickResult(task_id=task.id, action="timeout_escalated", detail=step.step_id)

    return TickResult(task_id=task.id, action="none", detail=f"{step.step_id} still running")


def _append_timeout_step_event(task: TeamTask, step: TeamStep) -> None:
    """Room event for a timeout-kill (v17 M2): same `step_status failed` shape the
    worker's own failure path emits (`team_step_runner._append_step_event`) so the FE
    reducer needs no new vocabulary — the desk frees back to idle instead of hanging
    "working" with a stale bubble. Best-effort like every office append."""
    append_office_event(
        room_for_task(task.id), author="coordinator", kind="step_status",
        body={"task_title": task.title, "step_title": step.title, "status": "failed",
              "assigned_to": step.assigned_to},
        also_office=True,
    )


def poll_awaiting_approval_step(
    deps: CoordinatorDeps, task: TeamTask, step: TeamStep
) -> TickResult:
    """A step paused on a Lớp B gate WITH a known `approval_id`: poll `ApprovalStore`
    (via `deps.approval_status`) and act on a resolved decision.

    `approved` -> re-reserve + re-spawn the SAME step. Since v34 P1 the step graph is
    checkpointed, so the re-spawned worker RESUMES the saved thread at its last
    completed node (fresh `attempt_id`, adopted into the saved state). A lost/unusable
    checkpoint degrades to a from-scratch re-run — still safe because `deliver`'s
    external write goes back through the SAME per-agent `ActionGateway`, whose
    reserve-before-execute dedup claim (content-hash or `dedup_hint`, see
    `action_gateway._action_dedup_key`) makes an identical re-attempt a no-op
    `"deduplicated"` result if the write already went out, and a normal single
    execution if it never did — either way the CEO never gets a duplicate external
    effect from this replay.

    `rejected` -> terminal: mark the step `failed` (no retry — the CEO explicitly said
    no) and escalate.

    `pending` (or an id that no longer resolves, `None`) -> leave the step exactly
    alone, same as a step with no `approval_id` at all — the lease clock stays PAUSED,
    nothing is timed out or re-polled until the next tick.
    """
    from src.agent.coordinator_graph import TickResult

    decision = deps.approval_status(step.approval_id) if step.approval_id else None
    if decision == "approved":
        return reserve_and_spawn(deps, task, step)
    if decision == "rejected":
        # attempt-guarded: same rationale as `poll_running_step`'s terminal
        # writes — `step.attempt_id` is the lease this ticker read the row under.
        deps.store.mark_failed(task.id, step.step_id, attempt_id=step.attempt_id)
        deps.escalate(
            task, step, "step_approval_rejected",
            f"Bước '{step.title}' của việc '{task.title}' bị từ chối phê duyệt — đã dừng.",
        )
        return TickResult(task_id=task.id, action="failed", detail=step.step_id)
    return TickResult(task_id=task.id, action="none",
                      detail=f"{step.step_id} awaiting_approval (id={step.approval_id})")


def poll_waiting_clarify_step(
    deps: CoordinatorDeps, task: TeamTask, step: TeamStep
) -> TickResult:
    """v34 P2: a step paused mid-graph on a CEO clarify question WITH a known
    `clarify_id` — poll the ClarifyStore (via `deps.clarify_status`).

    `answered` or `expired` -> re-reserve + re-spawn the SAME step; its worker resumes
    the saved checkpoint thread with `Command(resume=<answer or "">)` (an expired
    question resumes with "" — the safe-default draft ships as-is; the queue can never
    wedge a task, mirroring `clarify_store`'s own expiry contract).

    `pending` (or an id that no longer resolves, `None` — e.g. a wiped clarify DB) ->
    leave the step exactly alone; the lease clock stays PAUSED like an
    `awaiting_approval` step. An unresolvable id never blocks forever in practice:
    the row it pointed at is gone, so the expire sweep can't flip it either — the
    follow-up sweep (v34 P3) is the escalation net for that pathological case.
    """
    from src.agent.coordinator_graph import TickResult

    status = deps.clarify_status(step.clarify_id) if step.clarify_id else None
    if status is not None and status[0] in ("answered", "expired"):
        return reserve_and_spawn(deps, task, step)
    return TickResult(task_id=task.id, action="none",
                      detail=f"{step.step_id} waiting_clarify (id={step.clarify_id})")


def aggregate_and_deliver(deps: CoordinatorDeps, task: TeamTask) -> TickResult:
    from src.agent.coordinator_graph import TickResult

    summary, cost = deps.aggregate(task)
    if cost is not None:
        deps.store.record_task_cost(task.id, aggregate=cost)
    deps.deliver_room(task, summary)
    deps.store.set_task_status(task.id, "done")
    return TickResult(task_id=task.id, action="aggregated", detail=summary[:80])
