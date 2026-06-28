"""M4-S4: JSON ops API (approve/reject/config) — RED LINE: same real gateway path.

Offline, stubbed Slack handler (NO network), mirroring test_server_approvals' seeding. The
load-bearing tests prove the JSON approve runs the REAL `gw.approve(handler=
dispatch_approved_action)` path — an audit row is written, dedup is respected, Lớp A → 403 —
exactly like the htmx route. Config tests prove validate→atomic-replace is intact.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from src.actions.approval_store import ApprovalStore
from src.config.config_builders import build_settings_from_dict
from src.server import agent_views
from src.server.app import create_app

_SLACK_ACTION = {
    "type": "mcp_tool", "server": "slack", "tool": "post_message",
    "args": {"channel": "C_STAKE", "text": "Báo cáo external xin duyệt"},
}
# A Lớp A (data-loss) action by tool NAME — survives the enqueue redaction (a secret in
# args would be redacted at enqueue, so it never reaches approve; a destructive tool name
# does not) and must be hard-denied even on approve.
_LOP_A_ACTION = {
    "type": "mcp_tool", "server": "confluence", "tool": "deletePage", "args": {"id": "123"},
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


def _seed(data_root, action=_SLACK_ACTION, agent_id="acme"):
    d = data_root / "agents" / agent_id
    d.mkdir(parents=True, exist_ok=True)
    return ApprovalStore(d / "approvals.db").enqueue(dict(action), reason="external report")


def _store(data_root, agent_id="acme"):
    return ApprovalStore(data_root / "agents" / agent_id / "approvals.db")


def _client():
    return TestClient(create_app())


def _audit_lines(data_root, agent_id="acme"):
    path = data_root / "agents" / agent_id / "audit" / "audit.jsonl"
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


# --- list ---


def test_list_approvals_json(monkeypatch, tmp_path):
    data_root = _patch(monkeypatch, tmp_path)
    aid = _seed(data_root)
    r = _client().get("/api/agents/acme/approvals")
    assert r.status_code == 200
    pending = r.json()["pending"]
    assert len(pending) == 1 and pending[0]["id"] == aid
    assert pending[0]["action"]["args"]["channel"] == "C_STAKE"  # for the confirm step


# --- RED LINE: approve runs the real gateway path ---


def test_approve_runs_real_gateway_path(monkeypatch, tmp_path):
    data_root = _patch(monkeypatch, tmp_path)
    aid = _seed(data_root)
    posted = {}
    monkeypatch.setattr(
        "src.actions.slack_write.make_slack_post_handler",
        lambda server: lambda action: posted.update(action) or "posted ts=1",
    )
    r = _client().post(f"/api/agents/acme/approvals/{aid}/approve")
    assert r.status_code == 200
    assert posted["args"]["channel"] == "C_STAKE"  # the REAL handler ran (no network)
    assert _store(data_root).list_pending() == []  # consumed
    # the gateway wrote an audit row for the approved action (the real path, not a bypass)
    audits = _audit_lines(data_root)
    assert any(a.get("verdict") == "allow" and "slack" in a.get("tool", "") for a in audits)


def test_approve_dedup_blocks_double_post(monkeypatch, tmp_path):
    """Approving the same action twice: the gateway's dedup drops the second (no double-post)."""
    data_root = _patch(monkeypatch, tmp_path)
    aid1 = _seed(data_root)
    aid2 = _seed(data_root)  # identical action → same dedup key
    calls = {"n": 0}
    monkeypatch.setattr(
        "src.actions.slack_write.make_slack_post_handler",
        lambda server: lambda action: calls.__setitem__("n", calls["n"] + 1) or "ts",
    )
    c = _client()
    assert c.post(f"/api/agents/acme/approvals/{aid1}/approve").status_code == 200
    assert c.post(f"/api/agents/acme/approvals/{aid2}/approve").status_code == 200
    assert calls["n"] == 1  # second approve deduped → handler ran once


def test_approve_lop_a_destructive_403(monkeypatch, tmp_path):
    """RED LINE: a Lớp A (data-loss) action is hard-denied even via approve → 403, never run."""
    data_root = _patch(monkeypatch, tmp_path)
    aid = _seed(data_root, action=_LOP_A_ACTION)
    r = _client().post(f"/api/agents/acme/approvals/{aid}/approve")
    assert r.status_code == 403  # HardBlockedError → 403, never posted


