"""Integration health checks for the dashboard (v3 M7 S9). Mostly read-only, secret-safe.

Answers "which connection is broken?" for a non-technical operator: each check returns
ok/not-ok + a fix hint for whoever does the technical setup. NO secret VALUE is read or
returned — env checks report presence only (bool), and no check logs a token value.

Two checks now do a LIVE network probe: `gh auth status` (the gh CLI's own check, 5s
timeout) and, since v11 P3, Slack `whoami` — when the Slack MCP server build exists and
its env is present, this check spawns the server and calls its `whoami` tool (a live
`auth.test`-equivalent) to confirm the token actually authenticates, not just that the
env vars are set. This is a deliberate change from the original "no token sent anywhere"
posture: whoami sends the configured token to Slack to verify it. If the server build
predates `whoami` (tool-not-found), this check falls back to the old presence-only
check rather than erroring. Everything else stays env-presence, file-existence, or PATH
lookup. Results are cached for 30s per process so a dashboard poll cannot spawn a
subprocess storm.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time

from dotenv import load_dotenv

from my_crew.config.reporting_config import (
    _DEFAULT_CONFLUENCE_DIST,
    _DEFAULT_JIRA_DIST,
    _DEFAULT_SLACK_DIST,
)
from my_crew.config.settings import MY_CREW_HOME

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 30.0
_cache: dict = {"at": 0.0, "payload": None}
_WHOAMI_TIMEOUT_S = 10.0


def integration_checks(*, use_cache: bool = True) -> dict:
    """{checks: [{id, label, ok, detail, hint}], checked_at} — cached 30s."""
    now = time.time()
    if use_cache and _cache["payload"] is not None and now - _cache["at"] < _CACHE_TTL_SECONDS:
        return _cache["payload"]
    load_dotenv(MY_CREW_HOME / ".env")  # presence checks must see .env values (no override)
    payload = {"checks": _run_checks(), "checked_at": now}
    _cache["at"], _cache["payload"] = now, payload
    return payload


def _env_set(*names: str) -> tuple[bool, str]:
    """(all set?, 'NAME1 ✓, NAME2 ✗' presence detail — names only, never values)."""
    marks = [f"{n} {'✓' if os.getenv(n) else '✗'}" for n in names]
    return all(os.getenv(n) for n in names), ", ".join(marks)


def _run_checks() -> list[dict]:
    checks: list[dict] = []

    ok, detail = _env_set("OPENROUTER_API_KEY")
    checks.append(
        _check("openrouter", "OpenRouter (LLM)", ok, detail, "Set OPENROUTER_API_KEY in .env")
    )

    ok, detail = _env_set("ATLASSIAN_SITE_NAME", "ATLASSIAN_USER_EMAIL", "ATLASSIAN_API_TOKEN")
    checks.append(
        _check(
            "atlassian", "Atlassian token (Jira + Confluence)", ok, detail,
            "Set the 3 ATLASSIAN_* vars in .env (one shared API token)",
        )
    )

    checks.append(_slack_check())

    for check_id, label, env_name, default in (
        ("jira_mcp", "Jira MCP server build", "JIRA_MCP_DIST", _DEFAULT_JIRA_DIST),
        ("confluence_mcp", "Confluence MCP server build", "CONFLUENCE_MCP_DIST",
         _DEFAULT_CONFLUENCE_DIST),
        ("slack_mcp", "Slack MCP server build", "SLACK_MCP_DIST", _DEFAULT_SLACK_DIST),
    ):
        path = os.getenv(env_name) or str(default)
        exists = os.path.isfile(path)
        checks.append(
            _check(
                check_id, label, exists, path,
                f"Clone + `npm install && npm run build` the server, or set {env_name} in .env",
            )
        )

    checks.append(_gh_check())
    checks.append(_docker_check())  # v47: proactive deep_agent-sandbox daemon probe
    checks.append(_websearch_flag_check())
    checks.append(_smtp_check())

    gws = shutil.which("gws")
    checks.append(
        _check(
            "gws", "gws CLI (Google Sheets — hr-pack only)", gws is not None,
            gws or "not on PATH",
            "Only needed for hr-pack. Install the gws CLI and run `gws auth`",
        )
    )
    return checks


def _websearch_flag_check() -> dict:
    """v18 (UAT finding #5): agents with `web_search: true` but NO provider key on the
    machine silently degrade to "xin phép tra cứu web…" — surface it. ok=True when no
    agent opts in (the keys are then simply unused); a broken profile is skipped, never
    fails the check itself."""
    import os as _os

    from my_crew.profile.loader import load_profile
    from my_crew.runtime.registry import load_registry

    has_key = bool(_os.getenv("TAVILY_API_KEY") or _os.getenv("BRAVE_API_KEY"))
    flagged: list[str] = []
    try:
        for entry in load_registry():
            if not entry.enabled:
                continue
            try:
                if getattr(load_profile(entry.id), "web_search", False):
                    flagged.append(entry.id)
            except Exception:  # noqa: BLE001 — one broken profile must not fail health
                continue
    except Exception:  # noqa: BLE001 — registry unreadable: other checks cover that
        flagged = []
    ok = has_key or not flagged
    detail = ("no agent opts in" if not flagged else
              f"agents bật web_search: {', '.join(flagged)}" + ("" if has_key else " — THIẾU key"))
    return _check(
        "websearch_key", "Web search key (agent bật web_search)", ok, detail,
        "Thêm TAVILY_API_KEY hoặc BRAVE_API_KEY ở Setup wizard, hoặc tắt web_search "
        "trong profile các agent trên",
    )


def _smtp_check() -> dict:
    """v39 #2: SMTP presence for email delivery + send_message email. ok = SMTP_HOST set
    (present-only — a password value never leaves the server). Absent ⇒ not-ok with a hint;
    email/send_message-email simply aren't usable until configured."""
    import os as _os

    ok = bool(_os.getenv("SMTP_HOST"))
    detail = "SMTP_HOST đã đặt" if ok else "chưa cấu hình SMTP (email/send_message email tắt)"
    return _check(
        "smtp", "Email (SMTP)", ok, detail,
        "Điền SMTP_HOST/PORT/USER/PASSWORD ở trang Kết nối (thẻ Email) để bật gửi email",
    )


def _slack_spec():
    """Build the Slack McpServerSpec the same way config_builders_reporting does (dist
    path override + the 3 browser-token env vars), so this probe spawns the exact same
    server config a real report/inbox run would."""
    from pathlib import Path

    from my_crew.config.reporting_config import McpServerSpec

    return McpServerSpec(
        name="slack",
        dist_path=Path(os.getenv("SLACK_MCP_DIST") or _DEFAULT_SLACK_DIST),
        env={
            "SLACK_XOXC_TOKEN": os.getenv("SLACK_XOXC_TOKEN") or "",
            "SLACK_XOXD_TOKEN": os.getenv("SLACK_XOXD_TOKEN") or "",
            "SLACK_TEAM_DOMAIN": os.getenv("SLACK_TEAM_DOMAIN") or "",
        },
        required_env_keys=("SLACK_XOXC_TOKEN", "SLACK_XOXD_TOKEN", "SLACK_TEAM_DOMAIN"),
    )


def _slack_check() -> dict:
    """Slack: presence-bool, upgraded to a live `whoami` probe when possible (v11 P3).

    - env absent → skip the spawn entirely, same as before (presence-only, not ok).
    - env present + dist missing → presence-only check (can't spawn a build that
      isn't there; the `slack_mcp` check below already reports the missing build).
    - env present + dist present → spawn, call `whoami`:
        {ok: true} → healthy, detail names the authenticated user/team.
        {ok: false, code: "TOKEN_EXPIRED"} → not ok, hint to refresh xoxc/xoxd.
        {ok: false, ...other} → not ok, detail carries the server's own message.
        tool not found (old server build, no whoami yet) → fall back to presence-only.
        any other spawn/call failure → not ok, detail carries the error (still a
          useful signal — token might be fine but the server itself is broken).
    """
    env_ok, env_detail = _env_set("SLACK_XOXC_TOKEN", "SLACK_XOXD_TOKEN", "SLACK_TEAM_DOMAIN")
    hint = "Set SLACK_XOXC_TOKEN / SLACK_XOXD_TOKEN / SLACK_TEAM_DOMAIN in .env"
    if not env_ok:
        return _check("slack", "Slack browser-token", False, env_detail, hint)

    dist = os.getenv("SLACK_MCP_DIST") or str(_DEFAULT_SLACK_DIST)
    if not os.path.isfile(dist):
        return _check("slack", "Slack browser-token", env_ok, env_detail, hint)

    try:
        from my_crew.adapters.mcp_adapter import call_tool

        result = _call_whoami_bounded(call_tool)
    except Exception as exc:  # noqa: BLE001 — a probe failure is a health signal, not a crash
        msg = str(exc)
        if "not found on server" in msg:  # old server build predates whoami
            logger.info("slack health: whoami not available on this server build, "
                        "falling back to presence check")
            return _check("slack", "Slack browser-token", env_ok, env_detail, hint)
        logger.warning("slack health: whoami probe failed: %s", msg)
        return _check("slack", "Slack browser-token", False, f"whoami failed: {msg}", hint)

    if isinstance(result, dict) and result.get("ok"):
        who = f"user @{result.get('user')}" if result.get("user") else "user unknown"
        team = result.get("team") or "unknown"
        return _check(
            "slack", "Slack browser-token", True,
            f"đã xác thực ({who}, team {team})", hint,
        )

    code = (result or {}).get("code") if isinstance(result, dict) else None
    if code == "TOKEN_EXPIRED":
        return _check(
            "slack", "Slack browser-token", False, "Token Slack hết hạn",
            "Lấy lại xoxc/xoxd từ browser rồi cập nhật .env",
        )
    detail = f"whoami: {result!r}" if result is not None else "whoami: no response"
    return _check("slack", "Slack browser-token", False, detail, hint)


def _call_whoami_bounded(call_tool):
    """Run the slack whoami probe bounded by `_WHOAMI_TIMEOUT_S`, independent of the
    adapter's own 60s per-call timeout (health checks must fail fast, not hang the
    dashboard poll). On timeout we do NOT join the worker (`shutdown(wait=False)`): a `with`
    block would block at exit until the underlying 60s call returns, defeating the 10s bound
    (review MED2). The daemon worker is left to finish/die on its own."""
    import concurrent.futures

    spec = _slack_spec()
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(call_tool, spec, "whoami", {})
    try:
        return future.result(timeout=_WHOAMI_TIMEOUT_S)
    finally:
        pool.shutdown(wait=False)


def _gh_check() -> dict:
    """`gh auth status` exit code — the CLI's own auth probe (5s timeout, no token read)."""
    try:
        proc = subprocess.run(
            ["gh", "auth", "status"], capture_output=True, timeout=5, check=False
        )
        ok, detail = proc.returncode == 0, f"gh auth status → exit {proc.returncode}"
    except FileNotFoundError:
        ok, detail = False, "gh not on PATH"
    except subprocess.TimeoutExpired:
        ok, detail = False, "gh auth status timed out (5s)"
    return _check("github", "GitHub (gh CLI)", ok, detail, "Install gh and run `gh auth login`")


def _docker_check() -> dict:
    """`docker info` exit code — a bounded daemon-reachability probe (v47).

    Surfaces "Docker not running" PROACTIVELY in the status panel instead of only at deep_agent run
    time (a `SandboxDenied` mid-run). Bounded (5s) so a hung daemon degrades to ✗, never stalls the
    panel; `docker` absent from PATH → ✗ cleanly. This is ONLY needed by agents on the deep_agent
    runtime (which run shell in a Docker sandbox) — a Docker-free fleet can ignore a ✗ here, so the
    hint says so. No token/secret is read.
    """
    try:
        proc = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=5, check=False
        )
        ok, detail = proc.returncode == 0, (
            "docker daemon reachable" if proc.returncode == 0
            else f"docker info → exit {proc.returncode} (daemon not running?)"
        )
    except FileNotFoundError:
        ok, detail = False, "docker not on PATH"
    except subprocess.TimeoutExpired:
        ok, detail = False, "docker info timed out (5s) — daemon hung?"
    return _check(
        "docker", "Docker (deep_agent sandbox)", ok, detail,
        "Chỉ cần cho agent deep_agent (chạy shell). Chạy Docker Desktop hoặc `colima start`.",
    )


def _check(check_id: str, label: str, ok: bool, detail: str, hint: str) -> dict:
    return {"id": check_id, "label": label, "ok": bool(ok), "detail": detail, "hint": hint}
