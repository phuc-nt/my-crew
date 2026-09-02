"""X2 — a breached spending ceiling stops the company, structurally.

`team_task_cap_usd` is the only hard stop between a looping pipeline and the CEO's
credit card. Everything else in the cost path is advisory: `spawn_headroom_usd` merely
defers a spawn to a later tick, and `_maybe_warn_cost_cap` only warns. The single place
that actually halts is `check_cost_cap` in `_act_on_task`, and when it trips it does
four separate things (`coordinator_graph._act_on_task`):

1. flips the task to `stalled` FIRST — the safety transition must not depend on the
   brake succeeding,
2. calls `halt_running_steps` to kill in-flight workers ("stop spending NOW"),
3. escalates `cost_cap_exceeded` to the CEO,
4. returns `action="cap_exceeded"`.

Ordering matters and is asserted as behaviour, not as source: a task that stalls but
keeps its workers running would still be billing, which is the exact regression the
comment in that function records (post-cancel drift kept billing).

**Why this needs a live fleet.** The cap is only meaningful against *real recorded
spend*. `check_cost_cap` sums what the store actually holds, and only real model calls
put real numbers there. An in-process test that writes a fake cost row proves the
comparison operator works; it does not prove the fleet stops. So this case sets a cap so
low that one honest step breaches it, then lets the real coordinator discover that on
its own tick.

The cap is set to a value ABOVE zero deliberately. A zero cap would trip before any work
happened, and "stalled a task that never started" is a different, much weaker claim than
"noticed money was spent and pulled the brake".
"""

from __future__ import annotations

import sqlite3

import pytest

from tests.fullflow_live.topology import boot, poll_until, seed_home, task_status

#: Low enough that real spend exceeds it, high enough to be a genuine ceiling rather
#: than a degenerate zero.
#:
#: Measured: with this cap the breach happens during DECOMPOSITION — planning the brief
#: costs ~$0.003, which already exceeds $0.001 — so `check_cost_cap` fires on the first
#: tick, before any step is dispatched. That is the cap working correctly (it is checked
#: at the top of `_act_on_task`, and decompose cost is part of `sum_cost`), and it is
#: what this case asserts. Raising the cap does not change the shape: probed at $0.004,
#: decomposition still breached it first and the task still stalled with no step spawned.
TINY_CAP_USD = 0.001

#: Multi-row on purpose. A single-step task could finish before any tick re-examines it,
#: and then the cap would never be consulted — the case would pass by never testing
#: anything. Three parts of one content plan are no longer enough: the planner merges
#: same-tier steps, so that brief folded to ONE step and was downgraded to a sprint
#: (measured, one paid run). The cross-check ask is what keeps it a crew — do+review is
#: the one small plan the router refuses to fold — and the reviewer row guarantees at
#: least one `_act_on_task` after spend is recorded. Pinned offline by
#: `test_the_live_cost_cap_breach_brief_still_plans_as_do_review`.
BRIEF = (
    "Viết kế hoạch nội dung cho trang chủ: (1) đoạn giới thiệu công ty, "
    "(2) danh sách 3 tính năng chính, (3) một lời kêu gọi hành động, "
    "rồi nhờ người khác soát chéo trước khi gửi anh."
)


def _recorded_spend(home, task_id: str) -> float:
    """The spend the COST CAP sees: `sum(step costs) + decompose + aggregate`.

    Read straight from the store because the HTTP status block reports a DIFFERENT
    number, from a different source. `control_plane_views._task_cost_breakdown` builds
    `cost.total_cost_usd` out of `CaptureStore`, while `TeamTaskStore.sum_cost` — the
    function `check_cost_cap` actually consults — sums the task/step rows.

    Measured on this suite's own runs, they disagree in BOTH directions:

    | task              | store `sum_cost` | HTTP `cost.total` |
    |-------------------|------------------|-------------------|
    | capped (stalled)  | $0.003185        | $0.000000         |
    | control (healthy) | $0.004965        | $0.006258         |

    The capped row is the one that matters here: a task whose planning cost breached the
    ceiling is reported to the CEO as having spent nothing at all. Since the guard is
    enforced against `sum_cost`, `sum_cost` is the only figure that can witness a breach,
    so this case reads it directly rather than asserting against a number the guard never
    looked at.

    This mirrors J4's `_stored_route`: when a view deliberately reshapes what it exposes,
    an invariant about the underlying mechanism is asserted at the store.
    """
    db = home / ".data" / "team_tasks.sqlite3"
    con = sqlite3.connect(db)
    try:
        row = con.execute(
            "SELECT decompose_cost_usd, aggregate_cost_usd FROM team_tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        steps = con.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM team_steps WHERE task_id = ?",
            (task_id,),
        ).fetchone()
    finally:
        con.close()
    if not row:
        return 0.0
    return float(row[0] or 0.0) + float(row[1] or 0.0) + float((steps or [0])[0] or 0.0)