def test_approve_bad_id_400(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    assert _client().post("/api/agents/acme/approvals/999/approve").status_code == 400


def test_approve_handler_failure_502_stays_pending(monkeypatch, tmp_path):
    data_root = _patch(monkeypatch, tmp_path)
    aid = _seed(data_root)
    monkeypatch.setattr(
        "src.actions.slack_write.make_slack_post_handler",
        lambda server: (lambda action: (_ for _ in ()).throw(RuntimeError("slack 503"))),
    )
    r = _client().post(f"/api/agents/acme/approvals/{aid}/approve")
    assert r.status_code == 502
    assert "still pending" in r.json()["detail"]
    assert len(_store(data_root).list_pending()) == 1  # reverted, not lost


def test_reject_json(monkeypatch, tmp_path):
    data_root = _patch(monkeypatch, tmp_path)
    aid = _seed(data_root)
    r = _client().post(f"/api/agents/acme/approvals/{aid}/reject")
    assert r.status_code == 200
    assert _store(data_root).list_pending() == []  # removed, no post


def test_unknown_agent_404(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    assert _client().get("/api/agents/ghost/approvals").status_code == 404


# --- config: validate → atomic replace; MEMORY.md read-only ---


def _seed_profile(tmp_path, monkeypatch, yaml_text="name: acme\nenabled: true\n"):
    """Point profile_editor at a tmp profiles dir with a minimal valid profile."""
    pdir = tmp_path / "profiles" / "acme"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "profile.yaml").write_text(yaml_text)
    (pdir / "SOUL.md").write_text("soul")
    (pdir / "PROJECT.md").write_text("project")
    (pdir / "MEMORY.md").write_text("memory")
    monkeypatch.setattr("src.server.profile_editor._PROFILES_DIR", tmp_path / "profiles")
    return pdir


def test_get_config_returns_four_files(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    _seed_profile(tmp_path, monkeypatch)
    r = _client().get("/api/agents/acme/config")
    assert r.status_code == 200
    files = r.json()["files"]
    assert set(files) >= {"profile", "soul", "project", "memory"}


def test_save_valid_yaml_commits(monkeypatch, tmp_path):
    """Coverage parity with the deleted htmx config test: a valid edit is written."""
    _patch(monkeypatch, tmp_path)
    pdir = _seed_profile(tmp_path, monkeypatch)
    r = _client().post(
        "/api/agents/acme/config/profile", json={"text": "name: acme\nenabled: false\n"}
    )
    assert r.status_code == 200 and r.json()["saved"] == "profile.yaml"
    assert "enabled: false" in (pdir / "profile.yaml").read_text()  # committed


def test_save_non_mapping_yaml_400(monkeypatch, tmp_path):
    """A non-mapping yaml (list/scalar) → 400 (ValueError), original kept."""
    _patch(monkeypatch, tmp_path)
    pdir = _seed_profile(tmp_path, monkeypatch)
    original = (pdir / "profile.yaml").read_text()
    r = _client().post("/api/agents/acme/config/profile", json={"text": "- just\n- a list\n"})
    assert r.status_code == 400
    assert (pdir / "profile.yaml").read_text() == original


def test_save_markdown_soul(monkeypatch, tmp_path):
    """SOUL.md is editable free text (coverage parity with the htmx markdown test)."""
    _patch(monkeypatch, tmp_path)
    pdir = _seed_profile(tmp_path, monkeypatch)
    r = _client().post("/api/agents/acme/config/soul", json={"text": "new soul"})
    assert r.status_code == 200 and r.json()["saved"] == "SOUL.md"
    assert (pdir / "SOUL.md").read_text() == "new soul"


def test_config_unknown_agent_404(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    assert _client().get("/api/agents/ghost/config").status_code == 404


def test_save_invalid_yaml_400_keeps_original(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    pdir = _seed_profile(tmp_path, monkeypatch)
    original = (pdir / "profile.yaml").read_text()
    r = _client().post(
        "/api/agents/acme/config/profile", json={"text": "this: [is: broken yaml"}
    )
    assert r.status_code == 400
    assert (pdir / "profile.yaml").read_text() == original  # atomic: original preserved


def test_save_memory_md_rejected(monkeypatch, tmp_path):
    """MEMORY.md is read-only — the config route refuses to write it."""
    _patch(monkeypatch, tmp_path)
    _seed_profile(tmp_path, monkeypatch)
    r = _client().post("/api/agents/acme/config/memory", json={"text": "hacked"})
    assert r.status_code == 400
