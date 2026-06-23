"""Slice C: weekly-embedded resource+cost section (fault-isolated, no network)."""

from __future__ import annotations

from src.tools.models import AssigneeLoad, CostSummary, ResourceReport


def _snapshot(config, settings):
    resource = ResourceReport(
        loads=(AssigneeLoad("Carol", 6, 2, 1, overloaded=True),),
        team_mean=6.0, overloaded=("Carol",), unassigned_count=1,
    )
    cost = CostSummary(
        llm_spent=10.0, llm_cap=50.0, llm_ratio=0.2, llm_status="ok",
        labor_estimate=0.0, open_issue_count=6, cost_per_issue=0.0,
    )
    return resource, cost


class _ResCfg:
    """ReportingConfig stub: the field the weekly resource helpers read, plus
    `slack_external_channels` for the compose-driver tests that let
    `default_report_deps` build a real gateway."""

    def __init__(self, key):
        self.jira_project_key = key
        self.slack_external_channels = frozenset()


def test_section_omitted_when_unconfigured(settings_factory):
    from src.agent import resource_weekly_section as rws

    settings = settings_factory()
    assert rws.weekly_resource_section("2026-06-22", _ResCfg(None), settings) == ""
    assert rws.weekly_resource_slack_line(_ResCfg(None), settings) == ""


def test_section_rendered_when_configured(settings_factory, monkeypatch):
    from src.agent import resource_weekly_section as rws

    settings = settings_factory()
    monkeypatch.setattr(rws, "build_resource_rollup", _snapshot)
    out = rws.weekly_resource_section("2026-06-22", _ResCfg("SCRUM"), settings)
    assert "<table>" in out and "Carol" in out
    assert "Chi phí" in out  # cost block present
    line = rws.weekly_resource_slack_line(_ResCfg("SCRUM"), settings)
    assert "Resource: 1 người" in line and "1 quá tải" in line


def test_section_survives_fetch_failure(settings_factory, monkeypatch):
    from src.agent import resource_weekly_section as rws

    settings = settings_factory()

    def boom(config, settings):
        raise RuntimeError("jira down")

    monkeypatch.setattr(rws, "build_resource_rollup", boom)
    out = rws.weekly_resource_section("2026-06-22", _ResCfg("SCRUM"), settings)
    assert "Không lấy được dữ liệu resource/cost" in out  # note, not a raise
    assert "jira down" not in out  # raw exception text must NOT leak
    # slack line empty on failure
    assert rws.weekly_resource_slack_line(_ResCfg("SCRUM"), settings) == ""


def test_assignee_escaped_in_weekly_section(settings_factory, monkeypatch):
    from src.agent import resource_weekly_section as rws

    settings = settings_factory()
    evil = ResourceReport(
        loads=(AssigneeLoad("<script>x</script>", 1, 0, 0, overloaded=False),),
        team_mean=1.0, overloaded=(), unassigned_count=0,
    )
    cost = CostSummary(0.0, 50.0, 0.0, "ok", 0.0, 1, 0.0)
    monkeypatch.setattr(rws, "build_resource_rollup", lambda config, settings: (evil, cost))
    out = rws.weekly_resource_section("2026-06-22", _ResCfg("SCRUM"), settings)
    assert "&lt;script&gt;" in out and "<script>x</script>" not in out


# --- regression: weekly still embeds the OKR section alongside resource ---


def test_weekly_compose_includes_both_okr_and_resource(settings_factory, monkeypatch):
    """The resource hook must not displace the OKR hook in the weekly report."""
    import src.agent.okr_weekly_section as okr_ws
    import src.agent.resource_weekly_section as res_ws
    from src.agent import report_graph

    # Patch the two weekly section helpers to known markers, then drive _compose.
    monkeypatch.setattr(okr_ws, "weekly_okr_section", lambda d, config: "<h2>OKR-MARKER</h2>")
    monkeypatch.setattr(
        res_ws, "weekly_resource_section", lambda d, config, settings: "<h2>RES-MARKER</h2>"
    )

    class _FakeLlm:
        def complete(self, messages):
            from src.llm.client import LlmResult
            return LlmResult(content="<p>weekly</p>", model="m",
                             prompt_tokens=0, completion_tokens=0, cost_usd=0.0)

    deps = report_graph.default_report_deps(
        config=_ResCfg("SCRUM"), settings=settings_factory(),
        report_kind="weekly", client=_FakeLlm(),
    )
    body, _cost = deps.compose([])  # empty risks; weekly sections appended after
    assert "OKR-MARKER" in body and "RES-MARKER" in body


def test_daily_compose_has_no_resource_section(settings_factory, monkeypatch):
    """Daily report must not include the resource section (hook is weekly-only)."""
    import src.agent.resource_weekly_section as res_ws
    from src.agent import report_graph

    monkeypatch.setattr(
        res_ws, "weekly_resource_section", lambda d, config, settings: "<h2>RES-MARKER</h2>"
    )

    class _FakeLlm:
        def complete(self, messages):
            from src.llm.client import LlmResult
            return LlmResult(content="<p>daily</p>", model="m",
                             prompt_tokens=0, completion_tokens=0, cost_usd=0.0)

    deps = report_graph.default_report_deps(
        config=_ResCfg("SCRUM"), settings=settings_factory(),
        report_kind="daily", client=_FakeLlm(),
    )
    body, _cost = deps.compose([])
    assert "RES-MARKER" not in body
