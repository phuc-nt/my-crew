"""Slice B: audience delivery routing — channel/dedup, pending_approval, Lớp B."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.agent.audience_delivery import (
    SLACK_OK_STATUSES,
    delivery_summary,
    resolve_audience_delivery,
)

TODAY = "2026-06-22"


class _Cfg:
    """ReportingConfig stub for delivery tests. `slack_external_channels` is read
    by the graph factories when they build the gateway; `slack_stakeholder_channel`
    by `resolve_audience_delivery` on the external path."""

    def __init__(self, stakeholder):
        self.slack_stakeholder_channel = stakeholder
        self.slack_external_channels = frozenset({stakeholder} if stakeholder else set())


# --- resolve_audience_delivery: channel + dedup hint ---


def test_internal_channel_none_and_dedup_unchanged():
    channel, hint = resolve_audience_delivery("internal", "daily", TODAY, _Cfg(None))
    assert channel is None  # → default slack_report_channel (current behavior)
    assert hint == f"daily-{TODAY}"  # dedup hint UNCHANGED (backward-compat)


def test_external_routes_to_stakeholder_channel():
    channel, hint = resolve_audience_delivery("external", "okr", TODAY, _Cfg("C_STAKE"))
    assert channel == "C_STAKE"
    assert hint == f"okr-external-{TODAY}"  # audience-suffixed dedup namespace


def test_external_without_stakeholder_channel_raises():
    with pytest.raises(RuntimeError, match="SLACK_STAKEHOLDER_CHANNEL"):
        resolve_audience_delivery("external", "daily", TODAY, _Cfg(None))


# --- pending_approval = success + summary ---


def test_pending_approval_is_in_ok_statuses():
    assert "pending_approval" in SLACK_OK_STATUSES


def test_delivery_summary_surfaces_approval_id():
    class _Res:
        status = "pending_approval"
        approval_id = 7

    out = delivery_summary("executed", _Res(), "https://x/p")
    assert "slack=pending_approval" in out and "approval_id=7" in out


def test_delivery_summary_no_approval_id_when_executed():
    class _Res:
        status = "executed"
        approval_id = None

    out = delivery_summary("executed", _Res(), None)
    assert "approval_id" not in out and "slack=executed" in out


# --- graph _deliver: external returns ok on pending_approval (all 3 graphs) ---


def _gateway(settings_factory, tmp_path):
    from src.actions.action_gateway import ActionGateway
    from src.audit.audit_log import AuditLog

    return ActionGateway(
        settings=settings_factory(dry_run=True), audit_log=AuditLog(tmp_path / "a.jsonl")
    )


def _spy_writes(monkeypatch, slack_status, approval_id):
    """Patch create_report_page + deliver_report to capture channel/date + fake status."""
    import src.actions.confluence_write as cw
    import src.actions.slack_write as sw
    from src.actions.action_gateway import GatewayResult
    from src.actions.confluence_write import ConfluencePage

    seen: dict = {}

    def fake_page(title, body, *, gateway, config, report_date, rationale=""):
        seen["page_date"] = report_date
        return GatewayResult(status="dry_run", summary="", approval_id=None), \
            ConfluencePage(page_id=None, url=None)

    def fake_deliver(text, *, gateway, config, report_date, rationale="", channel=None):
        seen["slack_date"] = report_date
        seen["channel"] = channel
        return GatewayResult(status=slack_status, summary="", approval_id=approval_id)

    monkeypatch.setattr(cw, "create_report_page", fake_page)
    monkeypatch.setattr(sw, "deliver_report", fake_deliver)
    return seen


def test_okr_external_deliver_pending_is_ok(settings_factory, tmp_path, monkeypatch):
    from src.agent import okr_report_graph
    from src.agent.okr_analyzer import OkrRollup

    seen = _spy_writes(monkeypatch, "pending_approval", 9)
    gw = _gateway(settings_factory, tmp_path)
    deps = okr_report_graph.default_okr_deps(
        config=_Cfg("C_STAKE"), settings=settings_factory(), audience="external", gateway=gw
    )
    today = datetime.now(UTC).date().isoformat()
    ok, summary = deps.deliver(OkrRollup((), (), ()), "<p>body</p>")
    assert ok is True  # pending_approval is success for external
    assert seen["channel"] == "C_STAKE"
    assert seen["slack_date"] == f"okr-external-{today}"
    assert "approval_id=9" in summary


def test_resource_external_deliver_pending_is_ok(settings_factory, tmp_path, monkeypatch):
    from src.agent import resource_report_graph
    from src.tools.models import CostSummary, ResourceReport

    seen = _spy_writes(monkeypatch, "pending_approval", 3)
    gw = _gateway(settings_factory, tmp_path)
    deps = resource_report_graph.default_resource_deps(
        config=_Cfg("C_STAKE"), settings=settings_factory(), audience="external", gateway=gw
    )
    resource = ResourceReport((), 0.0, (), 0)
    cost = CostSummary(0.0, 50.0, 0.0, "ok", 0.0, 0, 0.0)
    ok, summary = deps.deliver(resource, cost, "<p>body</p>")
    assert ok is True and seen["channel"] == "C_STAKE"


def test_resource_external_short_omits_confluence_link(settings_factory, tmp_path, monkeypatch):
    """C1 fix: the external resource short must NOT link the page (it holds per-person PII)."""
    import src.actions.confluence_write as cw
    import src.actions.slack_write as sw
    from src.actions.action_gateway import GatewayResult
    from src.actions.confluence_write import ConfluencePage
    from src.agent import resource_report_graph
    from src.tools.models import AssigneeLoad, CostSummary, ResourceReport

    posted: dict = {}

    def fake_page(title, body, *, gateway, config, report_date, rationale=""):
        # The page IS created with a real URL...
        return GatewayResult(status="dry_run", summary="", approval_id=None), \
            ConfluencePage(page_id="99", url="https://wiki/internal-page")

    def fake_deliver(text, *, gateway, config, report_date, rationale="", channel=None):
        posted["text"] = text
        return GatewayResult(status="pending_approval", summary="", approval_id=1)

    monkeypatch.setattr(cw, "create_report_page", fake_page)
    monkeypatch.setattr(sw, "deliver_report", fake_deliver)
    gw = _gateway(settings_factory, tmp_path)
    deps = resource_report_graph.default_resource_deps(
        config=_Cfg("C_STAKE"), settings=settings_factory(), audience="external", gateway=gw
    )
    resource = ResourceReport(
        (AssigneeLoad("Alice", 6, 0, 0, overloaded=True),), 6.0, ("Alice",), 0
    )
    cost = CostSummary(0.0, 50.0, 0.0, "ok", 200.0, 8, 25.0)
    deps.deliver(resource, cost, "<p>body</p>")
    # ...but the stakeholder short must NOT link it, and carries no name/labor.
    assert "wiki/internal-page" not in posted["text"]
    assert "Alice" not in posted["text"] and "$200" not in posted["text"]


def test_internal_deliver_keeps_channel_none(settings_factory, tmp_path, monkeypatch):
    from src.agent import okr_report_graph
    from src.agent.okr_analyzer import OkrRollup

    seen = _spy_writes(monkeypatch, "executed", None)
    gw = _gateway(settings_factory, tmp_path)
    deps = okr_report_graph.default_okr_deps(
        config=_Cfg(None), settings=settings_factory(), audience="internal", gateway=gw
    )
    today = datetime.now(UTC).date().isoformat()
    ok, _ = deps.deliver(OkrRollup((), (), ()), "<p>body</p>")
    assert ok is True
    assert seen["channel"] is None  # internal → default channel
    assert seen["slack_date"] == f"okr-{today}"  # dedup hint UNCHANGED


# --- Lớp B integration: stakeholder channel routes through approval (no hard_block edit) ---


def test_external_channel_routes_to_lop_b(settings_factory, tmp_path, monkeypatch):
    """deliver_report to a channel in external_channels → pending_approval (Lớp B).

    Real gateway + real hard_block (no edit needed); only the MCP post handler is
    faked. Confirms the stakeholder channel reaches Lớp B purely via channel selection.
    """
    from src.actions import slack_write
    from src.actions.action_gateway import ActionGateway
    from src.audit.audit_log import AuditLog

    class _SlackCfg:
        slack_report_channel = "C-default"
        slack_server = None

    monkeypatch.setattr(slack_write, "make_slack_post_handler", lambda s: lambda a: "posted")
    gw = ActionGateway(
        settings=settings_factory(dry_run=False),
        audit_log=AuditLog(tmp_path / "a.jsonl"),
        external_channels=frozenset({"C_STAKE"}),
    )
    result = slack_write.deliver_report(
        "hi stakeholders", gateway=gw, config=_SlackCfg(), channel="C_STAKE",
        report_date="daily-external-2026-06-22",
    )
    assert result.status == "pending_approval"
    assert gw.pending_approvals()  # queued for human approval


# --- CLI / cron parsing ---


def test_cli_parse_audience():
    from src.entrypoints.cli import _parse_audience

    assert _parse_audience(["--audience", "external"]) == "external"
    assert _parse_audience(["--audience", "internal"]) == "internal"
    assert _parse_audience([]) == "internal"
    assert _parse_audience(["--audience", "bogus"]) == "internal"


def test_cron_audience():
    from src.entrypoints.cron import _audience

    assert _audience(["--resource", "--audience", "external"]) == "external"
    assert _audience([]) == "internal"


# --- approved external action actually dispatches to its live handler ---


def test_approved_slack_action_dispatches_to_live_handler(monkeypatch):
    """approve <id> of an external report must POST (not just authorize)."""
    from src.actions import slack_write
    from src.config import config_builders
    from src.entrypoints.cli import _dispatch_approved_action

    posted: dict = {}

    class _SlackCfg:
        slack_server = None

    # The dispatch builds config from env then a handler from its slack_server;
    # stub both so no .env is read and the post is captured.
    monkeypatch.setattr(config_builders, "build_reporting_config_from_env", lambda: _SlackCfg())
    monkeypatch.setattr(
        slack_write, "make_slack_post_handler",
        lambda s: lambda a: posted.update(a) or "posted ts=1",
    )
    action = {
        "type": "mcp_tool", "server": "slack", "tool": "post_message",
        "args": {"channel": "C_STAKE", "text": "stakeholder update"},
    }
    out = _dispatch_approved_action(action)
    assert out == "posted ts=1"
    assert posted["args"]["channel"] == "C_STAKE"  # the real post handler ran


def test_approved_unknown_action_raises():
    from src.entrypoints.cli import _dispatch_approved_action

    with pytest.raises(RuntimeError, match="No live handler"):
        _dispatch_approved_action({"type": "gh", "argv": ["pr", "merge"]})


# --- weekly external drops embedded okr/resource sub-sections ---


def test_weekly_external_omits_embedded_sections(settings_factory, monkeypatch):
    import src.agent.okr_weekly_section as okr_ws
    import src.agent.resource_weekly_section as res_ws
    from src.agent import report_graph

    monkeypatch.setattr(okr_ws, "weekly_okr_section", lambda d, config: "<h2>OKR-MARKER</h2>")
    monkeypatch.setattr(
        res_ws, "weekly_resource_section", lambda d, config, settings: "<h2>RES-MARKER</h2>"
    )

    class _FakeLlm:
        def complete(self, messages):
            from src.llm.client import LlmResult
            return LlmResult(content="<p>weekly</p>", model="m",
                             prompt_tokens=0, completion_tokens=0, cost_usd=0.0)

    deps_ext = report_graph.default_report_deps(
        config=_Cfg(None), settings=settings_factory(),
        report_kind="weekly", audience="external", client=_FakeLlm(),
    )
    body_ext, _ = deps_ext.compose([])
    assert "OKR-MARKER" not in body_ext and "RES-MARKER" not in body_ext  # dropped

    deps_int = report_graph.default_report_deps(
        config=_Cfg(None), settings=settings_factory(),
        report_kind="weekly", audience="internal", client=_FakeLlm(),
    )
    body_int, _ = deps_int.compose([])
    assert "OKR-MARKER" in body_int and "RES-MARKER" in body_int  # internal keeps them
