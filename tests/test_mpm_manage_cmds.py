"""Slice 3: per-agent Lớp B management — approve/reject/audit isolated per agent."""

from __future__ import annotations

import json

from my_crew.actions.approval_store import ApprovalStore
from my_crew.config.config_builders import build_settings_from_dict
from my_crew.entrypoints import mpm, mpm_manage_cmds

_SLACK_ACTION = {
    "type": "mcp_tool", "server": "slack", "tool": "post_message",
    "args": {"channel": "C_STAKE", "text": "hi"},
}


def _patch(monkeypatch, tmp_path):
    """Point agent_data_dir at a tmp .data and load_profile at a per-agent fake.

    The fake builds Settings whose data_dir IS the per-agent dir — so the gateway's
    stores land under .data/agents/<id>/, exactly as the real loader does.
    """
    data_root = tmp_path / ".data"
    monkeypatch.setattr("my_crew.runtime.agent_paths.DATA_DIR", data_root)

    def _fake_load(agent_id, *, data_dir=None):
        # dry_run=False so an `approve` actually dispatches the handler (real post path).
        settings = build_settings_from_dict({"data_dir": data_dir, "dry_run": False})

        class _Cfg:
            slack_external_channels = frozenset({"C_STAKE"})
            slack_server = None

        return type("LP", (), {"settings": settings, "config": _Cfg()})()

    monkeypatch.setattr("my_crew.profile.loader.load_profile", _fake_load)
    return data_root


def _agent_dir(data_root, agent_id):
    return data_root / "agents" / agent_id


def _seed_approval(data_root, agent_id):
    d = _agent_dir(data_root, agent_id)
    d.mkdir(parents=True, exist_ok=True)
    return ApprovalStore(d / "approvals.db").enqueue(dict(_SLACK_ACTION), reason="external report")


# --- the headline: per-agent approval isolation ---


def test_approvals_isolated_per_agent(monkeypatch, tmp_path, capsys):
    data_root = _patch(monkeypatch, tmp_path)
    _seed_approval(data_root, "a")
    assert mpm_manage_cmds.run_manage("approvals", ["a"]) == 0
    assert "external report" in capsys.readouterr().out
    # B's store is separate → no pending
    assert mpm_manage_cmds.run_manage("approvals", ["b"]) == 0
    assert "no pending approvals" in capsys.readouterr().out


def test_approve_a_does_not_touch_b(monkeypatch, tmp_path):
    data_root = _patch(monkeypatch, tmp_path)
    aid = _seed_approval(data_root, "a")
    posted = {}
    monkeypatch.setattr(
        "my_crew.actions.slack_write.make_slack_post_handler",
        lambda server: lambda action: posted.update(action) or "posted ts=1",
    )
    assert mpm_manage_cmds.run_manage("approve", ["a", str(aid)]) == 0
    assert posted["args"]["channel"] == "C_STAKE"  # the real handler ran for A
    # A's approval is consumed; B's store still empty.
    assert ApprovalStore(_agent_dir(data_root, "a") / "approvals.db").list_pending() == []
    bstore = _agent_dir(data_root, "b") / "approvals.db"
    assert not bstore.exists() or ApprovalStore(bstore).list_pending() == []


def test_reject_a(monkeypatch, tmp_path):
    data_root = _patch(monkeypatch, tmp_path)
    aid = _seed_approval(data_root, "a")
    assert mpm_manage_cmds.run_manage("reject", ["a", str(aid)]) == 0
    assert ApprovalStore(_agent_dir(data_root, "a") / "approvals.db").list_pending() == []


def test_approve_bad_id_exit_1(monkeypatch, tmp_path, capsys):
    data_root = _patch(monkeypatch, tmp_path)
    _seed_approval(data_root, "a")
    assert mpm_manage_cmds.run_manage("approve", ["a", "999"]) == 1
    assert "error:" in capsys.readouterr().err


# --- per-agent audit isolation ---


def test_audit_isolated_per_agent(monkeypatch, tmp_path, capsys):
    data_root = _patch(monkeypatch, tmp_path)
    adir = _agent_dir(data_root, "a") / "audit"
    adir.mkdir(parents=True)
    (adir / "audit.jsonl").write_text(
        json.dumps({"timestamp": "2026-06-24T08:00:00", "verdict": "allow",
                    "tool": "slack:post_message", "reason": "ok"}) + "\n",
        encoding="utf-8",
    )
    assert mpm_manage_cmds.run_manage("audit", ["a"]) == 0
    assert "slack:post_message" in capsys.readouterr().out
    # B has no audit file → no entries
    assert mpm_manage_cmds.run_manage("audit", ["b"]) == 0
    assert "no audit entries" in capsys.readouterr().out


# --- error paths ---


def test_missing_profile_exit_1(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("my_crew.runtime.agent_paths.DATA_DIR", tmp_path / ".data")

    def _boom(agent_id, *, data_dir=None):
        raise FileNotFoundError(f"Profile {agent_id!r} not found")

    monkeypatch.setattr("my_crew.profile.loader.load_profile", _boom)
    assert mpm_manage_cmds.run_manage("approvals", ["ghost"]) == 1
    assert "error:" in capsys.readouterr().err


def test_missing_agent_arg_exit_2(capsys):
    assert mpm_manage_cmds.run_manage("approvals", []) == 2
    assert "usage:" in capsys.readouterr().err


def test_malformed_id_clean_exit_1(monkeypatch, tmp_path, capsys):
    # An uppercase / path-unsafe id is rejected by _validate_agent_id (via agent_data_dir)
    # → caught in _load_agent → clean exit 1 with the "lowercase" hint, no traceback.
    monkeypatch.setattr("my_crew.runtime.agent_paths.DATA_DIR", tmp_path / ".data")
    assert mpm_manage_cmds.run_manage("approvals", ["MyAgent"]) == 1
    assert "Invalid agent id" in capsys.readouterr().err


def test_dispatch_routes_to_manage(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        mpm_manage_cmds, "run_manage", lambda sub, rest: seen.update(sub=sub, rest=rest) or 0
    )
    assert mpm.main(["agent", "approvals", "a"]) == 0
    assert seen == {"sub": "approvals", "rest": ["a"]}
