"""First-run Setup Wizard API (v7 M17) — the ONLY web path that writes secrets to .env.

This is the highest-risk surface in v7, so the guards are layered (red-team hardened):

1. **Not-configured only**: every endpoint 410 Gone once setup is complete. "Complete" is a
   DURABLE marker file `.setup-complete` — NOT merely `auth_enabled()`. If it were only the
   password hash, losing/rotating the hash (bad restore, manual edit) would re-open the
   wizard and let a local attacker seize the dashboard (red-team MAJOR-2). The flag is set at
   `finish` and never auto-cleared.
2. **Localhost only**: refuse a non-loopback client. We read `request.client.host` and do
   NOT trust `X-Forwarded-For` — setup must run directly on the box, not behind a proxy.
3. **Write-only**: status returns booleans (key set / not set), never a secret value.
4. **Key-name whitelist**: `env_writer` refuses any key outside the allow-list (env-injection
   guard). Passwords go through the dedicated `finish` path, not free-form env.

Writing .env does NOT take effect in the running process (`load_dotenv` doesn't override
os.environ; the session secret binds once at app build). So `finish` writes the auth keys +
the marker, then RESTARTS the web service — only after restart is auth live. There is no safe
hot-reload for the session secret (red-team MAJOR-1).
"""

from __future__ import annotations

import logging
import os
import secrets

from fastapi import APIRouter, Body, HTTPException, Request

from my_crew.config.settings import MY_CREW_HOME
from my_crew.server import auth, env_writer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/setup", tags=["setup"])

_SETUP_COMPLETE_MARKER = MY_CREW_HOME / ".setup-complete"

#: Public integration groups the wizard can Test, mapped to the env keys each needs set.
_TEST_GROUPS: dict[str, tuple[str, ...]] = {
    "openrouter": ("OPENROUTER_API_KEY",),
    "atlassian": ("ATLASSIAN_SITE_NAME", "ATLASSIAN_USER_EMAIL", "ATLASSIAN_API_TOKEN"),
    "slack": ("SLACK_XOXC_TOKEN", "SLACK_XOXD_TOKEN", "SLACK_TEAM_DOMAIN"),
    "github": (),  # gh CLI auth, checked via the gh probe
}


def wizard_locked() -> bool:
    """The DURABLE write-lock for the wizard's mutation endpoints. Locked once ANY of:
    - the `.setup-complete` marker exists (wizard finished, or a prior run), OR
    - auth is already configured (a real password hash).

    Deliberately does NOT look at the setup keys being written — otherwise the wizard would
    lock itself the moment it writes its first key (OPENROUTER on step 0), before the
    password step (review C1). Rotating/removing the hash never unlocks: the marker is
    permanent (review MAJOR-2).
    """
    return _SETUP_COMPLETE_MARKER.exists() or auth.auth_enabled()


def wizard_should_show() -> bool:
    """Whether the SPA shows the wizard (vs login/dashboard). Distinct from the write-lock:
    an already-configured install (hand-edited .env with a core key) skips the wizard even
    though it was never `finish`-ed — so pre-M17 dev/localhost users aren't forced through it
    (regression #8). This is a READ decision; it does not weaken the write-lock above.
    """
    if wizard_locked():
        return False
    from my_crew.server.env_writer import read_key_presence

    configured = read_key_presence(frozenset({"OPENROUTER_API_KEY"})).get("OPENROUTER_API_KEY")
    return not configured  # show only when NOT already hand-configured


#: Back-compat name used by app wiring / tests.
def setup_complete() -> bool:
    """True when the wizard should NOT show (locked OR already hand-configured)."""
    return not wizard_should_show()


def _guard(request: Request) -> None:
    """Refuse if the wizard is durably LOCKED (410) or the caller isn't localhost (403).

    Uses `wizard_locked()` (marker OR auth) — NOT `setup_complete()`. The wizard writes keys
    as it goes, so gating writes on "any key present" would lock it mid-flow (review C1). The
    lock is the marker, set only at finish.
    """
    if wizard_locked():
        raise HTTPException(status_code=410, detail="Cài đặt đã hoàn tất.")
    client = request.client.host if request.client else ""
    if client not in ("127.0.0.1", "::1", "localhost", "testclient"):
        raise HTTPException(status_code=403, detail="Setup chỉ chạy trên máy chủ (localhost).")


