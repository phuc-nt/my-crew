"""M4-S1: read-only JSON visualization API — shape + PII allowlist + memory red line.

Offline: seed a tmp per-agent data dir (runs.jsonl / budget / approvals.db / audit.jsonl),
point the views' registry + profile loaders at it, and assert each endpoint returns the
allowlisted JSON. Red-line test: `/api/memory?audience=external` leaks no facts.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from src.actions.approval_store import ApprovalStore
from src.audit.audit_log import AuditEntry, AuditLog
from src.config.config_builders import build_settings_from_dict
from src.server import agent_views, visualize_views
from src.server.app import create_app


def _patch(monkeypatch, tmp_path, ids=("acme",)):
    data_root = tmp_path / ".data"
    monkeypatch.setattr("src.runtime.agent_paths.DATA_DIR", data_root)
    from src.runtime.registry import RegistryEntry

    reg = lambda: tuple(RegistryEntry(i, True) for i in ids)  # noqa: E731
    monkeypatch.setattr(visualize_views, "load_registry", reg)
    monkeypatch.setattr(agent_views, "load_registry", reg)

    def _fake_load(agent_id, *, data_dir=None, **k):
        settings = build_settings_from_dict(
            {"data_dir": data_dir, "dry_run": False, "monthly_budget_usd": 50.0}
        )
        return type("LP", (), {"settings": settings})()

    # visualize_views binds load_profile into its own namespace → patch it there.
    monkeypatch.setattr(visualize_views, "load_profile", _fake_load)
    return data_root


def _agent_dir(data_root, agent_id="acme"):
    d = data_root / "agents" / agent_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _client():
    return TestClient(create_app())


# --- runs ---


def test_runs_endpoint_allowlist(monkeypatch, tmp_path):
    data_root = _patch(monkeypatch, tmp_path)
    d = _agent_dir(data_root)
    # seed a run-event with a SENSITIVE extra field that must be dropped
    (d / "runs.jsonl").write_text(
        json.dumps({
            "ts": "2026-06-28T00:00:00Z", "kind": "daily", "audience": "internal",
            "status": "delivered", "cost_usd": 0.01, "delivered": True,
            "secret_report_text": "PII per-assignee names",
        }) + "\n"
    )
    r = _client().get("/api/runs/acme")
    assert r.status_code == 200
    runs = r.json()["runs"]
    assert len(runs) == 1
    assert runs[0]["kind"] == "daily" and runs[0]["delivered"] is True
    assert "secret_report_text" not in runs[0]  # allowlist dropped it


def test_runs_unknown_agent_404(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    assert _client().get("/api/runs/ghost").status_code == 404


# --- cost ---


def test_cost_endpoint_monthly_series(monkeypatch, tmp_path):
    data_root = _patch(monkeypatch, tmp_path)
    d = _agent_dir(data_root)
    bdir = d / "budget"
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / "budget-2026-05.json").write_text(json.dumps({"total_usd": 3.5}))
    (bdir / "budget-2026-06.json").write_text(json.dumps({"total_usd": 1.2}))
    r = _client().get("/api/cost/acme")
    assert r.status_code == 200
    body = r.json()
    assert body["cap"] == 50.0
    assert {row["month"] for row in body["series"]} == {"2026-05", "2026-06"}
    # over-budget agent must NOT raise (no check_allowed)
    (bdir / "budget-2026-06.json").write_text(json.dumps({"total_usd": 999.0}))
    assert _client().get("/api/cost/acme").status_code == 200


# --- memory red line ---


def test_memory_internal_returns_facts(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    _agent_dir(tmp_path / ".data")
    r = _client().get("/api/memory/acme?audience=internal")
    assert r.status_code == 200
    assert r.json()["internal_only"] is True  # facts list may be empty (InMemoryStore)


def test_memory_internal_returns_seeded_fact(monkeypatch, tmp_path):
    """Happy path: a seeded fact in the agent's namespace is returned (guards the namespace)."""
    _patch(monkeypatch, tmp_path)
    _agent_dir(tmp_path / ".data")
    from langgraph.store.memory import InMemoryStore

    from src.agent.memory_node import _NAMESPACE_KIND

    seeded = InMemoryStore()
    seeded.put(("acme", _NAMESPACE_KIND), "k1", {"fact": "SCRUM-15 quá hạn 17 ngày"})
    monkeypatch.setattr("src.agent.store.get_store", lambda settings: seeded)
    r = _client().get("/api/memory/acme?audience=internal")
    assert r.status_code == 200
    facts = r.json()["facts"]
    assert any(f["fact"] == "SCRUM-15 quá hạn 17 ngày" for f in facts)


