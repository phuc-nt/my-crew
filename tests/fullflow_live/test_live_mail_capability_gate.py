"""v92 — a brief that asks for the mailbox is planned onto someone who can open it.

`needs_mail` exists because of a measured dead end: a mail task was assigned to an agent
with no mailbox access, ran to completion, and spent $0.029 producing "em không có quyền
truy cập hộp thư". The unit tests pin the guard's logic; what they cannot show is what a
real planner does with a real brief when the roster it is given cannot do what the brief
asks. That is the behaviour these cases measure, against a live model and a real fleet.

**Two fleets, one brief.** The same mail-shaped brief runs twice:

- **M1 — nobody can read mail.** The guard rejects any plan that assigns a `needs_mail`
  step, and the rejection goes back into the decompose retry loop. The healthy outcome is
  therefore NOT an error: it is a plan that does not claim mailbox access. The task must
  still be planned and dispatched — a fleet that simply refuses mail-shaped briefs would
  be a regression, not a fix.
- **M2 — one agent can read mail.** With `secretary` granted `gws_context`, any step that
  does declare `needs_mail` must land on that agent and nobody else, and must not be
  routed to the native tier (where the mail tools never arrive).

M2 is the positive control M1 needs, and it is load-bearing in a specific way: every M1
assertion is satisfied by a fleet whose planner never sets `needs_mail` under any
circumstances — including one where the flag was silently dropped from the prompt. M2
fails in that world.

**Why the store, not HTTP.** `control_plane_views.build_task_status` projects step_id,
title, assigned_to, status, step_type, deps, cost_usd — `needs_mail` is not in it. Reading
the flag over HTTP would return None for every step in every possible world, including one
where the whole feature was reverted: a vacuous green. The store is the only place the
fact is observable, the same reasoning `test_live_adversarial_revoked_assignee` records for
`attempt_id`.

**What these cases deliberately do NOT assert.** Whether the planner CHOOSES to set
`needs_mail` on the M2 fleet. That is a model judgement call on a brief, it varies run to
run, and pinning it would make the suite flaky for a reason that is not a product defect.
M2 asserts a conditional — IF a step declares mail, THEN it is on the capable agent — plus
the unconditional invariant that no step ever lands on an incapable one.
"""

from __future__ import annotations

import sqlite3

import pytest

from tests.fullflow.cast import WORKERS
from tests.fullflow_live.topology import boot, seed_home, wait_until_settled

#: The agent granted mailbox access in the M2 fleet. `secretary` on purpose: it is the
#: agent the CEO really granted mail to in v92, so the case mirrors the live fleet.
MAIL_AGENT = "secretary"

#: Mail-shaped and TEAM-shaped at once, and both halves are required.
#:
#: Mail-shaped: step (1) cannot be done without opening the mailbox, so a planner that
#: never considers `needs_mail` on this brief is not being coy — it is not seeing the
#: capability at all.
#:
#: Team-shaped: `classify_brief` is pure code and defaults to SPRINT, and the sprint lane
#: has no `needs_mail` concept whatsoever — a brief that routes there would bypass the
#: gate entirely and the case would pass while testing nothing. Verified with the real
#: classifier rather than assumed: this brief returns
#: `(False, "việc dài nhiều giai đoạn ('trong tuần')")`, i.e. the team lane, and the
#: multi-stage phrasing is what puts it there. Changing the wording can silently move it
#: to sprint, so `test_the_live_mail_brief_still_reaches_the_team_lane` (in
#: `tests/test_task_decomposition.py`) pins it offline.
#:
#: Deliberately SHORT (3 parts, not 6). A measured run with a 6-part version showed why:
#: the guard rejects each mail-claiming plan and the model re-plans inside the retry loop,
#: so the cost of the brief is paid once PER ATTEMPT. At 6 parts three sequential
#: round-trips exceeded even a 420s ceiling and the delegate POST timed out mid-attempt-4,
#: leaving no task row at all. Three parts keeps every property this case needs while
#: making a full retry cycle affordable.
BRIEF = (
    "Rà soát hộp thư rồi lập báo cáo đơn hàng tuần: "
    "(1) đọc hộp thư tìm các email đơn hàng mới trong tuần, "
    "(2) lập bảng tổng hợp số đơn theo từng ngày, "
    "(3) đề xuất 2 việc cần làm tuần sau."
)


