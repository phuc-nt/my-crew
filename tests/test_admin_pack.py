"""v3 M8: admin-pack — third domain, fleet monitoring. Offline.

Load-bearing properties:

- Pack assembly: discovery sees `admin`; 3 report kinds; Slack-only allowlist.
- Analyzers are PURE aggregations (totals/sorting/alert slicing) — numbers never come
  from an LLM.
- `agent_state_reader` is READ-ONLY over real on-disk formats (budget json, audit
  jsonl, approvals sqlite, runs jsonl) and degrades per-agent instead of raising.
- `team_alerts` thresholds are deterministic (budget ≥80%, approval ≥24h, ≥3 denies).
- RED LINE: admin's allowlist cannot reach destructive tools (Lớp A) nor any
  non-allowlisted server (default-DENY) — reading the fleet grants no write power.
- Full graph runs offline end-to-end with a fake provider (LLM absent → deterministic
  fallback narrative; delivery dry-run) — the digest still ships numbers.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from src.config.config_builders import build_reporting_config_from_dict, build_settings_from_dict
from src.packs.registry import PackRegistry, _load_pack_module, discover_domains
from src.runtime import agent_state_reader as asr

_analyzers = _load_pack_module("admin", "analyzers")
build_audit_digest = _analyzers.build_audit_digest
build_cost_rollup = _analyzers.build_cost_rollup
build_guardrail_health = _analyzers.build_guardrail_health
fallback_fleet_narrative = _analyzers.fallback_fleet_narrative
render_fleet_slack = _analyzers.render_fleet_slack


def _state(agent_id="a1", spent=0.5, cap=50.0, pending=(), counts=None, enabled=True,
           last_run=None):
    ratio = spent / cap if cap else 0.0
    return {
        "agent_id": agent_id, "name": agent_id, "enabled": enabled,
        "budget_spent_usd": spent, "budget_cap_usd": cap, "budget_ratio": ratio,
        "pending_approvals": list(pending), "audit_counts": counts or {},
        "last_run": last_run,
    }


# --- pack assembly ---


def test_admin_pack_discovered_and_assembled():
    assert "admin" in discover_domains()
    pack = PackRegistry().load("admin")
    assert set(pack.report_kinds) == {"cost-rollup", "guardrail-health", "audit-digest"}
    assert set(pack.allowlist) == {"slack"}  # Slack-only write surface
    assert "admin-narrative-system" in pack.prompts
    assert pack.tools is not None


# --- analyzers (pure) ---


def test_cost_rollup_totals_and_sorting():
    payload = {
        "agents": [_state("cheap", spent=0.1), _state("pricey", spent=2.0)],
        "alerts": [{"kind": "budget", "agent_id": "pricey", "message": "m", "severity": "warn"}],
    }
    report = build_cost_rollup(payload)
    assert report.rows[0]["agent_id"] == "pricey"  # sorted by spend desc
    assert "$2.1000" in report.headline and "2 agent" in report.headline
    assert len(report.alerts) == 1


def test_guardrail_health_counts_and_alert_slice():
    payload = {
        "agents": [_state("a", counts={"deny": 4, "allow": 2}, pending=[{"id": 1}])],
        "alerts": [
            {"kind": "deny_spike", "agent_id": "a", "message": "m", "severity": "high"},
            {"kind": "budget", "agent_id": "a", "message": "m", "severity": "warn"},
        ],
    }
    report = build_guardrail_health(payload)
    assert report.rows[0]["deny"] == 4 and report.rows[0]["pending_approvals"] == 1
    assert [al["kind"] for al in report.alerts] == ["deny_spike"]  # budget not in this kind


def test_audit_digest_counts_disabled_and_never_ran():
    payload = {"agents": [_state("off", enabled=False), _state("new", last_run=None)],
               "alerts": []}
    report = build_audit_digest(payload)
    assert "1 đang tắt" in report.headline and "2 chưa từng chạy" in report.headline


def test_render_and_fallback_are_deterministic():
    report = build_cost_rollup({"agents": [_state()], "alerts": []})
    text = render_fleet_slack(report, report_date="2026-07-02")
    assert "Chi phí LLM toàn đội — 2026-07-02" in text and "`a1`" in text
    assert report.headline in fallback_fleet_narrative(report)


# --- team_alerts thresholds ---


def test_team_alerts_thresholds():
    now = datetime.now(UTC)
    old = (now - timedelta(hours=30)).isoformat()
    fresh = (now - timedelta(hours=1)).isoformat()
    states = [
        _state("warmish", spent=40.0, cap=50.0),          # 0.8 → warn
        _state("burned", spent=55.0, cap=50.0),           # >=1.0 → high
        _state("fine", spent=1.0, cap=50.0),
        _state("stuck", pending=[{"id": 7, "reason": "r", "created_at": old},
                                 {"id": 8, "reason": "r", "created_at": fresh}]),
        _state("denied", counts={"deny": 3}),
    ]
    alerts = asr.team_alerts(states, now=now)
    kinds = {(a["kind"], a["agent_id"]): a for a in alerts}
    assert kinds[("budget", "warmish")]["severity"] == "warn"
    assert kinds[("budget", "burned")]["severity"] == "high"
    assert ("budget", "fine") not in kinds
    assert "approval #7" in kinds[("approval_stuck", "stuck")]["message"]
    assert not any(a["kind"] == "approval_stuck" and "#8" in a["message"] for a in alerts)
    assert kinds[("deny_spike", "denied")]["severity"] == "high"


# --- state reader over real on-disk formats ---


def test_read_agent_state_from_disk_fixtures(tmp_path, monkeypatch):
    from src.actions.approval_store import ApprovalStore
    from src.llm.budget_tracker import _current_month

    data_root = tmp_path / ".data"
    monkeypatch.setattr("src.runtime.agent_paths.DATA_DIR", data_root)
    d = data_root / "agents" / "acme"
    (d / "budget").mkdir(parents=True)
    (d / "budget" / f"budget-{_current_month()}.json").write_text(
        json.dumps({"month": _current_month(), "total_usd": 1.25}), encoding="utf-8"
    )
    (d / "audit").mkdir()
    now = datetime.now(UTC).isoformat()
    stale = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    (d / "audit" / "audit.jsonl").write_text(
        "\n".join([
            json.dumps({"verdict": "allow", "timestamp": now}),
            json.dumps({"verdict": "deny", "timestamp": now}),
            json.dumps({"verdict": "deny", "timestamp": stale}),  # outside window
            "not-json",
        ]) + "\n", encoding="utf-8",
    )
    store = ApprovalStore(d / "approvals.db")
    store.enqueue({"type": "mcp_tool", "server": "slack", "tool": "post_message",
                   "args": {}}, reason="test pending")
    store.close()
    (d / "runs.jsonl").write_text(
        json.dumps({"agent_id": "acme", "kind": "daily", "status": "delivered",
                    "delivered": True, "ts": now}) + "\n", encoding="utf-8",
    )
    # Profile missing on purpose: the reader must degrade, not raise.
    state = asr.read_agent_state("acme")
    assert state["budget_spent_usd"] == pytest.approx(1.25)
    assert state["audit_counts"] == {"allow": 1, "deny": 1}  # stale + non-json skipped
    assert [p["reason"] for p in state["pending_approvals"]] == ["test pending"]
    assert state["last_run"]["kind"] == "daily"
    assert state["name"].startswith("<error:") and state["enabled"] is False


def test_read_agent_state_degrades_on_corrupt_db_and_bad_profile(tmp_path, monkeypatch):
    data_root = tmp_path / ".data"
    monkeypatch.setattr("src.runtime.agent_paths.DATA_DIR", data_root)
    profiles = tmp_path / "profiles"
    (profiles / "broken").mkdir(parents=True)
    # Malformed YAML profile: must degrade to an error row, never raise (fleet-wide
    # blindness was review H2).
    (profiles / "broken" / "profile.yaml").write_text("model_chain: [a, 2.5]\n", encoding="utf-8")
    monkeypatch.setattr("src.profile.loader._PROFILES_DIR", profiles)
    d = data_root / "agents" / "broken"
    d.mkdir(parents=True)
    (d / "approvals.db").write_bytes(b"this is not a sqlite file")  # corrupt db
    state = asr.read_agent_state("broken")
    assert state["name"].startswith("<error:")
    assert state["pending_approvals"] == []  # sqlite failure degrades, not raises


def test_read_pending_never_writes_into_sibling_dir(tmp_path, monkeypatch):
    # A zero-byte approvals.db must stay zero-byte: the fleet read opens sqlite
    # READ-ONLY and must not run DDL into another agent's data dir (red line).
    data_root = tmp_path / ".data"
    monkeypatch.setattr("src.runtime.agent_paths.DATA_DIR", data_root)
    d = data_root / "agents" / "sib"
    d.mkdir(parents=True)
    (d / "approvals.db").write_bytes(b"")
    state = asr.read_agent_state("sib")
    assert state["pending_approvals"] == []
    assert (d / "approvals.db").read_bytes() == b""  # untouched


# --- RED LINE: fleet read grants no write power ---


def test_admin_allowlist_cannot_reach_destructive_or_other_servers():
    from src.actions.hard_block import BlockCategory, classify

    allowlist = PackRegistry().load("admin").allowlist
    destructive = classify(
        {"type": "mcp_tool", "server": "slack", "tool": "delete_message", "args": {}},
        allowlist=allowlist,
    )
    assert destructive.blocked and destructive.category == BlockCategory.DATA_LOSS
    other_server = classify(
        {"type": "mcp_tool", "server": "jira", "tool": "createIssue", "args": {}},
        allowlist=allowlist,
    )
    assert other_server.blocked and other_server.category == BlockCategory.NOT_ALLOWLISTED
    safe = classify(
        {"type": "mcp_tool", "server": "slack", "tool": "post_message", "args": {}},
        allowlist=allowlist,
    )
    assert not safe.blocked


# --- offline end-to-end graph run ---


class _FakeFleetTools:
    def read(self, kind, config, settings):
        states = [_state("a1", spent=45.0, cap=50.0), _state("a2", spent=0.2)]
        return {"agents": states, "alerts": asr.team_alerts(states)}


def test_fleet_graph_runs_offline_with_fallback_narrative(tmp_path):
    pack = PackRegistry().load("admin")
    settings = build_settings_from_dict({"data_dir": tmp_path, "dry_run": True})  # no API key
    config = build_reporting_config_from_dict(
        {"jira_project_key": "X", "github_repo": "o/r", "slack_report_channel": "C_ADM",
         "slack_stakeholder_channel": "", "slack_external_channels": ""}
    )
    graph = pack.report_kinds["cost-rollup"](
        None, config=config, settings=settings, tools=_FakeFleetTools()
    )
    result = graph.invoke({})
    assert result["delivered"] is True  # dry-run delivery counts as shipped
    assert "Chi phí LLM toàn đội" in result["report_text"]
    assert "a1" in result["report_text"]
    # No API key ⇒ narrative fell back to the deterministic line — numbers still there.
    assert "Không có nhận xét tự động" in result["report_text"]


# --- team alerts API (S5) ---


def test_team_alerts_endpoint_and_cache(monkeypatch):
    from fastapi.testclient import TestClient

    from src.server import routes_agents_admin
    from src.server.app import create_app

    monkeypatch.setattr(routes_agents_admin, "_alerts_cache", {"at": 0.0, "payload": None})
    calls = {"n": 0}

    def _fake_states():
        calls["n"] += 1
        return [_state("burned", spent=55.0, cap=50.0)]

    monkeypatch.setattr("src.runtime.agent_state_reader.read_all_agent_states", _fake_states)
    client = TestClient(create_app())
    res = client.get("/api/team/alerts")
    assert res.status_code == 200
    alerts = res.json()["alerts"]
    assert alerts and alerts[0]["kind"] == "budget" and alerts[0]["severity"] == "high"
    client.get("/api/team/alerts")
    assert calls["n"] == 1  # 30s cache: a mounting Team view doesn't re-scan the fleet


def test_pack_graphs_wire_pack_allowlist_into_gateway(monkeypatch, tmp_path):
    # Review H1: the pack's allowlist must reach the RUNTIME gateway, not just the
    # classifier — otherwise the graph runs under the wider core default allowlist.
    from src.config.config_builders import build_reporting_config_from_dict
    from src.packs.registry import _load_pack_module

    captured: dict = {}

    class _SpyGateway:
        def __init__(self, settings, **kwargs):
            captured.update(kwargs)

    settings = build_settings_from_dict({"data_dir": tmp_path})
    config = build_reporting_config_from_dict(
        {"jira_project_key": "X", "github_repo": "o/r", "slack_report_channel": "C",
         "slack_stakeholder_channel": "", "slack_external_channels": ""}
    )
    for domain, module in (("admin", "graphs"), ("hr", "graphs")):
        graphs = _load_pack_module(domain, module)
        monkeypatch.setattr(graphs, "ActionGateway", _SpyGateway)
        captured.clear()
        builder = next(iter(graphs.REPORT_KINDS.values()))
        builder(None, config=config, settings=settings, tools=object())
        expected = PackRegistry().load(domain).allowlist
        assert captured.get("mcp_allowlist") == expected, domain