@pytest.fixture
def capped_fleet(tmp_path, live_api_key):
    """A fleet identical to every other journey's except for one number.

    `seed_home` hardcodes `team_task_cap_usd: 5.0`, so the cap is rewritten after seeding
    rather than by parameterising the helper — same pattern the escalation journey uses
    for `manager_id`, and it keeps the shared seeder honest about being the default.
    """
    home = tmp_path / "home"
    seed_home(home, api_key=live_api_key)
    company = home / "company.yaml"
    company.write_text(
        company.read_text(encoding="utf-8").replace(
            "team_task_cap_usd: 5.0", f"team_task_cap_usd: {TINY_CAP_USD}"
        ),
        encoding="utf-8",
    )
    assert f"team_task_cap_usd: {TINY_CAP_USD}" in company.read_text(encoding="utf-8"), (
        "the cap rewrite did not take — seed_home's company.yaml shape changed, and this "
        "case would silently run against the default $5 cap and prove nothing"
    )

    server = boot(home, api_key=live_api_key, seed=False)
    try:
        yield server
    finally:
        server.stop()


#: How long the synchronous delegate POST may take. 180s held for months — one decompose
#: on the live model answers in well under a minute — and then failed twice on 2026-09-02
#: with the fleet still inside its FIRST decompose attempt: OpenRouter kept the socket busy
#: with keep-alive whitespace while the upstream stalled, so nothing timed out server-side
#: either. The client now abandons an attempt at a 240s wall-clock deadline and retries,
#: which is the product's own recovery; a 180s wait here ended the case before that
#: recovery could run. 900s is what the rest of the live suite already allows a delegate.
DELEGATE_TIMEOUT_S = 900


def test_x2_breaching_the_cost_cap_stalls_the_task_and_halts_its_steps(capped_fleet,
                                                                       journey_budget):
    code, body = capped_fleet.post(
        "/api/control-plane/delegate", {"brief": BRIEF, "confirm": True}, timeout=DELEGATE_TIMEOUT_S
    )
    assert code == 200, f"delegate failed {code}: {body!r}"
    task_id = body.get("task_id")
    assert task_id, f"delegate returned no task_id: {body!r}"

    # Wait for the brake, not for "settled": `stalled` is deliberately NOT in
    # SETTLED_TASK_STATES, because an unattended fleet leaves a stalled task exactly
    # where it is — which is the correct behaviour and the thing being asserted.
    final = poll_until(
        lambda: (lambda s: s if (s.get("state") or {}).get("status") == "stalled" else None)(
            task_status(capped_fleet, task_id)
        ),
        timeout_s=300, interval_s=3,
        what=f"task {task_id} to stall on the cost cap",
    )

    # Spend is read from the STORE, not from the HTTP `cost` block, and that is not a
    # convenience — the two genuinely disagree (see `_recorded_spend`'s docstring). The
    # cap is enforced against `sum_cost`, so `sum_cost` is the only number that can
    # witness a cap breach; asserting on the HTTP figure would be asserting against a
    # different accounting than the one the guard consulted.
    spent = _recorded_spend(capped_fleet.home, task_id)
    journey_budget.note_cost(max(spent, (final.get("cost") or {}).get("total_cost_usd") or 0.0))

    # 1. It stalled BECAUSE money was spent, not because nothing happened. Without this
    #    the case would also pass against a fleet that stalls every task instantly.
    assert spent > 0, (
        f"task stalled having spent {spent} — a stall with no recorded spend is not a "
        "cap breach, so this case would be green against a fleet that simply cannot work"
    )
    assert spent > TINY_CAP_USD, (
        f"task stalled at ${spent}, which is UNDER the ${TINY_CAP_USD} cap — something "
        "other than the cost cap stopped it, and this case is measuring the wrong thing"
    )

    # 2. Nothing is left burning. This is the half that a `stalled` status alone does not
    #    give you: the comment in `_act_on_task` records a real regression where a task
    #    was cancelled and its workers kept billing.
    still_running = [
        s for s in (final.get("steps") or []) if s.get("status") == "running"
    ]
    assert not still_running, (
        f"task is stalled but {len(still_running)} step(s) are still running: "
        f"{still_running} — the ceiling was breached and the fleet is STILL spending"
    )

    # 3. An attempt was made to tell the CEO.
    #
    # Asserted as "the notify path ran", not as "the CEO received a cap message", and the
    # difference is the harness's own doing: this suite seeds a deliberately fake Telegram
    # token so a test run can never message a real person, so `deps.escalate` RAISES here.
    # Measured consequence — worth knowing when reading a failure: the stall is written
    # before the escalation, so the task still ends `stalled` correctly, but the
    # `cap_exceeded` branch does not reach its own log line, and the tick is concluded by
    # the give-up path instead. Asserting on the cap wording would therefore be asserting
    # that the sandbox can send Telegram messages, which it must not.
    #
    # What IS honest to require: the operator-notify channel was exercised. A cap breach
    # that stops a task while telling nobody is the silent-failure mode that matters, and
    # a build that skipped notification entirely would show none of these markers.
    log = capped_fleet.log()
    notified = (
        "cost_cap_exceeded" in log
        or "vượt trần chi phí" in log
        or "operator notice" in log
        or "telegram" in log.lower()
    )
    assert notified, (
        "the task stalled and NOTHING in the log shows an attempt to tell the CEO — a "
        "budget stop that notifies nobody is indistinguishable from a fleet that hung"
    )


