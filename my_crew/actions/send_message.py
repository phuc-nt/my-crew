"""`send_message` — the general "send content X to channel/recipient Y" primitive (v38 #1).

Delivery until now was report-shaped (a scheduled report fans out to its configured
channels) or a reply. This adds the missing primitive: an agent (via a controlled code
path — chat-ops catalog, NOT an LLM-callable write tool in the read-only loop) actively
sends a chosen message to a chosen recipient on a chosen channel.

It is a **facade**, not a new gateway action-type: it maps `{channel, to, text}` onto the
existing per-channel writer (`slack_write` / `telegram_write` / `email_write`), each of
which already builds the correct action dict and runs it through the Action Gateway. So
`send_message` inherits — with zero new guard code — Lớp A hard-deny, Lớp B + trust_mode
(autonomous executes + audits, guarded queues for approval), dry-run, kill-switch,
rate-limit, dedup, and the immutable audit log. There is no new egress surface.

Scope: slack / telegram / email — the true message-to-recipient channels. Confluence is a
PAGE-creation verb (`confluence_write.create_report_page`), not a message, so it is not a
`send_message` channel. Adding an LLM-callable write tool to the tool-calling runtime is
explicitly NOT how this is exposed — that would breach the read-only-toolset moat.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from my_crew.actions.action_gateway import ActionGateway, GatewayResult
    from my_crew.config.reporting_config import ReportingConfig

#: The channels `send_message` understands. Kept explicit so an unknown channel is a loud
#: refusal, never a silent no-op.
SUPPORTED_CHANNELS = ("slack", "telegram", "email")


class SendMessageError(ValueError):
    """A send_message request was malformed (bad channel, missing recipient/text)."""


def send_message(
    *,
    channel: str,
    to: str,
    text: str,
    gateway: ActionGateway,
    config: ReportingConfig,
    report_date: str,
    subject: str = "",
    rationale: str = "",
) -> GatewayResult:
    """Send `text` to `to` on `channel`, through the Action Gateway.

    `channel` ∈ SUPPORTED_CHANNELS. `to` is the channel-native recipient (slack channel id,
    telegram chat id, or email address). `report_date` makes the send idempotent per
    day+recipient (the writers key dedup off it). Returns the gateway result — `executed`
    / `dry_run` / `deduped` when it went through, `pending_approval` when trust_mode is
    guarded (or Lớp B rules queue it). Raises SendMessageError on a malformed request and
    RuntimeError when the channel's transport is not configured.
    """
    ch = (channel or "").strip().lower()
    recipient = (to or "").strip()
    body = text or ""
    if ch not in SUPPORTED_CHANNELS:
        raise SendMessageError(
            f"channel {channel!r} không hỗ trợ (chọn: {', '.join(SUPPORTED_CHANNELS)})"
        )
    if not recipient:
        raise SendMessageError("send_message thiếu người/kênh nhận (`to`)")
    if not body.strip():
        raise SendMessageError("send_message thiếu nội dung (`text`)")

    if ch == "slack":
        return _send_slack(recipient, body, gateway, config, report_date, rationale)
    if ch == "telegram":
        return _send_telegram(recipient, body, gateway, config, report_date, rationale)
    # email
    return _send_email(recipient, body, subject, gateway, config, report_date, rationale)


def _slack_allowed_channels(config: Any) -> frozenset[str]:
    """The Slack channels send_message may target: the agent's configured report channel
    + its declared external/stakeholder channels. A recipient outside this set is refused
    (v38 review, CEO decision): unlike Telegram (per-agent chat_id allowlist) and email
    (always Lớp B), a raw Slack channel had no allowlist — a chat-typed channel could
    auto-execute for an autonomous agent. This closes that gap while keeping the two
    registered channel kinds usable."""
    allowed: set[str] = set(getattr(config, "slack_external_channels", None) or ())
    report_ch = getattr(config, "slack_report_channel", None)
    if report_ch:
        allowed.add(str(report_ch))
    return frozenset(allowed)


def _send_slack(
    to: str, text: str, gateway: Any, config: Any, report_date: str, rationale: str
) -> GatewayResult:
    allowed = _slack_allowed_channels(config)
    if to not in allowed:
        raise SendMessageError(
            f"kênh Slack {to!r} chưa đăng ký — chỉ gửi tới kênh báo cáo hoặc kênh "
            f"external đã cấu hình ({', '.join(sorted(allowed)) or 'chưa có kênh nào'})"
        )
    from my_crew.actions.slack_write import deliver_report

    return deliver_report(
        text, gateway=gateway, config=config, channel=to,
        report_date=report_date, rationale=rationale,
    )


def _send_telegram(
    to: str, text: str, gateway: Any, config: Any, report_date: str, rationale: str
) -> GatewayResult:
    telegram = getattr(config, "telegram", None)
    if telegram is None:
        raise RuntimeError("telegram chưa cấu hình; không gửi được send_message qua telegram.")
    from my_crew.actions.telegram_write import send_telegram_message

    return send_telegram_message(
        text, gateway=gateway, telegram=telegram, chat_id=to,
        dedup_hint=f"send_message:{report_date}", rationale=rationale,
    )


def _send_email(
    to: str, text: str, subject: str, gateway: Any, config: Any, report_date: str, rationale: str
) -> GatewayResult:
    smtp = getattr(config, "smtp", None)
    if smtp is None:
        raise RuntimeError("smtp chưa cấu hình; không gửi được send_message qua email.")
    from my_crew.actions.email_write import deliver_email_report

    return deliver_email_report(
        text, subject or "(no subject)", gateway=gateway, smtp=smtp, to=to,
        report_date=report_date, rationale=rationale,
    )