def _mail_steps(home, task_id: str) -> list[tuple]:
    """`(step_id, assigned_to, needs_mail, step_type)` for this task's steps, from the store.

    Reads the DB directly because `needs_mail` is not in the HTTP projection (see the
    module docstring). Returns every step, not only the flagged ones, so a caller can tell
    "no step declared mail" apart from "the task has no steps at all" — those are very
    different failures and a filtered query renders them identical.
    """
    con = sqlite3.connect(home / ".data" / "team_tasks.sqlite3")
    try:
        return con.execute(
            "SELECT step_id, assigned_to, needs_mail, step_type FROM team_steps "
            "WHERE task_id = ? ORDER BY seq",
            (task_id,),
        ).fetchall()
    finally:
        con.close()


def _delegate(fleet, journey_budget):
    """Run BRIEF to a settled state on the given fleet; return (task_id, steps, status).

    The 900s ceiling is measured, not padding, and it is this high for one reason: on the
    mail-less fleet the decompose runs MORE THAN ONCE by design. `confirm: True` runs
    preview AND confirm inside a single synchronous request, so every attempt is paid
    before the POST returns; the guard then rejects each mail-claiming plan and the model
    re-plans inside the retry loop (`_MAX_DECOMPOSE_ATTEMPTS = 4`).

    Measured on the capable fleet, where the plan is accepted first try: one decompose cost
    $0.062 and the task finished well inside 420s. The mail-less fleet needs at least two,
    and 420s was observed timing out mid-attempt with the POST never returning and no task
    row written at all. Splitting into the 2-step preview/confirm flow does not help — the
    preview call performs the same decompose, so the wall time simply moves.
    """
    code, body = fleet.post(
        "/api/control-plane/delegate", {"brief": BRIEF, "confirm": True}, timeout=900
    )
    assert code == 200, f"delegate failed {code}: {body!r}"
    task_id = body.get("task_id")
    assert task_id, f"delegate returned no task_id: {body!r}"

    # 900s to settle: a measured run reached `done` on 3 of 4 steps with the last still
    # `running` when a 420s window expired — the fleet was working, the budget was short.
    status = wait_until_settled(fleet, task_id, timeout_s=900)
    journey_budget.note_cost(
        (status.get("cost") or {}).get("total_cost_usd") or 0.0, status
    )
    return task_id, _mail_steps(fleet.home, task_id), status


@pytest.fixture
def mail_less_fleet(tmp_path, live_api_key):
    """A fleet where NO agent can open the mailbox — the default seed."""
    home = tmp_path / "home"
    seed_home(home, api_key=live_api_key)
    server = boot(home, api_key=live_api_key, seed=False)
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def mail_capable_fleet(tmp_path, live_api_key):
    """The same fleet, except `secretary` is granted `gws_context`."""
    home = tmp_path / "home"
    seed_home(home, api_key=live_api_key, mail_capable={MAIL_AGENT})
    server = boot(home, api_key=live_api_key, seed=False)
    try:
        yield server
    finally:
        server.stop()