def test_memory_external_leaks_nothing(monkeypatch, tmp_path):
    """RED LINE: an external-audience memory read returns no facts even when facts exist."""
    _patch(monkeypatch, tmp_path)
    _agent_dir(tmp_path / ".data")
    from langgraph.store.memory import InMemoryStore

    from src.agent.memory_node import _NAMESPACE_KIND

    seeded = InMemoryStore()
    seeded.put(("acme", _NAMESPACE_KIND), "k1", {"fact": "should NOT leak"})
    monkeypatch.setattr("src.agent.store.get_store", lambda settings: seeded)
    r = _client().get("/api/memory/acme?audience=external")
    assert r.status_code == 200
    assert r.json()["facts"] == []  # external gets nothing despite a seeded fact


# --- automation ---


def test_automation_summarizes_action(monkeypatch, tmp_path):
    data_root = _patch(monkeypatch, tmp_path)
    d = _agent_dir(data_root)
    ApprovalStore(d / "approvals.db").enqueue(
        {"type": "mcp_tool", "server": "slack", "tool": "post_message",
         "args": {"channel": "C_STAKE", "text": "secret message body"}},
        reason="external report",
    )
    r = _client().get("/api/automation/acme")
    assert r.status_code == 200
    pending = r.json()["pending"]
    assert len(pending) == 1
    assert pending[0]["action_summary"] == "mcp_tool:slack:post_message"
    # raw args (the message text) must NOT be echoed
    assert "secret message body" not in json.dumps(pending[0])


# --- audit ---


def test_audit_unknown_agent_404(monkeypatch, tmp_path):
    """Coverage parity with the deleted htmx audit test: unknown id → 404."""
    _patch(monkeypatch, tmp_path)
    assert _client().get("/api/audit/ghost").status_code == 404


def test_audit_limit_clamped(monkeypatch, tmp_path):
    """The recent-rows limit is clamped (no unbounded / no limit=0=all)."""
    data_root = _patch(monkeypatch, tmp_path)
    d = _agent_dir(data_root)
    adir = d / "audit"
    adir.mkdir(parents=True, exist_ok=True)
    log = AuditLog(adir / "audit.jsonl")
    for i in range(5):
        log.record(AuditEntry(action_type="mcp_tool", tool=f"t{i}", verdict="allow"))
    body = _client().get("/api/audit/acme?limit=2").json()
    assert len(body["recent"]) == 2  # clamped to the requested limit
    assert body["counts"]["allow"] == 5  # counts are over ALL rows, not the clamp


def test_audit_counts_and_recent(monkeypatch, tmp_path):
    data_root = _patch(monkeypatch, tmp_path)
    d = _agent_dir(data_root)
    adir = d / "audit"
    adir.mkdir(parents=True, exist_ok=True)
    log = AuditLog(adir / "audit.jsonl")
    log.record(AuditEntry(action_type="mcp_tool", tool="slack:post_message", verdict="allow"))
    log.record(AuditEntry(action_type="mcp_tool", tool="confluence:deletePage", verdict="deny",
                          reason="Lớp A", rationale="should be dropped"))
    r = _client().get("/api/audit/acme")
    assert r.status_code == 200
    body = r.json()
    assert body["counts"] == {"allow": 1, "deny": 1}
    assert len(body["recent"]) == 2
    # rationale/result_summary must NOT be in the projected rows
    assert "rationale" not in body["recent"][0]
