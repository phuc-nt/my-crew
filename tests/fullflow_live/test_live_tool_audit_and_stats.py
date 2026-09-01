"""L3/L5 — every real tool call leaves an audit row, and the stats table counts them.

Phase 3 made the policy shim in `read_only_toolset` write one audit row per read-tool
call; Phase 5 added `collect_tool_stats`, which derives a per-tool tally from those rows
and nothing else. Both are pinned offline against synthesised trails. What offline cannot
show is that the rows a REAL loop produces carry the identity fields — task, step,
iteration, actor — that make the trail auditable. Those come from an ambient
`ToolCallContext` set up several layers away from the shim, which is exactly the kind of
wiring a synthesised row cannot exercise.

Both cases ride ONE journey rather than one each. The trail and the stats are two views of
the same rows, so a second paid run would buy no additional coverage — and `collect_tool_stats`
reading the same file the shim wrote is precisely the invariant L5 exists to check. That
sharing needs `scope="module"` on the fleet and the run: at the default function scope each
case quietly got its own fleet and its own delegate, so the two views were of two DIFFERENT
runs and the cross-check was hollow while still reporting green.

**Same fleet seam as the cost-cap cases, for the same measured reason.** A default-seeded
fleet is entirely native, and the native tier binds no read toolset at all — so the shim
never runs and the trail stays empty. `tools_tier` is what makes any of this observable;
`effective_runtime` on the work order is how each case proves it happened.
"""

from __future__ import annotations

import pytest

from tests.fullflow_live.topology import (
    audit_rows,
    boot,
    seed_home,
    transcript_events,
    wait_until_settled,
    work_orders,
)

#: Same agent the cost-cap cases promote. Deliberately not the coordinator: the tools tier
#: is for work steps, and keeping planning native leaves the journey's shape comparable to
#: every other live case.
TOOL_AGENT = "analyst"

#: The `action_type` the shim stamps. Imported rather than re-typed would couple this case
#: to a constant it does not own; the literal is what an external auditor would grep for,
#: and a rename should surface here as a failure to investigate, not a silent pass.
READ_CALL_ACTION = "mcp_tool_read"

#: Multi-stage so it reaches the team lane (a lookup-shaped brief routes to sprint, which
#: runs native and binds no tools) and research-shaped so the loop has a reason to call
#: `academic.search` more than once. Pinned offline by
#: `test_the_live_tool_audit_brief_still_reaches_the_team_lane`.
BRIEF = (
    "Nghiên cứu rồi lập báo cáo trong tuần về đánh giá chất lượng mô hình ngôn ngữ: "
    "(1) tra cứu hai phương pháp đánh giá tự động phổ biến, mỗi phương pháp kèm nguồn, "
    "(2) tra cứu hai hạn chế đã được ghi nhận của các phương pháp đó, kèm nguồn, "
    "(3) tổng hợp thành bảng và đề xuất 2 việc cần làm tuần sau."
)


@pytest.fixture(scope="module")
def tool_fleet(tmp_path_factory, live_api_key_module):
    """`analyst` on the tools tier, no spend ceiling — the loop should run to its natural end.

    Module-scoped so both cases share ONE fleet, for the same reason `tool_journey` is:
    a per-case fleet would mean a per-case journey.
    """
    home = tmp_path_factory.mktemp("tool_audit") / "home"
    seed_home(home, api_key=live_api_key_module, tools_tier={TOOL_AGENT})
    server = boot(home, api_key=live_api_key_module, seed=False)
    try:
        yield server
    finally:
        server.stop()


#: Above the 900s most of the live suite uses, and set by autopsy rather than by taste.
#:
#: Sample 2 (2026-09-01) timed out at 900s, and the store it left behind shows the run was
#: never stuck: `step_1`/`step_2` both `done`, `step_3` still `running` with a heartbeat at
#: 02:10:38 — i.e. alive and reporting right up to the moment the poll gave up. Nothing had
#: failed; the deadline simply landed mid-journey. (Sample 1 passed, so the two samples
#: bracket the real distribution rather than showing a regression.)
#:
#: This module is structurally near the top of the suite's cost: one research brief that
#: fans into a 3-step DAG, where `step_3` joins BOTH predecessors and so cannot start until
#: the two research steps finish. Raising the wait weakens no assertion — L3 and L5 both
#: measure the audit trail against the transcript of whatever run happened — it only stops
#: the poll from ending a run that was still making progress.
SETTLE_TIMEOUT_S = 1500


@pytest.fixture(scope="module")
def _tool_journey_run(tool_fleet):
    """Run BRIEF exactly once for the whole module.

    Module-scoped, and that is load-bearing rather than an optimisation. Under the default
    function scope each case got its OWN fleet and its OWN delegate, so the two cases were
    reading two different runs while the docstring claimed they cross-checked one — which
    is precisely the failure L5 exists to detect, reintroduced in the harness itself.
    Measured: a run of this file paid for two full research journeys (~28 min) instead of one.
    """
    code, body = tool_fleet.post(
        "/api/control-plane/delegate", {"brief": BRIEF, "confirm": True}, timeout=900
    )
    assert code == 200, f"delegate failed {code}: {body!r}"
    task_id = body.get("task_id")
    assert task_id, f"delegate returned no task_id: {body!r}"

    status = wait_until_settled(tool_fleet, task_id, timeout_s=SETTLE_TIMEOUT_S)
    return task_id, status


