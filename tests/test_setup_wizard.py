"""v7 M17: Setup Wizard API — the highest-risk web surface. Offline.

Load-bearing (the guards):
- Endpoints work ONLY before setup completes; 410 once the .setup-complete marker exists —
  and the marker, NOT the password hash, is what locks (rotating the hash never re-opens it).
- Localhost only; write-only status (bool, no secret value); key whitelist rejects injection.
- finish writes auth keys + marker, then triggers a restart (stubbed in tests).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from my_crew.server import routes_setup


@pytest.fixture
def clean_env(tmp_path, monkeypatch):
    """A throwaway .env + marker path so tests never touch the real repo .env."""
    env = tmp_path / ".env"
    env.write_text("", encoding="utf-8")
    marker = tmp_path / ".setup-complete"
    monkeypatch.setattr("my_crew.server.env_writer._ENV_PATH", env)
    monkeypatch.setattr(routes_setup, "_SETUP_COMPLETE_MARKER", marker)
    monkeypatch.setattr("my_crew.server.routes_setup.MY_CREW_HOME", tmp_path)
    monkeypatch.delenv("WEB_AUTH_PASSWORD_HASH", raising=False)
    # neutralize the real restart during tests — default to "accepted" like launchd would
    monkeypatch.setattr(routes_setup, "_restart_web_service", lambda: True)
    monkeypatch.setattr(routes_setup, "_restart_hint", lambda: "test-hint")
    return {"env": env, "marker": marker}


def _client():
    from my_crew.server.app import create_app

    return TestClient(create_app())


# --- before setup: endpoints work ---


def test_status_reports_incomplete_and_key_presence(clean_env):
    # A non-core key set (GITHUB_REPO) does NOT count as "configured" → wizard still shows.
    clean_env["env"].write_text("GITHUB_REPO=o/r\n", encoding="utf-8")
    r = _client().get("/api/setup/status")
    assert r.status_code == 200
    body = r.json()
    assert body["completed"] is False
    assert body["keys"]["GITHUB_REPO"] is True
    assert body["keys"]["SLACK_XOXC_TOKEN"] is False
    assert "o/r" not in str(body["keys"])  # presence is bool, no value


def test_existing_install_with_openrouter_key_skips_wizard(clean_env):
    """Regression guard (#8): a hand-configured .env (has OPENROUTER_API_KEY) but no
    password/marker must NOT be forced through the wizard — pre-M17 dev/localhost users had
    exactly this state and expect to go straight to the dashboard. `/status` says complete;
    the SPA shows login/dashboard, not the wizard."""
    clean_env["env"].write_text("OPENROUTER_API_KEY=sk-existing\n", encoding="utf-8")
    assert routes_setup.setup_complete() is True  # wizard should NOT show
    assert routes_setup.wizard_locked() is False  # but writes aren't marker-locked yet
    assert _client().get("/api/setup/status").json() == {"completed": True}


def test_lock_vs_show_are_distinct(clean_env):
    """The write-lock (marker/auth) and show-wizard (also +env-key) are SEPARATE decisions —
    conflating them bricked the wizard (C1). Prove the two functions diverge for a
    hand-configured-but-unfinished install."""
    clean_env["env"].write_text("OPENROUTER_API_KEY=sk-x\n", encoding="utf-8")
    assert routes_setup.wizard_should_show() is False  # already configured → hide wizard
    assert routes_setup.wizard_locked() is False  # not finished → writes not locked
    # after finish, both agree: locked + not-shown
    clean_env["marker"].write_text("done\n", encoding="utf-8")
    assert routes_setup.wizard_locked() is True and routes_setup.wizard_should_show() is False


def test_env_write_whitelisted_key(clean_env):
    r = _client().post("/api/setup/env", json={"OPENROUTER_API_KEY": "sk-abc"})
    assert r.status_code == 200
    assert "OPENROUTER_API_KEY=sk-abc" in clean_env["env"].read_text(encoding="utf-8")


def test_env_write_rejects_injection_key(clean_env):
    r = _client().post("/api/setup/env", json={"PATH": "/evil", "OPENROUTER_API_KEY": "x"})
    assert r.status_code == 400
    # all-or-nothing: OPENROUTER not written either
    assert "OPENROUTER_API_KEY" not in clean_env["env"].read_text(encoding="utf-8")


def test_full_flow_openrouter_then_finish_not_bricked(clean_env):
    """Regression for C1: writing the OPENROUTER key (wizard step 0) must NOT lock the wizard
    — the remaining steps + finish must still work. The lock is the marker, set at finish."""
    c = _client()
    # step 0 writes OPENROUTER_API_KEY
    assert c.post("/api/setup/env", json={"OPENROUTER_API_KEY": "sk-x"}).status_code == 200
    # a later group still writes (NOT 410)
    assert c.post("/api/setup/env", json={"SLACK_TEAM_DOMAIN": "acme.slack.com"}).status_code == 200
    # finish still reachable
    r = c.post("/api/setup/finish", json={"password": "ceopass"})
    assert r.status_code == 200 and r.json()["restarting"] is True
    assert r.json()["restart_hint"] == "test-hint"
    # NOW locked (marker set at finish)
    assert c.post("/api/setup/env", json={"GITHUB_REPO": "o/r"}).status_code == 410


# --- finish: writes auth + marker, then locks ---


def test_finish_sets_password_marker_and_locks(clean_env, monkeypatch):
    c = _client()
    r = c.post("/api/setup/finish", json={"password": "ceopass", "username": "ceo"})
    assert r.status_code == 200 and r.json()["restarting"] is True
    text = clean_env["env"].read_text(encoding="utf-8")
    assert "WEB_AUTH_PASSWORD_HASH=" in text and "WEB_SESSION_SECRET=" in text
    assert "WEB_AUTH_USERNAME=ceo" in text
    assert clean_env["marker"].exists()  # durable lock set
    # now every setup endpoint is 410 (marker present)
    assert c.post("/api/setup/env", json={"GITHUB_REPO": "o/r"}).status_code == 410
    assert c.get("/api/setup/status").json() == {"completed": True}


def test_finish_short_password_rejected(clean_env):
    r = _client().post("/api/setup/finish", json={"password": "12"})
    assert r.status_code == 400


def test_finish_reports_honest_false_when_restart_fails(clean_env, monkeypatch):
    """If the platform restart mechanism didn't accept the kickstart, `restarting` must be
    False and the message must tell the operator to restart manually — not lie."""
    monkeypatch.setattr(routes_setup, "_restart_web_service", lambda: False)
    r = _client().post("/api/setup/finish", json={"password": "ceopass"})
    assert r.status_code == 200
    body = r.json()
    assert body["restarting"] is False
    assert "thủ công" in body["message"]
    assert body["restart_hint"] == "test-hint"


def test_restart_hint_platform_detection(monkeypatch):
    # launchd not loaded, no container markers, no systemd env → generic fallback
    monkeypatch.setattr("os.system", lambda _cmd: 1 << 8)  # non-zero rc
    monkeypatch.setattr("os.path.exists", lambda _p: False)
    monkeypatch.delenv("INVOCATION_ID", raising=False)
    hint = routes_setup._restart_hint()
    assert "my-crew serve" in hint

    monkeypatch.setattr("os.path.exists", lambda p: p == "/.dockerenv")
    hint = routes_setup._restart_hint()
    assert "docker" in hint.lower() or "podman" in hint.lower()

    monkeypatch.setattr("os.path.exists", lambda _p: False)
    monkeypatch.setenv("INVOCATION_ID", "abc")
    hint = routes_setup._restart_hint()
    assert "systemctl" in hint


# --- restarting the RIGHT service ---


def _launchd_print(pid: str | None):
    """Fake `launchctl print` output, with or without a pid line."""
    body = "\tstate = running\n" + (f"\tpid = {pid}\n" if pid else "")
    return lambda cmd, **_kw: type("R", (), {"stdout": body if "print" in cmd[1] else ""})()


def test_restart_only_when_launchd_manages_this_process(monkeypatch):
    """A second server on the same Mac (own MY_CREW_HOME, own port) must NOT kickstart the
    installed service. The launchd label names one installation; finishing a wizard in a
    different instance once restarted somebody else's running fleet.
    """
    monkeypatch.setattr(routes_setup.subprocess, "run", _launchd_print("999999"))
    kicked = []
    monkeypatch.setattr("os.system", lambda cmd: kicked.append(cmd) or 0)

    assert routes_setup._launchd_manages_us() is False
    assert routes_setup._restart_web_service() is False
    assert kicked == [], "must not kickstart a job it does not belong to"


def test_restart_fires_when_this_process_is_the_launchd_job(monkeypatch):
    """The flip side: the genuinely-managed service must still restart itself, or the
    installed deployment regresses to manual restarts."""
    import os as _os

    monkeypatch.setattr(routes_setup.subprocess, "run", _launchd_print(str(_os.getpid())))
    kicked = []
    monkeypatch.setattr("os.system", lambda cmd: kicked.append(cmd) or 0)

    assert routes_setup._launchd_manages_us() is True
    assert routes_setup._restart_web_service() is True
    assert kicked and "kickstart -k" in kicked[0]


def test_restart_absent_when_launchd_has_no_such_job(monkeypatch):
    """No label loaded at all (a plain `my-crew serve`) → no pid line → no restart."""
    monkeypatch.setattr(routes_setup.subprocess, "run", _launchd_print(None))
    monkeypatch.setattr("os.system", lambda _cmd: 0)
    assert routes_setup._launchd_manages_us() is False
    assert routes_setup._restart_web_service() is False


# --- the durability property (red-team MAJOR-2) ---


def test_marker_locks_even_if_hash_absent(clean_env, monkeypatch):
    """The lock is the MARKER, not the hash. If the hash is later removed/rotated (bad
    restore, manual edit), setup must STAY locked — else a local attacker re-runs it."""
    clean_env["marker"].write_text("done\n", encoding="utf-8")
    monkeypatch.delenv("WEB_AUTH_PASSWORD_HASH", raising=False)  # hash gone
    c = _client()
    assert routes_setup.setup_complete() is True
    assert c.post("/api/setup/env", json={"GITHUB_REPO": "o/r"}).status_code == 410
    assert c.post("/api/setup/finish", json={"password": "attacker"}).status_code == 410


# --- localhost guard ---


def test_non_localhost_refused(clean_env):
    # TestClient sets client host to "testclient" (allowlisted). Prove the guard logic
    # directly with a fake request from a LAN IP.
    class _FakeClient:
        host = "192.168.1.50"

    class _FakeReq:
        client = _FakeClient()

    with pytest.raises(Exception) as exc:  # HTTPException 403
        routes_setup._guard(_FakeReq())
    assert "localhost" in str(exc.value.detail)


# --- test endpoint re-reads fresh env ---


def test_test_group_rechecks_with_fresh_env(clean_env, monkeypatch):
    monkeypatch.setattr(
        "my_crew.server.integration_health.integration_checks",
        lambda use_cache: {
            "checks": [{"id": "openrouter", "ok": True, "detail": "OK", "hint": ""}]
        },
    )
    r = _client().post("/api/setup/test/openrouter")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_test_unknown_group_404(clean_env):
    assert _client().post("/api/setup/test/nope").status_code == 404
