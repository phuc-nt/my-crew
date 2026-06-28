"""M4-S5: consolidated offline e2e + the htmx-removal grep guard.

Proves the M4 surface coheres after htmx removal: FastAPI serves the SPA at `/`, the 5 JSON
APIs return seeded data, the approve red line runs the real gateway path (stubbed post), and
no Jinja2/TemplateResponse code remains in src/server/. No network, no live keys.

(Trigger + SSE are unchanged by M4-S5 and stay covered by their own suites —
`test_server_trigger.py` + `test_server_stream.py` — so they are not re-exercised here.)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from src.actions.approval_store import ApprovalStore
from src.config.config_builders import build_settings_from_dict
from src.server import agent_views
from src.server.app import create_app

_SERVER_DIR = Path(__file__).resolve().parents[1] / "src" / "server"
_SLACK_ACTION = {
    "type": "mcp_tool", "server": "slack", "tool": "post_message",
    "args": {"channel": "C_STAKE", "text": "Báo cáo external xin duyệt"},
}


def _patch(monkeypatch, tmp_path, ids=("acme",)):
    data_root = tmp_path / ".data"
    monkeypatch.setattr("src.runtime.agent_paths.DATA_DIR", data_root)
    from src.runtime.registry import RegistryEntry

    reg = lambda: tuple(RegistryEntry(i, True) for i in ids)  # noqa: E731
    monkeypatch.setattr(agent_views, "load_registry", reg)
    monkeypatch.setattr("src.server.visualize_views.load_registry", reg)
    monkeypatch.setattr("src.server.ops_helpers.agent_views.load_registry", reg)

    def _fake_load(agent_id, *, data_dir=None, **k):
        settings = build_settings_from_dict({"data_dir": data_dir, "dry_run": False})

        class _Cfg:
            slack_external_channels = frozenset({"C_STAKE"})
            slack_server = None

        return type("LP", (), {"settings": settings, "config": _Cfg()})()

    monkeypatch.setattr("src.profile.loader.load_profile", _fake_load)
    monkeypatch.setattr("src.server.visualize_views.load_profile", _fake_load)
    return data_root


# --- grep guard: htmx fully removed ---


def test_no_jinja_template_code_in_server():
    """No Jinja2/TemplateResponse CODE remains in src/server/ (htmx UI fully removed).

    Checks for the actual rendering constructs, not the word 'htmx' in a migration comment
    (a few docstrings reference the old htmx UI by name — that's history, not live code).
    """
    offenders = []
    for py in _SERVER_DIR.rglob("*.py"):
        src = py.read_text(encoding="utf-8")
        for needle in ("TemplateResponse", "Jinja2Templates", "import jinja2", "htmx.min.js"):
            if needle in src:
                offenders.append(f"{py.name}: {needle}")
    assert offenders == [], f"jinja/template remnants: {offenders}"


def test_htmx_files_deleted():
    for gone in (
        "routes_dashboard.py", "routes_approvals.py", "routes_audit.py", "routes_profile.py",
        "templates", "static/htmx.min.js",
    ):
        assert not (_SERVER_DIR / gone).exists(), f"{gone} should be deleted in S5"


# --- e2e: SPA + JSON APIs + approve red line ---


def test_spa_and_api_surface(monkeypatch, tmp_path):
    data_root = _patch(monkeypatch, tmp_path)
    d = data_root / "agents" / "acme"
    d.mkdir(parents=True, exist_ok=True)
    run = {"ts": "t1", "kind": "daily", "status": "delivered"}
    (d / "runs.jsonl").write_text(json.dumps(run) + "\n")
    c = TestClient(create_app())
    # SPA shell at /
    assert c.get("/").status_code == 200
    # the 5 JSON APIs return seeded data
    assert c.get("/api/runs/acme").json()["runs"][0]["kind"] == "daily"
    assert c.get("/api/cost/acme").status_code == 200
    assert c.get("/api/memory/acme?audience=internal").json()["internal_only"] is True
    assert c.get("/api/automation/acme").status_code == 200
    assert c.get("/api/audit/acme").status_code == 200


def test_e2e_approve_red_line(monkeypatch, tmp_path):
    """The approve path still runs the real gateway (audit written), end to end, no bypass."""
    data_root = _patch(monkeypatch, tmp_path)
    d = data_root / "agents" / "acme"
    d.mkdir(parents=True, exist_ok=True)
    aid = ApprovalStore(d / "approvals.db").enqueue(dict(_SLACK_ACTION), reason="external report")
    posted = {}
    monkeypatch.setattr(
        "src.actions.slack_write.make_slack_post_handler",
        lambda server: lambda action: posted.update(action) or "ts=1",
    )
    r = TestClient(create_app()).post(f"/api/agents/acme/approvals/{aid}/approve")
    assert r.status_code == 200
    assert posted["args"]["channel"] == "C_STAKE"  # the REAL handler ran (no network)
    audit = (d / "audit" / "audit.jsonl")
    rows = [json.loads(x) for x in audit.read_text().splitlines() if x.strip()]
    assert any(a.get("verdict") == "allow" for a in rows)  # gateway audited the approve


def test_external_memory_still_internal_only(monkeypatch, tmp_path):
    """Red line survives the rewrite: external-audience memory read leaks nothing."""
    _patch(monkeypatch, tmp_path)
    (tmp_path / ".data" / "agents" / "acme").mkdir(parents=True, exist_ok=True)
    r = TestClient(create_app()).get("/api/memory/acme?audience=external")
    assert r.status_code == 200 and r.json()["facts"] == []


def test_localhost_no_auth_contract():
    """The app is still localhost-only / no-auth (no auth dependency added)."""
    app = create_app()
    # No global auth dependency; an unauthenticated request to /api/agents is 200.
    assert TestClient(app).get("/api/agents").status_code == 200
    # the JS asset path is the base=/ build (served at /assets), proving the S5 serve rewrite
    index = TestClient(app).get("/").text
    assert re.search(r"/assets/index-[^\"]+\.js", index)
