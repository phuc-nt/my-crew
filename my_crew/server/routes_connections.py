"""Connections screen routes (v33 P1) — the UI version of `.env`, catalog-FIXED.

One card per KNOWN integration: live status (reuses `integration_health` checks) +
which env keys are set (presence only — a secret VALUE never leaves the server) +
a whitelisted write path (reuses `env_writer.merge_env` with the UNCHANGED
`SETUP_WRITABLE_KEYS`). This module deliberately adds NO new writable key and NO
free-form editor: the catalog below is the whole surface.

Restart semantics: `merge_env` writes the FILE only — this process keeps its old
os.environ until restarted (same constraint the Setup wizard has). A successful key
write flips a module-level `needs_restart` marker so the UI can show the banner; the
restart endpoint reuses the wizard's launchd kickstart and tells the truth when the
service is not launchd-managed (dev: restart by hand).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, HTTPException

from my_crew.runtime.webhook_url_guard import WebhookUrlBlocked, assert_safe_webhook_url
from my_crew.server import env_writer
from my_crew.server.env_writer import (
    CONNECTIONS_WRITABLE_KEYS,
    SETUP_WRITABLE_KEYS,
    DisallowedEnvKey,
)
from my_crew.server.integration_health import integration_checks

logger = logging.getLogger(__name__)

#: OPERATOR_WEBHOOK_URL_ENV name, mirrored here (not imported from operator_channels) to
#: avoid pulling the runtime module's heavier import graph into the server route module for
#: one string constant.
_OPERATOR_WEBHOOK_URL_KEY = "OPERATOR_WEBHOOK_URL"

router = APIRouter(prefix="/api/connections", tags=["connections"])

#: Written keys the running process has not loaded yet (file != process env).
_needs_restart = False

#: The fixed catalog. `check_ids` reference integration_health check ids; `keys` are
#: the env keys the card's form may edit — every one MUST be in SETUP_WRITABLE_KEYS
#: (asserted at import so a typo fails loudly, not silently 400s at runtime).
_CATALOG: tuple[dict, ...] = (
    {
        "id": "openrouter", "label": "OpenRouter (LLM)",
        "check_ids": ("openrouter",),
        "keys": ("OPENROUTER_API_KEY", "OPENROUTER_MODEL"),
    },
    {
        "id": "atlassian", "label": "Atlassian — Jira + Confluence",
        "check_ids": ("atlassian", "jira_mcp", "confluence_mcp"),
        "keys": (
            "ATLASSIAN_SITE_NAME", "ATLASSIAN_USER_EMAIL", "ATLASSIAN_API_TOKEN",
            "JIRA_PROJECT_KEY", "CONFLUENCE_SPACE_KEY", "CONFLUENCE_SPACE_ID",
            "OKR_CONFLUENCE_PAGE_ID",
        ),
    },
    {
        "id": "slack", "label": "Slack (browser token)",
        "check_ids": ("slack", "slack_mcp"),
        "keys": (
            "SLACK_XOXC_TOKEN", "SLACK_XOXD_TOKEN", "SLACK_TEAM_DOMAIN",
            "SLACK_REPORT_CHANNEL", "SLACK_STAKEHOLDER_CHANNEL", "SLACK_EXTERNAL_CHANNELS",
        ),
    },
    {
        "id": "websearch", "label": "Tìm kiếm web (Tavily / Brave)",
        "check_ids": ("websearch_key",),
        "keys": ("TAVILY_API_KEY", "BRAVE_API_KEY"),
    },
    {
        "id": "github", "label": "GitHub (gh CLI)",
        "check_ids": ("github",),
        "keys": ("GITHUB_REPO",),
        "note": "Đăng nhập bằng `gh auth login` trong terminal — không có key trong .env.",
    },
    {
        "id": "gws", "label": "Google Workspace (gws CLI — Sheets, Gmail, Calendar, Drive)",
        "check_ids": ("gws",),
        "keys": (),
        "note": "Cài gws CLI và chạy `gws auth` — xác thực OAuth riêng, không có key trong .env. "
                "Bật `gws_context: true` trong hồ sơ agent để agent đọc Gmail/Calendar/Drive.",
    },
    {
        "id": "smtp", "label": "Email (SMTP)",
        "check_ids": ("smtp",),
        "keys": (
            "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD",
            "SMTP_FROM_ADDR", "SMTP_USE_TLS", "SMTP_RECIPIENTS",
        ),
        "note": "Cấu hình SMTP để gửi email báo cáo + send_message qua email. "
                "Mật khẩu chỉ dùng lúc gửi, không hiển thị lại.",
    },
    {
        "id": "telegram", "label": "Telegram (bot theo từng nhân sự)",
        "check_ids": (),
        "keys": (),
        "note": "Token bot khai theo từng nhân sự ở trang nhân sự đó "
                "(Đội → chọn nhân sự → Telegram).",
    },
    {
        "id": "nokey", "label": "Firecrawl / OpenAlex",
        "check_ids": (),
        "keys": (),
        "ok": True,
        "note": "Không cần key — Firecrawl chạy local, OpenAlex là API mở.",
    },
    {
        # Operator escalation channels (email + webhook): NOT wizard-writable — only the
        # `/operator` route can set them (localhost-bound pre-auth, session-authed
        # post-finish). See CONNECTIONS_WRITABLE_KEYS docstring for why this can't live
        # in SETUP_WRITABLE_KEYS.
        "id": "operator", "label": "Cảnh báo cho người vận hành (escalation)",
        "check_ids": (),
        "keys": ("OPERATOR_EMAIL", "OPERATOR_WEBHOOK_URL"),
        "ok": True,
        "note": "Nơi nhận thông báo khi agent cần người vận hành can thiệp (ngoài Telegram). "
                "Webhook chỉ nhận https, không nhận địa chỉ nội bộ/loopback.",
    },
)

# A catalog typo (key outside its intended whitelist) must fail at import, not at runtime.
for _card in _CATALOG:
    _allowed = SETUP_WRITABLE_KEYS if _card["id"] != "operator" else CONNECTIONS_WRITABLE_KEYS
    for _k in _card["keys"]:
        assert _k in _allowed, f"catalog key {_k} not writable on its intended path"


@router.get("")
def get_connections() -> dict:
    """Cards for the fixed catalog: aggregated status + key presence. Never a value."""
    checks = {c["id"]: c for c in integration_checks()["checks"]}
    presence = env_writer.read_key_presence(SETUP_WRITABLE_KEYS | CONNECTIONS_WRITABLE_KEYS)
    cards = []
    for card in _CATALOG:
        card_checks = [checks[cid] for cid in card["check_ids"] if cid in checks]
        if card_checks:
            ok = all(c["ok"] for c in card_checks)
            detail = "; ".join(c["detail"] for c in card_checks)
            hint = next((c["hint"] for c in card_checks if not c["ok"]), "")
        else:
            ok, detail, hint = bool(card.get("ok", True)), "", ""
        cards.append({
            "id": card["id"], "label": card["label"], "ok": ok,
            "detail": detail, "hint": hint, "note": card.get("note", ""),
            "keys": [{"name": k, "set": bool(presence.get(k))} for k in card["keys"]],
        })
    return {"cards": cards, "needs_restart": _needs_restart}


@router.put("/keys")
def put_connection_keys(updates: dict[str, str] = Body(..., embed=True)) -> dict:  # noqa: B008
    """Write key values into `.env` through the ONE whitelisted merge path. Blank
    values are skipped by merge_env (never blank out a set key); an unknown key name
    is refused all-or-nothing."""
    global _needs_restart
    clean = {k: v for k, v in updates.items() if str(v).strip() != ""}
    if not clean:
        raise HTTPException(status_code=400, detail="Không có giá trị nào để lưu.")
    try:
        env_writer.merge_env(clean, allow=SETUP_WRITABLE_KEYS)
    except DisallowedEnvKey as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _needs_restart = True
    logger.info("connections: wrote %d env key(s): %s", len(clean), ", ".join(sorted(clean)))
    return {"ok": True, "written": sorted(clean), "needs_restart": True}


@router.put("/operator")
def put_operator_keys(updates: dict[str, str] = Body(..., embed=True)) -> dict:  # noqa: B008
    """Write OPERATOR_EMAIL / OPERATOR_WEBHOOK_URL — the ONLY path that may set them.
    Never reachable through `/setup/env`. Like every other route here, this one is
    localhost-bound pre-auth and session-authed post-finish (`AuthMiddleware` only
    enforces sessions once `WEB_AUTH_PASSWORD_HASH` exists) — it is NOT unconditionally
    "authed". OPERATOR_WEBHOOK_URL is SSRF-checked before it touches disk, and again at
    send time in `operator_channels._try_webhook` (DNS can rebind between the two).

    `needs_restart` is true only on EDIT (the key already held a DIFFERENT value) — the
    scheduler/worker is a separate process from this web process and won't see a fresh
    `load_dotenv(override=True)` here, so an edit needs a real restart to take effect. A
    first-set still benefits from the immediate in-process reload (this process sees it
    right away for e.g. a subsequent Test), so it does not falsely demand a restart.
    """
    global _needs_restart
    clean = {k: v.strip() for k, v in updates.items() if str(v).strip() != ""}
    if not clean:
        raise HTTPException(status_code=400, detail="Không có giá trị nào để lưu.")

    webhook = clean.get(_OPERATOR_WEBHOOK_URL_KEY)
    if webhook is not None:
        try:
            assert_safe_webhook_url(webhook)
        except WebhookUrlBlocked as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    before = env_writer.read_key_presence(CONNECTIONS_WRITABLE_KEYS)
    # A key "already set" (present) whose value we're about to overwrite is an EDIT — the
    # running scheduler process may already be using the OLD value and needs a restart to
    # see the new one. First-set keys don't have that problem (nothing was using them).
    is_edit = any(before.get(k) for k in clean)

    try:
        env_writer.merge_env(clean, allow=CONNECTIONS_WRITABLE_KEYS)
    except DisallowedEnvKey as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    from dotenv import load_dotenv

    from my_crew.config.settings import MY_CREW_HOME

    load_dotenv(MY_CREW_HOME / ".env", override=True)  # this process sees the new value now
    if is_edit:
        _needs_restart = True
    logger.info("connections: wrote %d operator key(s): %s", len(clean), ", ".join(sorted(clean)))
    return {"ok": True, "written": sorted(clean), "needs_restart": is_edit}


@router.post("/restart")
def restart_service() -> dict:
    """Restart the web service so new .env values load. Reuses the wizard's launchd
    kickstart; when the service is not launchd-managed (dev), says so honestly."""
    from my_crew.server.routes_setup import _restart_web_service

    managed = _restart_web_service()
    if managed:
        return {"ok": True, "managed": True,
                "message": "Đang khởi động lại — đợi ~5 giây rồi tải lại trang."}
    return {"ok": True, "managed": False,
            "message": "Dịch vụ không chạy qua launchd — hãy khởi động lại thủ công "
                       "(tắt tiến trình server rồi chạy lại)."}
