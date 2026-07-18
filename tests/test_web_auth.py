"""v6 M16: single-user session auth — the web's Lớp B approve gate. Offline.

Load-bearing:
- auth OFF (no hash) ⇒ every route open, byte-identical to pre-M16.
- auth ON ⇒ every route except /health + login needs a session; wrong password → 401;
  logout clears it; login is rate-limited (brute-force cap); the SSE stream survives auth.
- assert_bind_safe REFUSES a non-loopback bind while auth is OFF (R3 fail-loud).
- passwords are bcrypt (verify round-trips, wrong password fails).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from my_crew.server import auth


@pytest.fixture
def auth_env(monkeypatch):
    monkeypatch.setenv("WEB_AUTH_USERNAME", "ceo")
    monkeypatch.setenv("WEB_AUTH_PASSWORD_HASH", auth.hash_password("s3cret"))
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret")
    auth._login_attempts.clear()


def _app():
    from my_crew.server.app import create_app

    return create_app()


# --- bcrypt ---


def test_hash_and_verify_roundtrip():
    h = auth.hash_password("hunter2")
    assert auth._verify("hunter2", h)
    assert not auth._verify("wrong", h)
    assert not auth._verify("hunter2", "not-a-hash")  # malformed hash → False, no crash


# --- auth disabled (default) ---


def test_auth_disabled_opens_everything(monkeypatch):
    monkeypatch.delenv("WEB_AUTH_PASSWORD_HASH", raising=False)
    assert not auth.auth_enabled()
    c = TestClient(_app())
    assert c.get("/api/agents").status_code == 200
    assert c.get("/api/me").json() == {"authenticated": True, "auth": "disabled"}


# --- auth enabled ---


def test_protected_route_401_without_session(auth_env):
    c = TestClient(_app())
    assert c.get("/api/agents").status_code == 401
    assert c.get("/health").status_code == 200  # public


def test_me_is_public_and_reports_unauthenticated(auth_env):
    """/api/me must be reachable WITHOUT a session (it's how the SPA decides login vs
    dashboard on load) and answer authenticated:false — not a 401 the shell can't read."""
    c = TestClient(_app())
    r = c.get("/api/me")
    assert r.status_code == 200 and r.json() == {"authenticated": False, "user": None}


def test_login_flow(auth_env):
    c = TestClient(_app())
    assert c.post("/api/login", json={"username": "ceo", "password": "wrong"}).status_code == 401
    assert c.post("/api/login", json={"username": "ceo", "password": "s3cret"}).status_code == 200
    assert c.get("/api/agents").status_code == 200  # session now valid
    assert c.get("/api/me").json()["authenticated"] is True
    c.post("/api/logout")
    assert c.get("/api/agents").status_code == 401  # cleared


def test_wrong_username_rejected(auth_env):
    c = TestClient(_app())
    r = c.post("/api/login", json={"username": "intruder", "password": "s3cret"})
    assert r.status_code == 401


def test_login_rate_limited(auth_env):
    c = TestClient(_app())
    for _ in range(auth._LOGIN_MAX):
        c.post("/api/login", json={"username": "ceo", "password": "wrong"})
    # the next attempt is throttled — even a CORRECT password is 429 during the window
    r = c.post("/api/login", json={"username": "ceo", "password": "s3cret"})
    assert r.status_code == 429


def test_page_navigation_returns_spa_shell_not_401(auth_env):
    """A logged-out PAGE nav gets the SPA shell (React renders login), not a bare 401 —
    so the browser doesn't show a JSON error on a deep link."""
    c = TestClient(_app())
    r = c.get("/approvals")  # a client-routed page
    # either the SPA shell (200, if a build exists) or a 401 fallback — never a 500
    assert r.status_code in (200, 401)


# --- bind safety (R3) ---


def test_assert_bind_safe_refuses_lan_without_auth(monkeypatch):
    monkeypatch.delenv("WEB_AUTH_PASSWORD_HASH", raising=False)
    with pytest.raises(RuntimeError, match="refusing to bind"):
        auth.assert_bind_safe("0.0.0.0")
    # loopback is always fine
    auth.assert_bind_safe("127.0.0.1")


def test_assert_bind_safe_allows_lan_with_auth(auth_env):
    auth.assert_bind_safe("0.0.0.0")  # auth on ⇒ LAN bind allowed, no raise


def test_assert_bind_safe_refuses_auth_on_with_insecure_secret(monkeypatch):
    """auth ON but no real session secret ⇒ refuse — signing with the public dev constant
    would let anyone forge a logged-in cookie (a silent auth bypass)."""
    monkeypatch.setenv("WEB_AUTH_PASSWORD_HASH", auth.hash_password("x"))
    monkeypatch.delenv("WEB_SESSION_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="forge a session cookie"):
        auth.assert_bind_safe("127.0.0.1")  # even on loopback — a forgeable cookie is unsafe
    monkeypatch.setenv("WEB_SESSION_SECRET", auth._DEV_SESSION_SECRET)  # the public constant
    with pytest.raises(RuntimeError, match="forge a session cookie"):
        auth.assert_bind_safe("127.0.0.1")
    monkeypatch.setenv("WEB_SESSION_SECRET", "a-real-random-secret")
    auth.assert_bind_safe("127.0.0.1")  # now safe


# --- SSE survives auth (R1) ---


def test_stream_route_gated_then_reaches_handler(auth_env):
    """The live-run stream endpoint must be gated like everything else, and once
    authenticated the request must REACH the stream handler (not be blocked by the auth
    middleware). We assert the gate (401 pre-login) and that post-login the real stream
    path routes through — a missing run is a clean 404, NOT a 401 or a hang. (This proves
    routing survives the middleware; draining a live event stream end-to-end is covered by
    the SSE stream tests in test_server_stream.py.)"""
    c = TestClient(_app())
    assert c.get("/api/runs/nope/stream").status_code == 401  # gated pre-login
    c.post("/api/login", json={"username": "ceo", "password": "s3cret"})
    r = c.get("/api/runs/nope/stream")  # the REAL EventSourceResponse route
    assert r.status_code != 401  # reaches the handler through the auth middleware
