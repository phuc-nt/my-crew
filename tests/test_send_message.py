"""v38 #1: send_message facade + ops-chat command.

send_message maps {channel, to, text} onto the existing per-channel writers, so every
send inherits the Action Gateway (Lớp A/B, trust_mode, dry-run, dedup, audit). These
tests prove the routing + validation + that it is NOT a new bypass — a real gateway in
dry_run mode logs, never sends; a guarded gateway queues; an unknown channel is refused.
"""

from __future__ import annotations

import pytest

from src.actions.send_message import SUPPORTED_CHANNELS, SendMessageError, send_message


class _FakeGateway:
    """Records what the writer handed the gateway, returns an executed result."""

    def __init__(self):
        self.actions = []

    def execute(self, action, *, handler=None, rationale=""):
        self.actions.append(action)
        from src.actions.action_gateway import GatewayResult

        return GatewayResult(status="executed", summary=f"sent {action.get('type')}")


class _Cfg:
    slack_server = object()
    slack_report_channel = "C-default"
    slack_external_channels = frozenset({"C123", "C-external"})

    class _Smtp:
        recipients = ()

    class _Tele:
        chat_ids = ("99887",)

    smtp = _Smtp()
    telegram = _Tele()


def test_rejects_unknown_channel():
    with pytest.raises(SendMessageError, match="không hỗ trợ"):
        send_message(channel="carrier-pigeon", to="x", text="hi",
                     gateway=_FakeGateway(), config=_Cfg(), report_date="2026-07-13")


def test_rejects_empty_recipient_and_text():
    with pytest.raises(SendMessageError, match="người/kênh nhận"):
        send_message(channel="slack", to="  ", text="hi",
                     gateway=_FakeGateway(), config=_Cfg(), report_date="2026-07-13")
    with pytest.raises(SendMessageError, match="nội dung"):
        send_message(channel="slack", to="C1", text="   ",
                     gateway=_FakeGateway(), config=_Cfg(), report_date="2026-07-13")


def test_slack_routes_to_gateway_as_mcp_post():
    gw = _FakeGateway()
    send_message(channel="slack", to="C123", text="báo cáo xong",
                 gateway=gw, config=_Cfg(), report_date="2026-07-13")
    assert len(gw.actions) == 1
    a = gw.actions[0]
    assert a["type"] == "mcp_tool" and a["server"] == "slack"
    assert a["args"]["channel"] == "C123" and a["args"]["text"] == "báo cáo xong"


def test_slack_rejects_unregistered_channel():
    """Review HIGH #2 (CEO: add allowlist): a Slack channel not in report/external config
    is refused before the gateway — no auto-execute to an arbitrary chat-typed channel."""
    gw = _FakeGateway()
    with pytest.raises(SendMessageError, match="chưa đăng ký"):
        send_message(channel="slack", to="C-random-unlisted", text="hi",
                     gateway=gw, config=_Cfg(), report_date="2026-07-13")
    assert gw.actions == []  # never reached the gateway


def test_slack_allows_report_channel():
    gw = _FakeGateway()
    send_message(channel="slack", to="C-default", text="hi",  # the report channel
                 gateway=gw, config=_Cfg(), report_date="2026-07-13")
    assert len(gw.actions) == 1


def test_telegram_routes_with_chat_id():
    gw = _FakeGateway()
    send_message(channel="telegram", to="99887", text="nhắc lịch họp",
                 gateway=gw, config=_Cfg(), report_date="2026-07-13")
    a = gw.actions[0]
    assert a["type"] == "telegram_send" and a["chat_id"] == "99887"


def test_email_missing_smtp_raises_runtime():
    class _NoSmtp(_Cfg):
        smtp = None

    with pytest.raises(RuntimeError, match="smtp"):
        send_message(channel="email", to="a@b.com", text="hi",
                     gateway=_FakeGateway(), config=_NoSmtp(), report_date="2026-07-13")


