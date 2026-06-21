"""Slack write through the gateway + report graph wiring + dedup-hint."""

from __future__ import annotations

from datetime import date

import pytest

from src.actions import slack_write
from src.actions.action_gateway import ActionGateway
from src.actions.slack_write import _dedup_key, deliver_report
from src.agent.report_graph import ReportDeps, build_report_graph
from src.audit.audit_log import AuditLog
from src.tools.models import CiRun, Issue, PullRequest, Risk


def _gateway(settings_factory, tmp_path, **kw):
    return ActionGateway(
        settings=settings_factory(**kw), audit_log=AuditLog(tmp_path / "audit.jsonl")
    )


def test_dedup_key_stable_per_day_channel():
    assert _dedup_key("C1", "2026-06-21") == _dedup_key("C1", "2026-06-21")
    assert _dedup_key("C1", "2026-06-21") != _dedup_key("C1", "2026-06-22")


def test_deliver_report_dry_run_skips_post(settings_factory, tmp_path, monkeypatch):
    posted = []
    monkeypatch.setattr(slack_write, "_slack_post_handler", lambda a: posted.append(a) or "ok")
    gw = _gateway(settings_factory, tmp_path, dry_run=True)
    result = deliver_report("hi", gateway=gw, channel="C1", report_date="2026-06-21")
    assert result.status == "dry_run"
    assert posted == []  # handler not called under dry-run


def test_deliver_report_dedup_same_day(settings_factory, tmp_path, monkeypatch):
    posted = []
    monkeypatch.setattr(slack_write, "_slack_post_handler", lambda a: posted.append(a) or "ok")
    gw = _gateway(settings_factory, tmp_path, dry_run=False)
    r1 = deliver_report("report A", gateway=gw, channel="C1", report_date="2026-06-21")
    r2 = deliver_report("report B different", gateway=gw, channel="C1", report_date="2026-06-21")
    assert r1.status == "executed"
    assert r2.status == "deduplicated"  # different text, same day -> not re-posted
    assert len(posted) == 1


def test_deliver_report_empty_text_raises(settings_factory, tmp_path):
    gw = _gateway(settings_factory, tmp_path)
    with pytest.raises(ValueError, match="empty"):
        deliver_report("   ", gateway=gw, channel="C1", report_date="2026-06-21")


def test_dedup_hint_isolated_per_tool(settings_factory, tmp_path):
    # M1: same hint string on DIFFERENT tools must NOT collide/dedup together.
    gw = _gateway(settings_factory, tmp_path, dry_run=False)
    a = {"type": "mcp_tool", "server": "slack", "tool": "post_message",
         "args": {"channel": "C1", "text": "x"}, "dedup_hint": "h"}
    b = {"type": "mcp_tool", "server": "slack", "tool": "update_message",
         "args": {"channel": "C1", "ts": "1", "text": "y"}, "dedup_hint": "h"}
    r1 = gw.execute(a, handler=lambda _a: "ok")
    r2 = gw.execute(b, handler=lambda _a: "ok")
    assert r1.status == "executed"
    assert r2.status == "executed"  # different tool, same hint -> NOT deduped


def _fake_deps():
    return ReportDeps(
        fetch_issues=lambda: [Issue(key="AB-1", summary="x", status="In Progress",
                                    assignee="P", due_date=date(2026, 6, 1), labels=("blocked",))],
        fetch_prs=lambda: [PullRequest(number=9, title="y", author="p", updated_at=date(2026, 6, 1),
                                       review_decision=None, checks_state="FAILURE",
                                       age_days=20, stale=True)],
        fetch_ci=lambda: [CiRun(workflow="ci", status="completed", conclusion="failure")],
        analyze_risks=lambda i, p, c: [Risk(kind="blocker", severity="high", subject="AB-1",
                                            detail="d", suggested_action="a")],
        compose=lambda risks: ("<h2>Báo cáo</h2>", 0.0002),
        deliver=lambda risks, body: (True, "confluence=executed slack=executed url=https://x"),
    )


def test_report_graph_runs_with_fakes():
    graph = build_report_graph(deps=_fake_deps())
    out = graph.invoke({}, config={"configurable": {"thread_id": "t"}})
    assert out["report_text"].startswith("<h2>")  # Slice 2: detail body (HTML)
    assert out["delivered"] is True
    assert out["cost_usd"] == 0.0002
    assert "confluence=executed" in out["delivery_summary"]


def test_report_graph_compiles_without_network():
    # default deps wiring must not require network/key at build time.
    graph = build_report_graph(deps=_fake_deps())
    assert graph is not None


# --- Slice 2: short Slack message builder (mrkdwn, derived, no LLM) ---


def test_slack_short_with_risks_and_link():
    from src.llm.report_prompt import build_slack_short

    risks = [
        Risk(kind="blocker", severity="high", subject="AB-1", detail="chặn", suggested_action="gỡ")
    ]
    out = build_slack_short(risks, report_date="2026-06-21", detail_url="https://x/wiki/p")
    assert "1 rủi ro" in out
    assert "<https://x/wiki/p|" in out  # Slack link format
    assert "##" not in out and "**" not in out  # no GitHub markdown


def test_slack_short_no_risks():
    from src.llm.report_prompt import build_slack_short

    out = build_slack_short([], report_date="2026-06-21", detail_url="https://x/p")
    assert "Tiến độ ổn" in out


def test_slack_short_no_url():
    from src.llm.report_prompt import build_slack_short

    out = build_slack_short([], report_date="2026-06-21", detail_url=None)
    assert "không tạo được link" in out
