"""Slice C: weekly-embedded resource+cost section (fault-isolated, no network)."""

from __future__ import annotations

from src.tools.models import AssigneeLoad, CostSummary, ResourceReport


def _snapshot():
    resource = ResourceReport(
        loads=(AssigneeLoad("Carol", 6, 2, 1, overloaded=True),),
        team_mean=6.0, overloaded=("Carol",), unassigned_count=1,
    )
    cost = CostSummary(
        llm_spent=10.0, llm_cap=50.0, llm_ratio=0.2, llm_status="ok",
        labor_estimate=0.0, open_issue_count=6, cost_per_issue=0.0,
    )
    return resource, cost


def _set_project(monkeypatch, *, key):
    """Monkeypatch the reporting config so the weekly resource helpers see a project key."""
    import src.config.reporting_config as rc
    from src.agent import resource_weekly_section

    class _Cfg:
        jira_project_key = key

    monkeypatch.setattr(rc, "get_reporting_config", lambda: _Cfg())
    return resource_weekly_section


def test_section_omitted_when_unconfigured(monkeypatch):
    rws = _set_project(monkeypatch, key=None)
    assert rws.weekly_resource_section("2026-06-22") == ""
    assert rws.weekly_resource_slack_line() == ""


def test_section_rendered_when_configured(monkeypatch):
    rws = _set_project(monkeypatch, key="SCRUM")
    monkeypatch.setattr(rws, "build_resource_rollup", _snapshot)
    out = rws.weekly_resource_section("2026-06-22")
    assert "<table>" in out and "Carol" in out
    assert "Chi phí" in out  # cost block present
    line = rws.weekly_resource_slack_line()
    assert "Resource: 1 người" in line and "1 quá tải" in line


def test_section_survives_fetch_failure(monkeypatch):
    rws = _set_project(monkeypatch, key="SCRUM")

    def boom():
        raise RuntimeError("jira down")

    monkeypatch.setattr(rws, "build_resource_rollup", boom)
    out = rws.weekly_resource_section("2026-06-22")
    assert "Không lấy được dữ liệu resource/cost" in out  # note, not a raise
    assert "jira down" not in out  # raw exception text must NOT leak
    assert rws.weekly_resource_slack_line() == ""  # slack line empty on failure


def test_assignee_escaped_in_weekly_section(monkeypatch):
    rws = _set_project(monkeypatch, key="SCRUM")
    evil = ResourceReport(
        loads=(AssigneeLoad("<script>x</script>", 1, 0, 0, overloaded=False),),
        team_mean=1.0, overloaded=(), unassigned_count=0,
    )
    cost = CostSummary(0.0, 50.0, 0.0, "ok", 0.0, 1, 0.0)
    monkeypatch.setattr(rws, "build_resource_rollup", lambda: (evil, cost))
    out = rws.weekly_resource_section("2026-06-22")
    assert "&lt;script&gt;" in out and "<script>x</script>" not in out


# --- regression: weekly still embeds the OKR section alongside resource ---


def test_weekly_compose_includes_both_okr_and_resource(monkeypatch):
    """The resource hook must not displace the OKR hook in the weekly report."""
    import src.agent.okr_weekly_section as okr_ws
    import src.agent.resource_weekly_section as res_ws
    from src.agent import report_graph

    # Patch the two weekly section helpers to known markers, then drive _compose.
    monkeypatch.setattr(okr_ws, "weekly_okr_section", lambda d: "<h2>OKR-MARKER</h2>")
    monkeypatch.setattr(res_ws, "weekly_resource_section", lambda d: "<h2>RES-MARKER</h2>")

    class _FakeLlm:
        def complete(self, messages):
            from src.llm.client import LlmResult
            return LlmResult(content="<p>weekly</p>", model="m",
                             prompt_tokens=0, completion_tokens=0, cost_usd=0.0)

    deps = report_graph.default_report_deps(report_kind="weekly", client=_FakeLlm())
    body, _cost = deps.compose([])  # empty risks; weekly sections appended after
    assert "OKR-MARKER" in body and "RES-MARKER" in body


def test_daily_compose_has_no_resource_section(monkeypatch):
    """Daily report must not include the resource section (hook is weekly-only)."""
    import src.agent.resource_weekly_section as res_ws
    from src.agent import report_graph

    monkeypatch.setattr(res_ws, "weekly_resource_section",
                        lambda d: "<h2>RES-MARKER</h2>")

    class _FakeLlm:
        def complete(self, messages):
            from src.llm.client import LlmResult
            return LlmResult(content="<p>daily</p>", model="m",
                             prompt_tokens=0, completion_tokens=0, cost_usd=0.0)

    deps = report_graph.default_report_deps(report_kind="daily", client=_FakeLlm())
    body, _cost = deps.compose([])
    assert "RES-MARKER" not in body
