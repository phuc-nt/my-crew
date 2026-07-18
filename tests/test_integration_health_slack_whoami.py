"""Slack integration-health check (v11 P3): env-presence upgraded to a live `whoami`
probe when the server build exists, with a graceful fallback to the old presence-only
check on an old server build (no whoami tool yet). Hermetic — `call_tool` is
monkeypatched, no real subprocess spawns.
"""

from __future__ import annotations

import pytest

from my_crew.server import integration_health as health_mod


@pytest.fixture(autouse=True)
def _slack_env(monkeypatch, tmp_path):
    """A present, valid-looking Slack env + an existing dist file (so the check gets
    past the presence/build gates and reaches the whoami probe)."""
    dist = tmp_path / "index.js"
    dist.write_text("// fake dist")
    monkeypatch.setenv("SLACK_XOXC_TOKEN", "xoxc-fake")
    monkeypatch.setenv("SLACK_XOXD_TOKEN", "xoxd-fake")
    monkeypatch.setenv("SLACK_TEAM_DOMAIN", "acme")
    monkeypatch.setenv("SLACK_MCP_DIST", str(dist))
    yield


def test_env_absent_skips_probe_entirely(monkeypatch):
    for name in ("SLACK_XOXC_TOKEN", "SLACK_XOXD_TOKEN", "SLACK_TEAM_DOMAIN"):
        monkeypatch.delenv(name, raising=False)

    called = {"n": 0}
    monkeypatch.setattr(
        "my_crew.adapters.mcp_adapter.call_tool",
        lambda *a, **k: called.__setitem__("n", called["n"] + 1),
    )
    result = health_mod._slack_check()
    assert result["ok"] is False
    assert called["n"] == 0  # never spawned


def test_dist_missing_falls_back_to_presence_only(monkeypatch):
    monkeypatch.setenv("SLACK_MCP_DIST", "/no/such/file.js")
    called = {"n": 0}
    monkeypatch.setattr(
        "my_crew.adapters.mcp_adapter.call_tool",
        lambda *a, **k: called.__setitem__("n", called["n"] + 1),
    )
    result = health_mod._slack_check()
    assert result["ok"] is True  # env present -> old presence-only behavior
    assert called["n"] == 0  # no spawn attempted for a build that doesn't exist


def test_whoami_ok_reports_authenticated_user_and_team(monkeypatch):
    monkeypatch.setattr(
        "my_crew.adapters.mcp_adapter.call_tool",
        lambda spec, tool, args: {"ok": True, "user": "phuc", "team": "Acme"},
    )
    result = health_mod._slack_check()
    assert result["ok"] is True
    assert "phuc" in result["detail"]
    assert "Acme" in result["detail"]


def test_whoami_token_expired_reports_not_ok_with_vn_hint(monkeypatch):
    monkeypatch.setattr(
        "my_crew.adapters.mcp_adapter.call_tool",
        lambda spec, tool, args: {"ok": False, "code": "TOKEN_EXPIRED"},
    )
    result = health_mod._slack_check()
    assert result["ok"] is False
    assert "hết hạn" in result["detail"]
    assert "xoxc" in result["hint"]


def test_whoami_tool_not_found_falls_back_to_presence_check(monkeypatch):
    def fake_call_tool(spec, tool, args):
        raise RuntimeError(
            f"MCP call failed: server='slack' tool={tool!r}: "
            f"MCP tool {tool!r} not found on server 'slack'. Available: search_messages"
        )

    monkeypatch.setattr("my_crew.adapters.mcp_adapter.call_tool", fake_call_tool)
    result = health_mod._slack_check()
    assert result["ok"] is True  # old server, presence was fine -> not an error


def test_whoami_other_failure_reports_not_ok(monkeypatch):
    def fake_call_tool(spec, tool, args):
        raise RuntimeError("MCP call failed: server='slack' tool='whoami': boom")

    monkeypatch.setattr("my_crew.adapters.mcp_adapter.call_tool", fake_call_tool)
    result = health_mod._slack_check()
    assert result["ok"] is False
    assert "boom" in result["detail"]


def test_run_checks_includes_slack_and_does_not_crash(monkeypatch):
    """Sanity: the full check list still assembles with the new slack check wired in."""
    monkeypatch.setattr(
        "my_crew.adapters.mcp_adapter.call_tool",
        lambda spec, tool, args: {"ok": True, "user": "x", "team": "y"},
    )
    checks = health_mod._run_checks()
    ids = [c["id"] for c in checks]
    assert "slack" in ids
    assert ids.count("slack") == 1


# --- v47: Docker daemon health check --------------------------------------------------


def _fake_run(returncode=0, exc=None):
    def _run(argv, **kw):
        if exc is not None:
            raise exc
        return type("P", (), {"returncode": returncode})()
    return _run


def test_docker_check_ok_when_daemon_reachable(monkeypatch):
    monkeypatch.setattr(health_mod.subprocess, "run", _fake_run(returncode=0))
    c = health_mod._docker_check()
    assert c["id"] == "docker" and c["ok"] is True


def test_docker_check_not_ok_when_daemon_down(monkeypatch):
    monkeypatch.setattr(health_mod.subprocess, "run", _fake_run(returncode=1))
    c = health_mod._docker_check()
    assert c["ok"] is False and "deep_agent" in c["hint"]  # hint says it's deep_agent-only


def test_docker_check_not_on_path(monkeypatch):
    monkeypatch.setattr(health_mod.subprocess, "run", _fake_run(exc=FileNotFoundError()))
    c = health_mod._docker_check()
    assert c["ok"] is False and "PATH" in c["detail"]


def test_docker_check_bounded_on_hang(monkeypatch):
    import subprocess as _sp

    monkeypatch.setattr(
        health_mod.subprocess, "run",
        _fake_run(exc=_sp.TimeoutExpired(cmd="docker info", timeout=5)),
    )
    c = health_mod._docker_check()
    assert c["ok"] is False and "timed out" in c["detail"]  # degrades, never hangs


def test_run_checks_includes_docker(monkeypatch):
    monkeypatch.setattr(
        "my_crew.adapters.mcp_adapter.call_tool",
        lambda spec, tool, args: {"ok": True, "user": "x", "team": "y"},
    )
    ids = [c["id"] for c in health_mod._run_checks()]
    assert "docker" in ids and ids.count("docker") == 1
