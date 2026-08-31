"""Which tool is failing, and which is slow — counted from the audit trail.

The rows come from one writer (the policy shim, Phase 3); this module only reads them.
So most of these tests drive REAL calls through the shim rather than hand-writing rows:
a test that fabricates its own input would keep passing after the writer's format drifted,
which is the one failure an aggregate-over-a-log is actually prone to.

The distinction the tally exists to make: a policy DENIAL never ran, a FAILURE ran and
broke. Same "allow"/"deny" verdict field cannot express the second one, so conflating
them would hide exactly the tool that needs fixing.
"""

from __future__ import annotations

import pytest

from my_crew.audit.tool_stats import (
    ToolStats,
    collect_tool_stats,
    render_tool_stats,
)
from my_crew.runtime_backends.read_only_toolset import ToolPolicyError, _shim


@pytest.fixture
def trail(monkeypatch, tmp_path):
    """Point the shared team-tasks root at tmp_path; hand back the trail path."""
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    return tmp_path / "audit" / "audit.jsonl"


def _ok_tool(name="history.search", value="kết quả"):
    return _shim(name, lambda args: value)


def _failing_tool(name="jira.issues", exc=None):
    def _boom(args):
        raise exc or RuntimeError("hết giờ chờ mạng")

    return _shim(name, _boom)


# --- counting ok vs failed vs denied ----------------------------------------------------


def test_a_served_call_counts_as_a_success(trail):
    _ok_tool()({})

    stats = collect_tool_stats(trail)
    assert [(s.tool, s.total_calls, s.successes, s.failures) for s in stats] == [
        ("history.search", 1, 1, 0)
    ]


def test_a_tool_whose_body_raises_counts_as_a_failure_not_a_success(trail):
    """The whole point of the phase. The policy verdict is "allow" for this row — classify
    did allow it — so a tally reading only the verdict would call a broken tool healthy."""
    _failing_tool()({})

    stat = collect_tool_stats(trail)[0]
    assert (stat.failures, stat.successes, stat.denied) == (1, 0, 0)


def test_a_policy_denial_is_counted_apart_from_a_body_failure(trail, monkeypatch):
    """A denied call never ran; a failed call ran and broke. Different problems, different
    fixes — summing them would point an operator at the wrong one."""
    monkeypatch.setattr(
        "my_crew.runtime_backends.read_only_toolset._classify_ok",
        lambda name, args: (_ for _ in ()).throw(ToolPolicyError("credential")),
    )
    # The refusal degrades to a "⚠️ bị từ chối" string for the model (`tool_error_guard`),
    # so nothing propagates here — but the denial is still on the trail.
    out = _shim("jira.issues", lambda args: "không bao giờ chạy")({})
    assert "bị từ chối" in out

    stat = collect_tool_stats(trail)[0]
    assert (stat.denied, stat.failures, stat.successes) == (1, 0, 0)


def test_a_mixed_run_tallies_each_tool_separately(trail):
    ok = _ok_tool()
    bad = _failing_tool()
    for _ in range(3):
        ok({})
    for _ in range(2):
        bad({})

    by_tool = {s.tool: s for s in collect_tool_stats(trail)}
    assert (by_tool["history.search"].successes, by_tool["history.search"].failures) == (3, 0)
    assert (by_tool["jira.issues"].successes, by_tool["jira.issues"].failures) == (0, 2)


def test_total_calls_counts_every_attempt(trail):
    _ok_tool()({})
    _failing_tool("history.search")({})

    stat = collect_tool_stats(trail)[0]
    assert stat.total_calls == 2
    assert stat.successes + stat.failures + stat.denied == stat.total_calls


# --- the tool keeps working ------------------------------------------------------------


def test_measuring_a_tool_does_not_change_what_it_returns(trail):
    assert _ok_tool(value="dữ liệu thật")({}) == "dữ liệu thật"


def test_a_failing_tool_still_degrades_to_a_message_rather_than_raising(trail):
    """`tool_error_guard` wraps the shim; adding the outcome capture must not turn a
    degraded failure back into an exception that kills the loop."""
    out = _failing_tool()({})
    assert isinstance(out, str) and "⚠️" in out


# --- durations --------------------------------------------------------------------------


def test_the_average_duration_is_reported_for_calls_that_ran(trail):
    for _ in range(3):
        _ok_tool()({})

    stat = collect_tool_stats(trail)[0]
    assert stat.avg_duration_ms >= 0.0


