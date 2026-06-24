"""Slice B: resource + cost prompts + graph wiring + CLI --resource (no network/key)."""

from __future__ import annotations

from src.agent.resource_report_graph import ResourceReportDeps, build_resource_graph
from src.llm.resource_report_prompt import (
    build_resource_slack_short,
    fallback_resource_narrative,
    render_resource_xhtml,
)
from src.tools.models import AssigneeLoad, CostSummary, ResourceReport


def _resource(*, overloaded=("Carol",), unassigned=2):
    loads = (
        AssigneeLoad("Carol", 6, 2, 1, overloaded=True),
        AssigneeLoad("Bob", 2, 0, 0, overloaded=False),
    )
    return ResourceReport(
        loads=loads, team_mean=4.0, overloaded=overloaded, unassigned_count=unassigned
    )


def _cost(*, cost_per_issue=25.0, status="warn"):
    return CostSummary(
        llm_spent=45.0, llm_cap=50.0, llm_ratio=0.9, llm_status=status,
        labor_estimate=8 * cost_per_issue, open_issue_count=8, cost_per_issue=cost_per_issue,
    )


# --- deterministic XHTML render ---


def test_render_xhtml_no_github_markdown():
    out = render_resource_xhtml(_resource(), _cost(), report_date="2026-06-22")
    assert "<table>" in out and "<h2>" in out
    assert "##" not in out and "**" not in out
    assert "<html>" not in out and "<body>" not in out


def test_render_xhtml_numbers_from_data():
    out = render_resource_xhtml(_resource(), _cost(), report_date="2026-06-22")
    assert "Carol" in out and "⚠️ quá tải" in out  # overloaded marker
    assert "$45" in out and "$50" in out and "90%" in out  # cost figures
    assert "Chưa phân công: 2 issue" in out  # unassigned line


def test_render_xhtml_escapes_assignee_name():
    evil = ResourceReport(
        loads=(AssigneeLoad("<script>alert(1)</script>", 1, 0, 0, overloaded=False),),
        team_mean=1.0, overloaded=(), unassigned_count=0,
    )
    out = render_resource_xhtml(evil, _cost(cost_per_issue=0), report_date="2026-06-22")
    assert "&lt;script&gt;" in out
    assert "<script>alert(1)</script>" not in out  # raw tag must NOT appear


def test_render_labor_line_gating():
    with_labor = render_resource_xhtml(_resource(), _cost(cost_per_issue=25), report_date="d")
    assert "nhân công" in with_labor and "ước tính" in with_labor.lower()
    without = render_resource_xhtml(_resource(), _cost(cost_per_issue=0), report_date="d")
    assert "nhân công" not in without  # omitted when cost_per_issue == 0


def test_render_no_loads():
    empty = ResourceReport(loads=(), team_mean=0.0, overloaded=(), unassigned_count=0)
    out = render_resource_xhtml(empty, _cost(cost_per_issue=0), report_date="d")
    assert "Chưa có issue nào được phân công" in out


# --- Slack short ---


def test_slack_short_mrkdwn():
    out = build_resource_slack_short(
        _resource(), _cost(), report_date="2026-06-22", detail_url="https://x/p"
    )
    assert "*Resource & Cost" in out
    assert "<https://x/p|" in out
    assert "Quá tải: Carol" in out
    assert "##" not in out and "**" not in out


def test_slack_short_no_url():
    out = build_resource_slack_short(_resource(), _cost(), report_date="d", detail_url=None)
    assert "không tạo được link" in out


def test_slack_short_sanitizes_assignee_names():
    # Jira display names are user-controlled → must not inject Slack mentions/links
    # or break mrkdwn when surfaced in the "Quá tải" line.
    evil = ResourceReport(
        loads=(AssigneeLoad("x", 6, 0, 0, overloaded=True),),
        team_mean=2.0, overloaded=("<!channel>", "*spam*"), unassigned_count=0,
    )
    out = build_resource_slack_short(evil, _cost(), report_date="d", detail_url=None)
    assert "<!channel>" not in out and "*spam*" not in out  # control chars neutralized
    assert "‹!channel›" in out  # < > replaced


def test_fallback_narrative_single_paragraph():
    out = fallback_resource_narrative(_resource(), _cost(), report_date="2026-06-22")
    assert out.startswith("<p>") and out.endswith("</p>")
    assert "Carol" in out  # overloaded name surfaced qualitatively


# --- graph wiring with fakes ---


def _fake_deps(delivered=True):
    resource, cost = _resource(), _cost()
    return ResourceReportDeps(
        fetch=lambda: (resource, cost),
        compose=lambda r, c: ("<p>tóm tắt</p><h2>RC</h2>", None),
        deliver=lambda r, c, body, approved=False: (
            delivered, "confluence=dry_run slack=dry_run url=None"),
    )


