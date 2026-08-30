"""X4 — an agent revoked AFTER planning never gets to run the step it was given.

This is a time-of-check-to-time-of-use gap, and the product names it explicitly. A step's
`assigned_to` is authorized ONCE, at decompose-validation time, before the CEO sees the
preview. Dispatch happens later — seconds later for a fast step, many minutes later for
one waiting behind dependencies. In between, the roster can change: an agent is disabled,
removed, or promoted into the coordinator/admin role. `_reserve_and_spawn`'s docstring
states the requirement in the imperative: a mismatch "must fail the step + escalate,
NEVER spawn a process under a no-longer-authorized identity".

**Why the identity matters, and not just the bookkeeping.** `team_task_roster`'s docstring
records what the exclusions are protecting: the admin agent is "the CEO's fleet-overseer
/ops-chat agent, not a line worker; giving it a team-task step would let a CEO brief
accidentally grant a team-task step the admin agent's config-write ops-chat privileges."
So the gate is a privilege boundary, and a step spawned under a revoked identity is a
worker process running with authority the CEO never approved for that work.

**Why this cannot be tested in-process.** The check reads the roster fresh from
`registry.yaml` at dispatch. In one process, the "revocation" would be a mutated object
that the tick loop was handed; here the file is rewritten on disk under a running fleet,
and the coordinator — a separate OS process, already mid-task, already holding a plan
that names this agent — has to notice on its own next tick. That is the actual race, and
only two processes and a real file can produce it.

The revocation is timed to land AFTER the plan exists (so the assignment was genuinely
authorized once) and while at least one step is still unstarted (so there is something
left to dispatch). A revocation that arrived before planning would be tested by the
decompose-time gate instead — a different guard, already covered — and would prove
nothing about drift.

Two cases:

- **X4** — revoke a worker holding un-dispatched work; assert the fleet refuses to spawn
  under it, and says so, rather than running the step anyway.
- **X4b** — the positive control: the SAME brief, the SAME timing, no revocation. Without
  it, X4 is satisfied by a fleet that never dispatches anything at all.
"""

from __future__ import annotations

import json
import sqlite3

import pytest
import yaml

from tests.fullflow.cast import ADMIN_ID, COORDINATOR_ID, WORKERS
from tests.fullflow_live.topology import boot, poll_until, seed_home, task_status

#: Multi-step on purpose. The revocation has to land while work is still PENDING, so the
#: brief must be big enough that not everything dispatches on the first tick.
BRIEF = (
    "Chuẩn bị tài liệu ra mắt sản phẩm: (1) viết mô tả sản phẩm, "
    "(2) liệt kê 3 câu hỏi thường gặp, (3) viết một email thông báo ngắn."
)


def _revoke(home, agent_id: str) -> None:
    """Disable one agent in the live registry, exactly as an operator editing the file.

    Rewrites `registry.yaml` in place rather than calling any API: the point is that the
    coordinator re-reads the roster at dispatch, and the flat file is the source both
    `assignable_staff` and a real operator go through. Parsed and re-emitted rather than
    string-replaced, so a change to the file's shape breaks this loudly instead of
    silently editing nothing.
    """
    path = home / "registry.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    entries = doc.get("agents") or []
    hit = [e for e in entries if e.get("id") == agent_id]
    assert hit, (
        f"{agent_id!r} is not in the registry, so disabling it would be a no-op and this "
        f"case would assert nothing: {entries!r}"
    )
    for entry in hit:
        entry["enabled"] = False
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


def _dispatch_witnesses(home, task_id: str, step_id: str) -> list[tuple]:
    """Evidence that ONE specific step was ever dispatched.

    Both columns are store-only — neither `child_pid` nor `attempt_id` appears in the
    HTTP step projection — so this is not a shortcut around the public surface; it is the
    only place the fact is observable.

    `attempt_id` is included because it is issued by `reserve_step`, and the roster gate
    runs BEFORE reserve. Its presence therefore proves the gate did not fire in time,
    even in the case where the spawn itself then failed and left no pid behind.

    Scoped to a single `step_id` rather than to everything the revoked agent holds, and
    that narrowing is load-bearing: an agent can hold several steps, and one dispatched
    LEGITIMATELY before the revocation would carry an attempt_id forever. Querying by
    assignee would read that as a gate failure and fail the case for doing the right
    thing. Only the step that was still pending when the registry changed is evidence.

    Known limit, stated rather than papered over: `reset_step_to_pending` CLEARS
    attempt_id, so a step that was dispatched, released back to pending, and only then
    revoked would read clean here despite having run once. That sequence cannot occur in
    this case — the step is chosen while pending and revoked immediately, with no
    intervening dispatch to release — but the helper is not a general-purpose
    "did this ever run" oracle, and should not be reused as one.
    """
    db = home / ".data" / "team_tasks.sqlite3"
    con = sqlite3.connect(db)
    try:
        return con.execute(
            "SELECT step_id, status, attempt_id, child_pid FROM team_steps "
            "WHERE task_id = ? AND step_id = ? "
            "AND (attempt_id IS NOT NULL OR child_pid IS NOT NULL)",
            (task_id, step_id),
        ).fetchall()
    finally:
        con.close()


