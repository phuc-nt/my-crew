"""Slice C: OKR prompts + graph wiring + CLI --okr (no network, no key)."""

from __future__ import annotations

from src.agent.okr_analyzer import OkrRollup
from src.agent.okr_report_graph import OkrReportDeps, build_okr_graph
from src.llm.okr_report_prompt import (
    build_okr_slack_short,
    fallback_okr_narrative,
    render_okr_table_xhtml,
)
from src.tools.models import KeyResult, Objective, OkrProblem


def _rollup() -> OkrRollup:
    obj = Objective(
        name="Tăng retention",
        key_results=(
            KeyResult("KR1 churn < 5%", ("ABC-1",), 0.7, progress_pct=80.0),
            KeyResult("KR2 NPS > 40", ("ABC-2",), 0.3, progress_pct=40.0),
        ),
        progress_pct=68.0,
    )
    behind = Objective(
        name="Mở rộng thị trường",
        key_results=(KeyResult("KR3", ("ABC-9",), None, progress_pct=20.0),),
        progress_pct=20.0,
    )
    return OkrRollup(
        objectives=(obj, behind),
        problems=(OkrProblem("O1 | KRX", "epic ABC-99 không tồn tại / không có child"),),
        at_risk=("Mở rộng thị trường",),
    )


# --- deterministic XHTML render ---


def test_render_okr_table_xhtml_has_no_github_markdown():
    out = render_okr_table_xhtml(_rollup(), report_date="2026-06-22")
    assert "<table>" in out and "<h2>" in out
    assert "##" not in out and "**" not in out  # no GitHub markdown
    assert "<html>" not in out and "<body>" not in out


def test_render_okr_table_xhtml_numbers_from_rollup():
    out = render_okr_table_xhtml(_rollup(), report_date="2026-06-22")
    assert "68%" in out  # objective progress, rendered deterministically
    assert "80%" in out and "40%" in out  # KR progresses
    assert "Mở rộng thị trường" in out  # at-risk section present


def test_render_okr_table_xhtml_lists_problems():
    out = render_okr_table_xhtml(_rollup(), report_date="2026-06-22")
    assert "OKR có vấn đề" in out
    assert "ABC-99" in out


def test_render_okr_table_no_objectives():
    empty = OkrRollup(objectives=(), problems=(), at_risk=())
    out = render_okr_table_xhtml(empty, report_date="2026-06-22")
    assert "Chưa có Objective" in out


# --- Slack short (mrkdwn) ---


def test_okr_slack_short_mrkdwn():
    out = build_okr_slack_short(_rollup(), report_date="2026-06-22", detail_url="https://x/p")
    assert "*OKR Status" in out
    assert "<https://x/p|" in out
    assert "Cần chú ý" in out
    assert "##" not in out and "**" not in out


def test_okr_slack_short_no_url():
    out = build_okr_slack_short(_rollup(), report_date="2026-06-22", detail_url=None)
    assert "không tạo được link" in out


def test_fallback_narrative_is_single_paragraph():
    out = fallback_okr_narrative(_rollup(), report_date="2026-06-22")
    assert out.startswith("<p>") and out.endswith("</p>")
    assert "Cần chú ý" in out


# --- graph wiring with fakes ---


def _fake_deps(delivered: bool = True):
    rollup = _rollup()
    return OkrReportDeps(
        fetch_rollup=lambda: rollup,
        compose=lambda r: ("<p>tóm tắt</p><h2>OKR</h2>", None),
        deliver=lambda r, body: (delivered, "confluence=dry_run slack=dry_run url=None"),
    )


def test_okr_graph_runs_with_fakes():
    graph = build_okr_graph(deps=_fake_deps())
    out = graph.invoke({}, config={"configurable": {"thread_id": "okr-t"}})
    assert out["report_text"].startswith("<p>")
    assert out["delivered"] is True
    # problems serialized into state as primitive dicts
    assert any("ABC-99" in p["reason"] for p in out["risks"])


def test_okr_graph_compiles_without_network():
    assert build_okr_graph(deps=_fake_deps()) is not None


def test_okr_deliver_uses_okr_dedup_namespace(settings_factory, tmp_path, monkeypatch):
    """The OKR deliver path must go through the gateway with an okr-<date> dedup key."""
    from datetime import UTC, datetime

    import src.actions.confluence_write as cw
    import src.actions.slack_write as sw
    from src.actions.action_gateway import ActionGateway, GatewayResult
    from src.actions.confluence_write import ConfluencePage
    from src.agent import okr_report_graph
    from src.audit.audit_log import AuditLog

    today = datetime.now(UTC).date().isoformat()
    gw = ActionGateway(
        settings=settings_factory(dry_run=True), audit_log=AuditLog(tmp_path / "a.jsonl")
    )
    seen_dates: list[str] = []

    # Spy on the two gateway wrappers to capture the report_date (dedup namespace).
    def fake_create_page(title, body, *, gateway, report_date, rationale=""):
        seen_dates.append(report_date)
        return GatewayResult(status="dry_run", summary="", approval_id=None), \
            ConfluencePage(page_id=None, url=None)

    def fake_deliver_report(text, *, gateway, report_date, rationale="", channel=None):
        seen_dates.append(report_date)
        return GatewayResult(status="dry_run", summary="", approval_id=None)

    monkeypatch.setattr(cw, "create_report_page", fake_create_page)
    monkeypatch.setattr(sw, "deliver_report", fake_deliver_report)

    deps = okr_report_graph.default_okr_deps(gateway=gw)
    ok, summary = deps.deliver(_rollup(), "<p>body</p>")
    assert ok is True
    assert seen_dates == [f"okr-{today}", f"okr-{today}"]  # both writes namespaced per okr-date


# --- CLI dispatch ---


def test_parse_report_kind_okr():
    from src.entrypoints.cli import _parse_report_kind

    assert _parse_report_kind(["--okr"]) == "okr"
    assert _parse_report_kind(["--weekly"]) == "weekly"
    assert _parse_report_kind([]) == "daily"
    assert _parse_report_kind(["--okr", "--weekly"]) == "okr"  # okr precedence


def test_cli_report_okr_dispatch(monkeypatch):
    """`report --okr` builds the OKR graph (not the daily/weekly one)."""
    import src.agent.okr_report_graph as okr_graph_mod
    from src.entrypoints import cli

    called = {}

    class _FakeGraph:
        def invoke(self, _state, config):
            called["invoked"] = True
            return {"report_text": "<p>ok</p>", "cost_usd": None,
                    "delivered": True, "delivery_summary": "s"}

    monkeypatch.setattr(cli, "get_settings", lambda: type("S", (), {"openrouter_api_key": "k"})())
    monkeypatch.setattr(cli, "get_checkpointer", lambda: None)
    monkeypatch.setattr(
        okr_graph_mod, "build_okr_graph", lambda cp, audience="internal": _FakeGraph()
    )

    rc = cli.main(["report", "--okr"])
    assert rc == 0
    assert called.get("invoked") is True


def test_audit_command_still_works_without_key(monkeypatch):
    """Regression: non-LLM commands must not require a key after the --okr change."""
    from src.entrypoints import cli

    monkeypatch.setattr(cli, "get_settings",
                        lambda: type("S", (), {"openrouter_api_key": None})())
    rc = cli.main(["audit", "--limit", "1"])
    assert rc == 0  # runs without a key
