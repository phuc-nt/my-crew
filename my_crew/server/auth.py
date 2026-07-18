"""Single-user session auth (v6 M16) — the gate protecting Lớp B approve on the web.

Threat model (phase M16): one CEO, LAN / Mac-mini deployment. NOT multi-tenant, NO SSO.
The one thing that must not happen: someone on the LAN opens the dashboard and clicks
"approve" (unlocking a Lớp B action) or reads secrets. So a single shared password behind
a signed session cookie is the right scope — auth here IS the Lớp B protection, not
decoration.

Config (all env, never git):
- `WEB_AUTH_USERNAME`     — the login name (default "admin").
- `WEB_AUTH_PASSWORD_HASH`— bcrypt hash of the password (generate with `mpm web hash-password`).
- `WEB_SESSION_SECRET`    — random secret signing the session cookie (itsdangerous).

When `WEB_AUTH_PASSWORD_HASH` is UNSET, auth is OFF (localhost dev, byte-identical to
pre-M16). Binding to anything but 127.0.0.1 with auth OFF is refused at startup
(`assert_bind_safe`) — a fail-loud guard so a LAN deploy can't accidentally expose an
unauthenticated dashboard (R3).

Crypto is bcrypt + itsdangerous only (R2: no hand-rolled crypto). Login is rate-limited
(R1 brute-force cap). Everything except /login, /api/login, /api/logout, /health, and the
SPA's own static assets requires a valid session.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict

import bcrypt
from fastapi import APIRouter, HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

_USERNAME_ENV = "WEB_AUTH_USERNAME"
_HASH_ENV = "WEB_AUTH_PASSWORD_HASH"
_SECRET_ENV = "WEB_SESSION_SECRET"

#: Paths reachable without a session. /health for liveness; the login/logout endpoints so a
#: logged-out user can authenticate; /api/me so the SPA can ASK whether it's logged in (the
#: handler answers {authenticated:false} instead of a 401, which the shell needs to decide
#: login-vs-dashboard on load); the SPA assets so the login PAGE renders.
_PUBLIC_PREFIXES = ("/api/login", "/api/logout", "/api/me", "/api/setup/status", "/health",
                    "/assets/", "/static/", "/favicon", "/icons")
#: Rate limit: max failed logins per IP per window (brute-force cap, R1).
_LOGIN_MAX = 5
_LOGIN_WINDOW_S = 60.0

router = APIRouter(tags=["auth"])
_login_attempts: dict[str, list[float]] = defaultdict(list)


def auth_enabled() -> bool:
    """True when a password hash is configured — auth is OFF by default (dev localhost)."""
    return bool(os.environ.get(_HASH_ENV, "").strip())


def hash_password(plain: str) -> str:
    """bcrypt hash of a plaintext password (for `mpm web hash-password` → .env)."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def _verify(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


#: The insecure fallback session secret used ONLY in dev (auth off). If auth is ON, the
#: operator MUST set a real WEB_SESSION_SECRET — signing sessions with this public constant
#: would let anyone forge a logged-in cookie, defeating the whole auth layer.
_DEV_SESSION_SECRET = "dev-insecure-session-secret"


def assert_session_secret_safe() -> None:
    """Refuse when auth is ON but WEB_SESSION_SECRET is unset / the public dev constant —
    signing sessions with a known secret lets anyone FORGE a logged-in cookie, silently
    defeating auth. Called at app-build time so EVERY entry path (main() or `uvicorn
    app:app`) is guarded, not just main() (review M1)."""
    if auth_enabled() and os.environ.get(_SECRET_ENV, "").strip() in ("", _DEV_SESSION_SECRET):
        raise RuntimeError(
            f"web auth is ON but {_SECRET_ENV} is unset/insecure — an attacker could forge "
            f"a session cookie. Set a real secret: mpm web gen-secret."
        )


def assert_bind_safe(host: str) -> None:
    """Refuse to start an unsafe bind (R3 — fail loud, not warn).

    Binding a non-loopback host (0.0.0.0 / LAN IP) with auth OFF exposes the dashboard —
    anyone on the network could approve Lớp B actions. (The weak-secret refusal lives in
    `assert_session_secret_safe`, called at app build so it also covers `uvicorn app:app`.)
    """
    assert_session_secret_safe()
    loopback = host in ("127.0.0.1", "localhost", "::1")
    if not loopback and not auth_enabled():
        raise RuntimeError(
            f"refusing to bind {host!r} with web auth DISABLED — set {_HASH_ENV} "
            f"(mpm web hash-password) + {_SECRET_ENV} first, or bind 127.0.0.1."
        )


def _rate_limited(ip: str, *, now: float | None = None) -> bool:
    current = now if now is not None else time.time()
    recent = [t for t in _login_attempts[ip] if current - t < _LOGIN_WINDOW_S]
    _login_attempts[ip] = recent
    return len(recent) >= _LOGIN_MAX


def _record_attempt(ip: str, *, now: float | None = None) -> None:
    _login_attempts[ip].append(now if now is not None else time.time())


@router.post("/api/login")
async def login(request: Request) -> dict:
    """Authenticate; on success set the signed session. Rate-limited per client IP."""
    if not auth_enabled():
        return {"ok": True, "auth": "disabled"}  # dev: no login needed
    ip = request.client.host if request.client else "?"
    if _rate_limited(ip):
        raise HTTPException(status_code=429, detail="Quá nhiều lần thử, đợi một phút rồi thử lại.")
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="body phải là JSON") from None
    username = str(body.get("username") or "")
    password = str(body.get("password") or "")
    expected_user = os.environ.get(_USERNAME_ENV, "admin")
    hashed = os.environ.get(_HASH_ENV, "")
    if username == expected_user and _verify(password, hashed):
        request.session["user"] = username  # signed cookie via SessionMiddleware
        return {"ok": True}
    _record_attempt(ip)
    raise HTTPException(status_code=401, detail="Sai tên đăng nhập hoặc mật khẩu.")


@router.post("/api/logout")
async def logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True}


@router.get("/api/me")
async def me(request: Request) -> dict:
    """Who is logged in (the SPA calls this on load to decide login vs dashboard)."""
    if not auth_enabled():
        return {"authenticated": True, "auth": "disabled"}
    user = request.session.get("user")
    return {"authenticated": bool(user), "user": user}


class AuthMiddleware(BaseHTTPMiddleware):
    """Require a valid session for every request except the public prefixes.

    An unauthenticated API call gets 401 (the SPA client turns that into a login redirect);
    an unauthenticated PAGE navigation returns the SPA shell so the React app can render the
    login screen itself (no server-side redirect needed for a client-routed SPA).
    """

    async def dispatch(self, request: Request, call_next):
        if not auth_enabled():
            return await call_next(request)
        path = request.url.path
        if path == "/" or any(path.startswith(p) for p in _PUBLIC_PREFIXES):
            return await call_next(request)
        if request.session.get("user"):
            return await call_next(request)
        if path.startswith("/api/"):
            return Response('{"detail":"chưa đăng nhập"}', status_code=401,
                            media_type="application/json")
        # A client-routed page: hand back the SPA shell; React shows the login screen.
        from pathlib import Path

        from fastapi.responses import FileResponse

        index = Path(__file__).parent / "static" / "app" / "index.html"
        if index.is_file():
            return FileResponse(index)
        return Response("login required", status_code=401)


__all__ = ["router", "AuthMiddleware", "auth_enabled", "hash_password", "assert_bind_safe",
           "assert_session_secret_safe"]