@pytest.mark.live_slow
def test_m1_a_mail_brief_on_a_mail_less_fleet_is_planned_without_claiming_mail(
    mail_less_fleet, journey_budget,
):
    """No agent can read mail, so no step may claim it — and the work still happens.

    The guard raises inside the decompose retry loop, which means the model gets the
    rejection back and can re-plan. So the outcome under test is not an error surfacing to
    the CEO; it is a plan that does not claim a capability the fleet does not have. Both
    halves are asserted, because each alone is trivially satisfiable: "no mail steps" by a
    fleet that plans nothing, and "a plan exists" by a fleet that ignores the gate.
    """
    task_id, steps, status = _delegate(mail_less_fleet, journey_budget)

    assert steps, (
        f"task {task_id} settled with no steps at all — the brief was never planned, so "
        f"'no step claimed mail' below would be vacuously true. status={status!r}"
    )

    claimed = [s for s in steps if s[2]]
    assert not claimed, (
        f"steps {claimed!r} declared needs_mail on a fleet where NO agent has mailbox "
        "access. validate_mail_steps should have rejected this plan inside the decompose "
        "retry loop, so either the guard is not wired into that loop or the flag was "
        "written after validation."
    )

    # The guard must have actually FIRED, not merely been satisfied by a planner that
    # never reaches for the flag. This is the assertion that actually detects the feature
    # being gone, and a mutation run measured exactly that: with `validate_mail_steps`
    # neutered, the planner emitted a plan with NO mail step at all, so `claimed` above
    # stayed green and only this line went red. Treat the two as unequal — `claimed` pins
    # the invariant, this pins that the invariant was under load.
    assert "đặt needs_mail nhưng đội CHƯA có agent nào" in mail_less_fleet.log(), (
        "the planner never proposed a needs_mail step on a mail-shaped brief, so the guard "
        "was never exercised and this case proves nothing. Either the flag left the "
        "decompose prompt or the brief stopped reading as mail work."
    )


@pytest.mark.live_slow
def test_m2_a_mail_step_lands_only_on_the_agent_that_can_open_the_mailbox(
    mail_capable_fleet, journey_budget,
):
    """With exactly one mail-capable agent, mail work goes to that agent or nowhere.

    This is M1's positive control: M1 is satisfied by a planner that can never set
    `needs_mail` under any circumstances — including one where the flag was dropped from
    the decompose prompt, or the field quietly stopped persisting. Here the capability
    exists, so that world is distinguishable from a working one.

    The mail assertion is a CONDITIONAL, and a measured run justifies that choice: on this
    exact brief with `secretary` capable, the planner produced 4 steps and flagged NONE,
    while on the mail-less fleet it flagged step 1 immediately. Whether to declare the
    capability is a model judgement call that genuinely varies, so pinning it would buy
    flakiness rather than coverage — the "the flag is reachable at all" proof therefore
    lives in M1, where the guard's rejection makes it deterministic.

    What must hold every time is the unconditional half: no step ever lands on an incapable
    agent, which holds whether or not the model flagged anything.
    """
    task_id, steps, status = _delegate(mail_capable_fleet, journey_budget)

    assert steps, f"task {task_id} settled with no steps at all: status={status!r}"

    incapable = {w for w, _ in WORKERS} - {MAIL_AGENT}
    misassigned = [s for s in steps if s[2] and s[1] in incapable]
    assert not misassigned, (
        f"steps {misassigned!r} declared needs_mail but were assigned to an agent without "
        f"mailbox access; only {MAIL_AGENT!r} has it on this fleet. This is precisely the "
        "$0.029 dead end the flag exists to prevent — the step would run, find no mail "
        "tool, and honestly report that it cannot do the work."
    )

    flagged = [s for s in steps if s[2]]
    if flagged:
        # The native tier never receives gws_context, so a mail step routed there is
        # stripped of the tool it declared. `resolve_step_runtime` keeps it off native by
        # construction; a `sprint`/`review` step_type here would mean it went anyway.
        assert all(s[3] == "work" for s in flagged), (
            f"a needs_mail step is on a lane that cannot carry mail tools: {flagged!r}"
        )
        assert all(s[1] == MAIL_AGENT for s in flagged), (
            f"needs_mail steps must be on {MAIL_AGENT!r}: {flagged!r}"
        )