@pytest.fixture
def tool_journey(tool_fleet, _tool_journey_run, journey_budget):
    """Hand both cases the same settled task, and bill each case's own budget.

    `journey_budget` stays function-scoped — it is shared with every other live journey
    file and keys its baseline row off `request.node.name` — so the spend of the one real
    run is noted once per case. The run itself happens only once.
    """
    task_id, status = _tool_journey_run
    journey_budget.note_cost(
        (status.get("cost") or {}).get("total_cost_usd") or 0.0, status
    )

    orders = work_orders(tool_fleet.home, task_id)
    tools_tier = [o for o in orders if o.get("effective_runtime") == "ToolCallingRuntime"]
    assert tools_tier, (
        f"no step of task {task_id} resolved onto ToolCallingRuntime, so the read toolset "
        "was never bound and no shim ran — every assertion below would be vacuous. "
        f"resolved={[(o.get('step_id'), o.get('effective_runtime')) for o in orders]!r}"
    )
    return tool_fleet.home, task_id, tools_tier


@pytest.mark.live_slow
def test_l3_every_real_tool_call_lands_on_the_audit_trail_with_its_context(tool_journey):
    """A live loop's tool calls are recorded with the identity an auditor needs.

    The identity fields are the point. `verdict` and `tool` are set right at the shim and
    would survive almost any refactor; `task_id`, `step_id`, `iteration` and `actor` travel
    through the ambient `ToolCallContext`, set far from the shim, and are what breaks
    silently. A trail of rows that cannot say WHICH step made a call is not an audit trail.
    """
    home, task_id, _orders = tool_journey

    rows = [r for r in audit_rows(home) if r.get("action_type") == READ_CALL_ACTION]
    assert rows, (
        f"a step ran on ToolCallingRuntime but the trail at {home}/.data/audit/audit.jsonl "
        f"has no {READ_CALL_ACTION!r} rows. Either the model called no tool at all, or the "
        "shim stopped recording."
    )

    ours = [r for r in rows if (r.get("params") or {}).get("task_id") == task_id]
    assert ours, (
        f"{len(rows)} tool-call rows were written but none carries task_id={task_id!r}. The "
        "ambient ToolCallContext is not reaching the shim, so the trail cannot attribute a "
        f"call to the work that made it. sample={rows[0]!r}"
    )

    for row in ours:
        params = row.get("params") or {}
        assert row.get("tool"), f"audit row with no tool name: {row!r}"
        assert row.get("verdict") in ("allow", "deny"), f"unknown verdict: {row!r}"
        assert row.get("actor") == TOOL_AGENT, (
            f"row attributed to {row.get('actor')!r}, expected {TOOL_AGENT!r}: {row!r}"
        )
        assert params.get("step_id"), f"audit row with no step_id: {row!r}"
        assert isinstance(params.get("iteration"), int), (
            f"iteration missing or not an int — the loop round is what distinguishes a "
            f"retry from a fresh call: {row!r}"
        )
        assert isinstance(params.get("elapsed_ms"), int), f"no elapsed_ms: {row!r}"


@pytest.mark.live_slow
def test_l5_the_stats_table_counts_exactly_the_calls_the_transcript_recorded(tool_journey):
    """`collect_tool_stats` agrees with the loop's own transcript, call for call.

    Two independent writers, one truth: `thin_tool_loop` records `{"t": "tool_call"}` per
    invocation on the step transcript, while the shim writes an audit row from inside the
    tool wrapper. They are wired in different modules and neither reads the other, so a
    mismatch means one of them is missing calls — the failure mode a derived tally exists
    to make visible. `tool_stats`'s own docstring is explicit that there is deliberately no
    second counter for exactly this reason; this case checks that decision holds live.

    Denials are excluded from the comparison: a policy-blocked call is recorded by the shim
    but `thin_tool_loop` records `tool_call` before dispatch, so both counts include it —
    the arithmetic stays honest either way, and asserting on the breakdown separately keeps
    a denial from masquerading as a served read.
    """
    from my_crew.audit.tool_stats import collect_tool_stats
    from tests.fullflow_live.topology import audit_path

    home, task_id, orders = tool_journey

    recorded = [
        e
        for order in orders
        for e in transcript_events(home, task_id, str(order.get("transcript") or ""))
        if e.get("t") == "tool_call"
    ]
    assert recorded, (
        "the tools-tier step's transcript records no tool_call events, so the model never "
        "used a tool and there is nothing for the stats table to agree with. The step had "
        "academic.search and web.scrape bound; a run where it used neither cannot "
        "cross-check two counters."
    )

    stats = collect_tool_stats(audit_path(home), actor=TOOL_AGENT)
    assert stats, (
        f"{len(recorded)} tool calls are on the transcript but collect_tool_stats returned "
        f"nothing for actor={TOOL_AGENT!r} — the derived view has lost the rows the shim wrote"
    )

    counted = sum(s.total_calls for s in stats)
    assert counted == len(recorded), (
        f"the stats table counts {counted} calls, the transcript recorded {len(recorded)}. "
        "These are two independent writers over the same events, so a mismatch means one is "
        f"dropping calls. per-tool={[(s.tool, s.total_calls) for s in stats]!r} "
        f"transcript={[e.get('name') for e in recorded]!r}"
    )

    for stat in stats:
        assert stat.successes + stat.failures + stat.denied == stat.total_calls, (
            f"{stat.tool}'s breakdown does not sum to its total: {stat!r}. Phase 5 counts a "
            "policy denial separately from a body failure precisely so they stay "
            "distinguishable; a total that does not reconcile means one bucket is being "
            "double-counted."
        )