def _escalation_milestones(home, task_id: str) -> dict[str, list[str]]:
    """Milestone events the coordinator delivered about this task: kind -> messages.

    This is where an escalation actually lands. `make_escalate` sends to Telegram (a
    no-op under this harness, which has no real bot binding) and appends a `milestone`
    room event whose body carries `{"milestone": <event_kind>, "message": <text>}`. It
    prints NOTHING to the server's stdout, which is why grepping the log for the event
    kind reports a failure while the product is working correctly.

    Scoped to this task's rooms. `append_office_event(..., also_office=True)` writes the
    same event twice on purpose — once into the task's own room (`room_for_task`, the
    task id here) and once into the shared `office` room — so a kind legitimately
    appears twice and the count carries no meaning. Only presence and text do, which is
    why this returns messages keyed by kind rather than a tally.
    """
    db = home / ".data" / "office_room.sqlite3"
    if not db.exists():
        return {}
    con = sqlite3.connect(db)
    try:
        rows = con.execute(
            "SELECT body_json FROM messages WHERE kind = 'milestone'"
        ).fetchall()
    finally:
        con.close()

    found: dict[str, list[str]] = {}
    for (body,) in rows:
        try:
            parsed = json.loads(body)
        except (TypeError, ValueError):
            continue
        if parsed.get("task_id") != task_id:
            continue
        kind = parsed.get("milestone")
        if kind:
            found.setdefault(str(kind), []).append(str(parsed.get("message") or ""))
    return found


def _revocable_steps(status) -> list[dict]:
    """Pending steps whose revocation the dispatch gate can still catch, hardest first.

    Only `pending` steps qualify at all — anything already running was dispatched before
    the revocation and is a different question (that one is the lease/halt path).

    Ordered by dependency count, descending, and that ordering is the fix for a real race
    in an earlier draft of this case: a pending step with no unmet deps can be dispatched
    by the very next tick, in the gap between reading the status and rewriting the
    registry. When that happened the gate correctly never fired — there was nothing left
    to gate — and the case failed for a reason that was not a product defect. A step
    parked behind dependencies cannot be dispatched until its parents finish, which buys
    the revocation a wide, deterministic window to land in.
    """
    pending = [
        s for s in (status.get("steps") or [])
        if s.get("status") == "pending" and s.get("assigned_to")
    ]
    return sorted(pending, key=lambda s: len(s.get("deps") or []), reverse=True)


@pytest.fixture
def fleet(tmp_path, live_api_key):
    home = tmp_path / "home"
    seed_home(home, api_key=live_api_key)
    server = boot(home, api_key=live_api_key, seed=False)
    try:
        yield server
    finally:
        server.stop()