def test_resource_graph_runs_with_fakes():
    graph = build_resource_graph(deps=_fake_deps())
    out = graph.invoke({}, config={"configurable": {"thread_id": "rc-t"}})
    assert out["report_text"].startswith("<p>")
    assert out["delivered"] is True
    # overloaded names serialized into state
    assert any(r["assignee"] == "Carol" for r in out["risks"])


def test_resource_graph_compiles_without_network():
    assert build_resource_graph(deps=_fake_deps()) is not None


def test_resource_deliver_uses_resource_dedup_namespace(settings_factory, tmp_path, monkeypatch):
    """The deliver path must go through the gateway with a resource-<date> dedup key."""
    from datetime import UTC, datetime

    import src.actions.confluence_write as cw
    import src.actions.slack_write as sw
    from src.actions.action_gateway import ActionGateway, GatewayResult
    from src.actions.confluence_write import ConfluencePage
    from src.agent import resource_report_graph
    from src.audit.audit_log import AuditLog

    today = datetime.now(UTC).date().isoformat()
    gw = ActionGateway(
        settings=settings_factory(dry_run=True), audit_log=AuditLog(tmp_path / "a.jsonl")
    )
    seen_dates: list[str] = []

    def fake_create_page(title, body, *, gateway, config, report_date, rationale="",
                         approved=False):
        seen_dates.append(report_date)
        return GatewayResult(status="dry_run", summary="", approval_id=None), \
            ConfluencePage(page_id=None, url=None)

    def fake_deliver_report(text, *, gateway, config, report_date, rationale="", channel=None,
                            approved=False):
        seen_dates.append(report_date)
        return GatewayResult(status="dry_run", summary="", approval_id=None)

    monkeypatch.setattr(cw, "create_report_page", fake_create_page)
    monkeypatch.setattr(sw, "deliver_report", fake_deliver_report)

    class _Cfg:
        slack_external_channels = frozenset()

    deps = resource_report_graph.default_resource_deps(
        config=_Cfg(), settings=settings_factory(), gateway=gw
    )
    ok, summary = deps.deliver(_resource(), _cost(), "<p>body</p>")
    assert ok is True
    assert seen_dates == [f"resource-{today}", f"resource-{today}"]


# --- CLI dispatch ---


def test_parse_report_kind_resource():
    from src.entrypoints.cli import _parse_report_kind

    assert _parse_report_kind(["--resource"]) == "resource"
    assert _parse_report_kind(["--okr"]) == "okr"
    assert _parse_report_kind(["--weekly"]) == "weekly"
    assert _parse_report_kind([]) == "daily"
    # precedence: resource > okr > weekly > daily
    assert _parse_report_kind(["--resource", "--okr", "--weekly"]) == "resource"


def _fake_loaded(tmp_path, *, api_key):
    """A minimal LoadedProfile stand-in for CLI dispatch tests (no real profile dir)."""
    settings = type("S", (), {"openrouter_api_key": api_key, "data_dir": tmp_path})()
    return type(
        "LP", (),
        {"settings": settings, "config": object(), "soul": "", "project": "", "memory": "",
         "profile_id": "default"},
    )()


def test_cli_report_resource_dispatch(monkeypatch, tmp_path):
    """`report --resource` builds the resource graph."""
    import src.agent.resource_report_graph as rc_graph_mod
    from src.entrypoints import cli

    called = {}

    class _FakeGraph:
        def invoke(self, _state, config):
            called["invoked"] = True
            return {"report_text": "<p>ok</p>", "cost_usd": None,
                    "delivered": True, "delivery_summary": "s"}

    monkeypatch.setattr(cli, "load_profile", lambda pid: _fake_loaded(tmp_path, api_key="k"))
    monkeypatch.setattr(cli, "_checkpointer", lambda settings: None)
    monkeypatch.setattr(
        rc_graph_mod, "build_resource_graph",
        lambda cp, *, config=None, settings=None, context=None, audience="internal": _FakeGraph(),
    )

    rc = cli.main(["report", "--resource"])
    assert rc == 0 and called.get("invoked") is True


def test_audit_still_keyless_after_resource(monkeypatch, tmp_path):
    """Regression: non-LLM commands stay keyless after the --resource change."""
    from src.entrypoints import cli

    monkeypatch.setattr(cli, "load_profile", lambda pid: _fake_loaded(tmp_path, api_key=None))
    assert cli.main(["audit", "--limit", "1"]) == 0


def test_cron_resource_kind():
    from src.entrypoints.cron import _report_kind

    assert _report_kind(["--resource"]) == "resource"
    assert _report_kind(["--okr"]) == "okr"
    assert _report_kind(["--weekly"]) == "weekly"
    assert _report_kind([]) == "daily"