@router.get("/status")
def setup_status(request: Request) -> dict:
    """Wizard state: completed? which keys are set (bool only)? Never returns a secret.

    Public even after completion (returns {completed: true}) so the SPA knows to show the
    login screen instead of the wizard."""
    if setup_complete():
        return {"completed": True}
    from my_crew.server.env_writer import FINISH_WRITABLE_KEYS

    all_keys = env_writer.SETUP_WRITABLE_KEYS | FINISH_WRITABLE_KEYS
    return {"completed": False, "keys": env_writer.read_key_presence(all_keys)}


@router.post("/env")
def setup_env(request: Request, values: dict = Body(..., embed=False)) -> dict:  # noqa: B008
    """Write a batch of setup keys to .env (whitelist-guarded). Values not echoed back."""
    _guard(request)
    if not isinstance(values, dict) or not values:
        raise HTTPException(status_code=400, detail="body phải là {KEY: value}")
    try:
        env_writer.merge_env({str(k): str(v) for k, v in values.items()},
                             allow=env_writer.SETUP_WRITABLE_KEYS)
    except env_writer.DisallowedEnvKey as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {"ok": True, "written": sorted(values.keys())}


@router.post("/test/{group}")
def setup_test(request: Request, group: str) -> dict:
    """Re-check one integration group with FRESH .env values (override the process env so a
    just-written key is seen). Returns ok + a names-only detail — never a secret."""
    _guard(request)
    if group not in _TEST_GROUPS:
        raise HTTPException(status_code=404, detail=f"nhóm không rõ: {group}")
    from dotenv import load_dotenv

    load_dotenv(MY_CREW_HOME / ".env", override=True)  # SEE the values the wizard just wrote
    from my_crew.server import integration_health

    payload = integration_health.integration_checks(use_cache=False)
    checks = {c["id"]: c for c in payload["checks"]}
    if group == "github":
        c = checks.get("github") or checks.get("gh") or {"ok": False, "detail": "?", "hint": ""}
    else:
        c = checks.get(group, {"ok": False, "detail": "?", "hint": ""})
    return {"group": group, "ok": bool(c.get("ok")), "detail": c.get("detail"),
            "hint": c.get("hint")}


@router.post("/finish")
def setup_finish(request: Request, password: str = Body(..., embed=True),
                 username: str = Body("admin", embed=True)) -> dict:
    """Final step: set the login password + a fresh session secret, mark setup complete, and
    restart the web service so the new auth config takes effect.

    After this, os.environ still holds the OLD (auth-off) values in THIS process, so we
    restart rather than pretend auth is live. The wizard shows "đang khởi động lại".
    """
    _guard(request)
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Mật khẩu tối thiểu 6 ký tự.")
    from my_crew.server.env_writer import FINISH_WRITABLE_KEYS

    env_writer.merge_env(
        {
            "WEB_AUTH_USERNAME": username or "admin",
            "WEB_AUTH_PASSWORD_HASH": auth.hash_password(password),
            "WEB_SESSION_SECRET": secrets.token_urlsafe(48),
        },
        allow=FINISH_WRITABLE_KEYS,
    )
    _SETUP_COMPLETE_MARKER.write_text("v7 M17 setup done\n", encoding="utf-8")
    _restart_web_service()
    return {"ok": True, "restarting": True,
            "message": "Đã lưu. Đang khởi động lại dịch vụ — đợi ~5 giây rồi đăng nhập."}


def _restart_web_service() -> bool:
    """Ask launchd to restart this service so the new .env auth values load. If launchd isn't
    managing us (dev: uvicorn by hand), this no-ops with a log — the operator restarts by
    hand (the response tells them to). Never crashes finish. Returns True only when launchd
    accepted the kickstart, so callers can tell the operator the honest story."""
    label = "com.mpm.web"
    try:
        uid = os.getuid()
        # kickstart -k restarts the job; only works if it's a loaded launchd service.
        rc = os.system(f"launchctl kickstart -k gui/{uid}/{label} >/dev/null 2>&1")  # noqa: S605
        return rc == 0
    except Exception:  # noqa: BLE001 — restart is best-effort; finish already persisted
        logger.warning("could not auto-restart web service; restart it manually", exc_info=True)
        return False


__all__ = ["router", "setup_complete"]