def test_supported_channels_are_message_channels_only():
    # Confluence is a page verb, not a message — must not be a send_message channel.
    assert set(SUPPORTED_CHANNELS) == {"slack", "telegram", "email"}
    assert "confluence" not in SUPPORTED_CHANNELS


def test_dry_run_gateway_does_not_send(monkeypatch):
    """Through a REAL gateway with DRY_RUN, the send is logged, never transported."""
    from src.actions.action_gateway import ActionGateway
    from src.config.config_builders import build_settings_from_dict

    # Minimal settings with dry_run on; slack post to internal channel = not Lớp B.
    settings = build_settings_from_dict({
        "openrouter_api_key": "x", "openrouter_model": "m", "dry_run": True,
        "data_dir": "/tmp/uat-sendmsg-test",
    })

    class _RealishCfg(_Cfg):
        slack_server = {"dist": "x", "env": {}}

    gw = ActionGateway(settings, external_channels=frozenset())
    res = send_message(channel="slack", to="C-default", text="hi",  # the report channel
                       gateway=gw, config=_RealishCfg(), report_date="2026-07-13")
    assert res.status == "dry_run"  # logged what it WOULD do, sent nothing


def test_guarded_external_send_queues_for_approval(monkeypatch):
    """A Slack post to an EXTERNAL channel is Lớp B; a guarded agent must QUEUE it, not
    send — proving send_message inherits trust_mode from the gateway with no bypass."""
    from src.actions.action_gateway import ActionGateway
    from src.config.config_builders import build_settings_from_dict

    settings = build_settings_from_dict({
        "openrouter_api_key": "x", "openrouter_model": "m", "dry_run": False,
        "trust_mode": "guarded", "data_dir": "/tmp/uat-sendmsg-guarded",
    })

    class _RealishCfg(_Cfg):
        slack_server = {"dist": "x", "env": {}}
        slack_external_channels = frozenset({"C-external"})

    gw = ActionGateway(settings, external_channels=frozenset({"C-external"}))
    res = send_message(channel="slack", to="C-external", text="ra ngoài",
                       gateway=gw, config=_RealishCfg(), report_date="2026-07-13")
    assert res.status == "pending_approval"  # guarded → queued, not sent


def test_ops_command_registered_and_slots():
    from src.agent.ops_catalog import get_command

    cmd = get_command("send_message")
    assert cmd is not None and cmd["readonly"] is False
    assert set(cmd["slots"]) >= {"channel", "to", "text"}
    assert cmd["run"] is not None and cmd["preview"] is not None


def test_ops_preview_flags_unknown_channel():
    from src.agent.ops_send_message import preview_send_message

    out = preview_send_message({"channel": "fax", "to": "x", "text": "hi"})
    assert "chỉ hỗ trợ" in out and "slack" in out


@pytest.mark.parametrize("status,phrase", [
    ("executed", "Đã gửi"),
    ("pending_approval", "chờ duyệt"),
    ("dry_run", "DRY_RUN"),
    ("deduplicated", "KHÔNG gửi"),
    ("skipped", "KHÔNG gửi được"),
])
def test_ops_reply_reports_gateway_status_honestly(status, phrase, monkeypatch):
    """Review HIGH #1: a dedup/skip/dry-run must NOT read as 'sent'."""
    from src.actions.action_gateway import GatewayResult
    from src.agent import ops_send_message

    class _Loaded:
        settings = object()

        class config:
            slack_external_channels = frozenset()

    monkeypatch.setattr(ops_send_message, "_sender_profile", lambda: _Loaded())
    monkeypatch.setattr("src.actions.action_gateway.ActionGateway", lambda *a, **k: object())
    monkeypatch.setattr(ops_send_message, "send_message",
                        lambda **kw: GatewayResult(status=status, summary="x"))
    out = ops_send_message.run_send_message({"channel": "slack", "to": "C1", "text": "hi"})
    assert phrase in out