def test_x2b_a_normal_cap_does_not_stall_ordinary_work(tmp_path, live_api_key,
                                                       journey_budget):
    """The positive control. Same brief, the DEFAULT cap.

    X2 above is satisfied by a fleet that stalls everything — a coordinator that crashed,
    a comparison inverted to `spent >= 0`, a company loader returning a cap of zero for
    every read. All of those are catastrophic, and all of them make X2 green. This case
    fails in every one of those worlds, which is what licenses X2's stall to be read as
    "the cap fired" rather than "nothing works".

    It asserts only the negative — that the task is not stalled — because what a healthy
    fleet DOES with this brief (how many steps, which agents, whether it parks on a
    question) is the journeys' subject, not this one's.
    """
    server = boot(tmp_path / "home", api_key=live_api_key)
    try:
        code, body = server.post(
            "/api/control-plane/delegate", {"brief": BRIEF, "confirm": True},
            timeout=DELEGATE_TIMEOUT_S,
        )
        assert code == 200, f"delegate failed {code}: {body!r}"
        task_id = body["task_id"]

        # Let the fleet do real work under the default $5 cap, then look. Waiting for
        # recorded spend PAST X2's tiny cap rather than for a full delivery: this only
        # needs to observe that the task progressed beyond the point where X2 stalled,
        # WITHOUT the brake firing, and a completed deliverable would cost several times
        # more for no extra evidence. Waiting for any spend at all is not enough: the first
        # recorded call (a single cheap decompose) can land under $0.001 on its own.
        #
        # Spend is polled from the STORE for the same reason X2 asserts on it: the
        # comparison below is against the cap, and the cap reads `sum_cost`. Polling the
        # HTTP figure would compare a control measured one way against a case measured
        # another.
        home = tmp_path / "home"
        poll_until(
            lambda: (lambda usd: usd if usd > TINY_CAP_USD else None)(
                _recorded_spend(home, task_id)),
            timeout_s=240, interval_s=3,
            what=f"task {task_id} to record spend past ${TINY_CAP_USD} under the default cap",
        )
        status = task_status(server, task_id)

        spent = _recorded_spend(home, task_id)
        reported = (status.get("cost") or {}).get("total_cost_usd") or 0.0
        journey_budget.note_cost(max(spent, reported))

        # The key comparison: this task has spent MORE than X2's cap, and is fine.
        assert spent > TINY_CAP_USD, (
            f"control task only spent ${spent}, which does not exceed X2's "
            f"${TINY_CAP_USD} cap — it therefore does not demonstrate that the stall "
            "in X2 was caused by the cap rather than by the spend itself"
        )
        assert (status.get("state") or {}).get("status") != "stalled", (
            f"a task spending ${spent} under the DEFAULT $5 cap stalled anyway — the "
            "fleet stalls regardless of budget, so X2 proves nothing about the cap"
        )
    finally:
        server.stop()