def test_x4_a_revoked_assignee_is_refused_at_dispatch_not_spawned(fleet, journey_budget):
    code, body = fleet.post(
        "/api/control-plane/delegate", {"brief": BRIEF, "confirm": True}, timeout=180
    )
    assert code == 200, f"delegate failed {code}: {body!r}"
    task_id = body.get("task_id")
    assert task_id, f"delegate returned no task_id: {body!r}"

    # Wait for a real plan that still has undispatched work. Both halves matter: a plan
    # proves the assignment was authorized (so revoking it later is genuinely drift), and
    # a pending step proves there is still a dispatch left for the gate to catch.
    planned = poll_until(
        lambda: (lambda s: s if _revocable_steps(s) else None)(task_status(fleet, task_id)),
        timeout_s=180, interval_s=2,
        what=f"task {task_id} to have a plan with at least one pending step",
    )
    target = _revocable_steps(planned)[0]
    victim = target["assigned_to"]
    step_id = target["step_id"]
    assert victim not in (ADMIN_ID, COORDINATOR_ID), (
        f"the coordinator assigned a step to {victim!r}, which the roster is supposed to "
        "exclude from team-task work entirely — the decompose-time gate has failed and "
        "this case is no longer testing dispatch-time drift"
    )

    # -- the drift: authorized at plan time, revoked before dispatch -------------------
    _revoke(fleet.home, victim)

    # The fleet must now refuse THAT step — matched by step_id, not merely by assignee.
    # A task that fails for any other reason, or a different step of the same agent
    # failing, would otherwise look like a pass.
    def refused():
        status = task_status(fleet, task_id)
        for step in status.get("steps") or []:
            if step.get("step_id") == step_id and step.get("status") == "failed":
                return status
        return None

    final = poll_until(
        refused, timeout_s=240, interval_s=3,
        what=f"step {step_id} held by revoked agent {victim!r} to be failed, not spawned",
    )
    journey_budget.note_cost((final.get("cost") or {}).get("total_cost_usd") or 0.0)

    # 1. Nothing ever ran under the revoked identity — the actual security claim.
    #
    #    Read from the STORE, because the HTTP step view does not expose `child_pid` or
    #    `attempt_id` at all (`control_plane_views.build_task_status` projects step_id,
    #    title, assigned_to, status, step_type, deps, cost_usd — nothing else). Asserting
    #    `not step.get("pid")` over HTTP would read None for every step in every possible
    #    world, including one where the process really did spawn: a vacuous green.
    #
    #    `attempt_id` is the sharper witness of the two. The roster check sits BEFORE
    #    `reserve_step`, and reserving is what issues an attempt_id, so a correctly
    #    refused step must carry NEITHER. A step that was spawned and only afterwards
    #    marked failed still satisfies a status-only assertion while having already
    #    executed with authority the CEO withdrew.
    reserved = _dispatch_witnesses(fleet.home, task_id, step_id)
    assert not reserved, (
        f"step {step_id}, held by revoked agent {victim!r}, was reserved/spawned before "
        f"being failed: {reserved!r} — a process ran under an identity the CEO had "
        "withdrawn, which is what checking the roster before reserve_step exists to prevent"
    )

    # 2. The CEO was told, and told WHY. A step that fails silently is indistinguishable
    #    from a crash, and leaves the operator with no idea their edit stopped the work.
    #
    #    Read from the OFFICE-ROOM store, not the server log. `make_escalate` does not
    #    print the event kind to stdout at all — it sends to Telegram (no-op here, the
    #    harness has no real bot) and appends a `milestone` event carrying
    #    `{"milestone": <event_kind>, "message": ...}`. An earlier draft of this case
    #    grepped `fleet.log()` and failed while the product was behaving correctly:
    #    the notification was there, in the place the CEO actually reads it.
    #
    #    This is also the stronger assertion. A log line is incidental output that any
    #    refactor may drop; the room event is the delivered artifact the UI renders and
    #    the Telegram mirror replays, so asserting on it pins the behavior that matters.
    milestones = _escalation_milestones(fleet.home, task_id)
    assert "step_assignee_unauthorized" in milestones, (
        f"the step held by {victim!r} failed but no 'step_assignee_unauthorized' "
        f"milestone reached the CEO's room — a dead step with no stated cause. "
        f"milestones seen: {sorted(milestones)!r}"
    )
    assert any("không còn hợp lệ" in m for m in milestones["step_assignee_unauthorized"]), (
        "the milestone fired but its message never says the assignee is no longer "
        f"valid: {milestones['step_assignee_unauthorized']!r}"
    )


def test_x4b_an_unrevoked_fleet_dispatches_the_same_work(fleet, journey_budget):
    """The positive control, and X4 is worthless without it.

    Every assertion in X4 is satisfied by a fleet that dispatches NOTHING: a coordinator
    that crashed on its first tick, a roster loader that returns empty for everyone, a
    registry parse that fails closed. In all of those the step is pending-then-failed and
    never spawned — exactly what X4 checks for. This case fails in every one of those
    worlds, which is what licenses X4's refusal to be read as "the gate discriminated".

    Same brief and same waiting shape as X4, minus the revocation. It asserts only that
    work reaches a running/completed state under an agent that is still on the roster —
    what the fleet ultimately produces is the journeys' subject, not this one's.
    """
    code, body = fleet.post(
        "/api/control-plane/delegate", {"brief": BRIEF, "confirm": True}, timeout=180
    )
    assert code == 200, f"delegate failed {code}: {body!r}"
    task_id = body["task_id"]

    def dispatched():
        status = task_status(fleet, task_id)
        for step in status.get("steps") or []:
            if step.get("status") in ("running", "done", "completed"):
                return status
        return None

    status = poll_until(
        dispatched, timeout_s=240, interval_s=3,
        what=f"task {task_id} to dispatch a step with NO revocation in play",
    )
    journey_budget.note_cost((status.get("cost") or {}).get("total_cost_usd") or 0.0)

    worker_ids = {w for w, _ in WORKERS}
    live_steps = [
        s for s in (status.get("steps") or [])
        if s.get("status") in ("running", "done", "completed")
    ]
    assert any(s.get("assigned_to") in worker_ids for s in live_steps), (
        f"work was dispatched, but to nobody on the worker roster: {live_steps!r}"
    )
