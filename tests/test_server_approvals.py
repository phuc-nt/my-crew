"""M2-P7 Slice 2: web approve/reject (offline, stubbed Slack handler — NO network).

Seeds a real ApprovalStore under tmp (like test_mpm_manage_cmds), points the routes'
load_registry + load_profile at it, and stubs make_slack_post_handler so approve
exercises the REAL gateway path (Lớp A + audit + dedup) but no live post happens.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.actions.approval_store import ApprovalStore
from src.config.config_builders import build_settings_from_dict
from src.server import agent_views
from src.server.app import create_app

_SLACK_ACTION = {
    "type": "mcp_tool", "server": "slack", "tool": "post_message",
    "args": {"channel": "C_STAKE", "text": "Báo cáo external xin duyệt"},
}


def _patch(monkeypatch, tmp_path, ids=("acme",)):
    data_root = tmp_path / ".data"
    monkeypatch.setattr("src.runtime.agent_paths.DATA_DIR", data_root)
    from src.runtime.registry import RegistryEntry

    monkeypatch.setattr(
        agent_views, "load_registry", lambda: tuple(RegistryEntry(i, True) for i in ids)
    )

    def _fake_load(agent_id, *, data_dir=None, **k):
        settings = build_settings_from_dict({"data_dir": data_dir, "dry_run": False})

        class _Cfg:
            slack_external_channels = frozenset({"C_STAKE"})
            slack_server = None

        return type("LP", (), {"settings": settings, "config": _Cfg()})()

    monkeypatch.setattr("src.profile.loader.load_profile", _fake_load)
    return data_root


def _seed(data_root, agent_id="acme"):
    d = data_root / "agents" / agent_id
    d.mkdir(parents=True, exist_ok=True)
    return ApprovalStore(d / "approvals.db").enqueue(dict(_SLACK_ACTION), reason="external report")


def _store(data_root, agent_id="acme"):
    return ApprovalStore(data_root / "agents" / agent_id / "approvals.db")


def _client():
    return TestClient(create_app())


def test_approvals_list_shows_action_detail(monkeypatch, tmp_path):
    data_root = _patch(monkeypatch, tmp_path)
    _seed(data_root)
    r = _client().get("/dashboard/agents/acme/approvals")
    assert r.status_code == 200
    assert "C_STAKE" in r.text  # channel shown
    assert "Báo cáo external" in r.text  # message text shown


def test_confirm_partial_shows_what_posts(monkeypatch, tmp_path):
    data_root = _patch(monkeypatch, tmp_path)
    aid = _seed(data_root)
    r = _client().get(f"/dashboard/agents/acme/approvals/{aid}/confirm")
    assert r.status_code == 200
    assert "slack:post_message" in r.text and "C_STAKE" in r.text
    assert f"/approvals/{aid}/approve" in r.text  # confirm posts to the approve route


def test_approve_runs_real_handler_no_network(monkeypatch, tmp_path):
    data_root = _patch(monkeypatch, tmp_path)
    aid = _seed(data_root)
    posted = {}
    monkeypatch.setattr(
        "src.actions.slack_write.make_slack_post_handler",
        lambda server: lambda action: posted.update(action) or "posted ts=1",
    )
    r = _client().post(f"/dashboard/agents/acme/approvals/{aid}/approve")
    assert r.status_code == 200
    assert posted["args"]["channel"] == "C_STAKE"  # the stub handler RAN (no real post)
    assert _store(data_root).list_pending() == []  # consumed
    assert "None pending" in r.text  # refreshed list partial


def test_approve_bad_id_400(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    # no approval seeded → unknown id → ValueError → 400
    r = _client().post("/dashboard/agents/acme/approvals/999/approve")
    assert r.status_code == 400


def test_approve_handler_failure_502_and_stays_pending(monkeypatch, tmp_path):
    # A live-post failure → gateway reverts the approval to pending; the route maps the
    # RuntimeError to 502 (retryable) instead of a raw 500, and the approval survives.
    data_root = _patch(monkeypatch, tmp_path)
    aid = _seed(data_root)

    def _boom(server):
        def _h(action):
            raise RuntimeError("slack 503")
        return _h

    monkeypatch.setattr("src.actions.slack_write.make_slack_post_handler", _boom)
    r = _client().post(f"/dashboard/agents/acme/approvals/{aid}/approve")
    assert r.status_code == 502
    assert "still pending" in r.json()["detail"]
    assert len(_store(data_root).list_pending()) == 1  # reverted to pending, not lost


def test_reject_one_click(monkeypatch, tmp_path):
    data_root = _patch(monkeypatch, tmp_path)
    aid = _seed(data_root)
    posted = {}
    monkeypatch.setattr(
        "src.actions.slack_write.make_slack_post_handler",
        lambda server: lambda action: posted.update(action) or "x",
    )
    r = _client().post(f"/dashboard/agents/acme/approvals/{aid}/reject")
    assert r.status_code == 200
    assert _store(data_root).list_pending() == []  # marked rejected
    assert posted == {}  # NO handler invoked on reject


def test_unknown_agent_404(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, ids=("acme",))
    assert _client().get("/dashboard/agents/ghost/approvals").status_code == 404
    assert _client().post("/dashboard/agents/ghost/approvals/1/reject").status_code == 404


def test_confirm_unknown_approval_404(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    assert _client().get("/dashboard/agents/acme/approvals/999/confirm").status_code == 404