def test_a_tool_with_no_recorded_duration_reports_zero_not_a_crash(trail):
    trail.parent.mkdir(parents=True, exist_ok=True)
    trail.write_text(
        '{"action_type": "mcp_tool_read", "tool": "x.y", "verdict": "allow", '
        '"reason": "", "params": {}, "result_summary": "ok", "actor": ""}\n',
        encoding="utf-8",
    )
    assert collect_tool_stats(trail)[0].avg_duration_ms == 0.0


# --- error patterns ---------------------------------------------------------------------


def test_a_repeated_denial_reason_surfaces_as_a_pattern(trail, monkeypatch):
    monkeypatch.setattr(
        "my_crew.runtime_backends.read_only_toolset._classify_ok",
        lambda name, args: (_ for _ in ()).throw(ToolPolicyError("credential trong tham số")),
    )
    guarded = _shim("jira.issues", lambda args: "x")
    for _ in range(3):
        guarded({})

    reason, count = collect_tool_stats(trail)[0].common_errors[0]
    assert count == 3
    assert "credential" in reason


def test_only_the_top_reasons_are_kept(trail):
    trail.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        '{"action_type": "mcp_tool_read", "tool": "x.y", "verdict": "deny", '
        f'"reason": "lý do {i}", "params": {{}}, "actor": ""}}'
        for i in range(6)
    ]
    trail.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert len(collect_tool_stats(trail)[0].common_errors) == 3


# --- what is NOT counted ----------------------------------------------------------------


def test_rows_from_other_action_types_are_ignored(trail):
    """The shared trail also carries gateway writes and `web.search`. Counting those as
    tool calls would inflate every number on the table."""
    _ok_tool()({})
    with trail.open("a", encoding="utf-8") as fh:
        fh.write('{"action_type": "mcp_tool", "tool": "confluence:updatePage", '
                 '"verdict": "allow", "params": {}, "actor": ""}\n')

    stats = collect_tool_stats(trail)
    assert [s.tool for s in stats] == ["history.search"]


def test_a_row_written_before_outcomes_existed_is_not_counted_as_a_failure(trail):
    """Older rows carry no `result_summary`. Reading absent as "error" would invent a
    failure spike out of missing data."""
    trail.parent.mkdir(parents=True, exist_ok=True)
    trail.write_text(
        '{"action_type": "mcp_tool_read", "tool": "x.y", "verdict": "allow", '
        '"reason": "", "params": {"elapsed_ms": 5}, "actor": ""}\n',
        encoding="utf-8",
    )
    stat = collect_tool_stats(trail)[0]
    assert (stat.successes, stat.failures) == (1, 0)


def test_a_missing_trail_is_empty_not_an_error(tmp_path):
    assert collect_tool_stats(tmp_path / "nope.jsonl") == []


def test_a_corrupt_line_does_not_sink_the_whole_report(trail):
    _ok_tool()({})
    with trail.open("a", encoding="utf-8") as fh:
        fh.write("{ đây không phải json\n")

    assert collect_tool_stats(trail)[0].total_calls == 1


# --- filters ----------------------------------------------------------------------------


def test_stats_can_be_scoped_to_one_agent(trail):
    from my_crew.runtime_backends.tool_call_context import tool_call_context

    with tool_call_context(agent_id="analyst", task_id="t1", step_id="s1"):
        _ok_tool()({})
    with tool_call_context(agent_id="writer", task_id="t1", step_id="s1"):
        _ok_tool()({})
        _ok_tool()({})

    assert collect_tool_stats(trail, actor="writer")[0].total_calls == 2
    assert collect_tool_stats(trail, actor="analyst")[0].total_calls == 1


# --- ordering and rendering -------------------------------------------------------------


def test_the_worst_tool_is_listed_first(trail):
    """An operator scans the top of the table; burying the broken tool under healthy ones
    defeats the point of aggregating at all."""
    for _ in range(4):
        _ok_tool("history.search")({})
    for _ in range(3):
        _failing_tool("jira.issues")({})

    assert [s.tool for s in collect_tool_stats(trail)][0] == "jira.issues"


def test_the_failure_rate_counts_both_ways_a_call_can_come_back_empty():
    stat = ToolStats(tool="x", total_calls=4, successes=1, failures=2, denied=1)
    assert stat.failure_rate == 0.75


def test_the_failure_rate_of_an_unused_tool_is_zero_not_a_division_error():
    assert ToolStats(tool="x").failure_rate == 0.0


def test_the_table_names_each_tool_and_its_counts(trail):
    _ok_tool()({})
    _failing_tool()({})

    text = render_tool_stats(collect_tool_stats(trail))
    assert "history.search" in text and "jira.issues" in text


def test_an_empty_report_says_so_rather_than_printing_a_bare_header():
    """A lone header reads as "all tools healthy" — the opposite of "nothing recorded"."""
    assert "Chưa có" in render_tool_stats([])
