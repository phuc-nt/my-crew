"""M3-P11 S3: delivery channel registry — backward-compat + gateway-routed extras.

No smtp ⇒ no extra channels (byte-identical pre-P11). With smtp ⇒ email is an extra
channel, delivered through the gateway (Lớp B ⇒ pending_approval). Plus a guard that
`smtplib` is imported ONLY in `email_write.py` (no side-path send bypassing the gateway).
"""

from __future__ import annotations

import subprocess

from src.actions.action_gateway import ActionGateway
from src.agent.channel_registry import (
    EXTRA_CHANNEL_OK_STATUSES,
    deliver_extra_channels,
    resolve_channels,
)
from src.audit.audit_log import AuditLog
from src.config.config_builders import build_reporting_config_from_dict


def _config_with_smtp():
    return build_reporting_config_from_dict(
        {"smtp": {"host": "smtp.test", "user": "bot@test", "recipients": "lead@team.com"}}
    )


def test_no_smtp_no_extra_channels():
    """Backward-compat: no smtp ⇒ () ⇒ Slack+Confluence only."""
    assert resolve_channels(build_reporting_config_from_dict({})) == ()


def test_smtp_host_without_recipients_fails_loud():
    """A declared email channel with no recipient must fail at load, not silently drop."""
    import pytest

    with pytest.raises(RuntimeError, match="recipients is empty"):
        build_reporting_config_from_dict({"smtp": {"host": "smtp.test", "user": "b@test"}})


def test_smtp_adds_email_channel():
    assert resolve_channels(_config_with_smtp()) == ("email",)


def test_deliver_extra_channels_empty_when_no_smtp(settings_factory, tmp_path):
    gw = ActionGateway(
        settings=settings_factory(dry_run=False), audit_log=AuditLog(tmp_path / "a.jsonl")
    )
    results = deliver_extra_channels(
        "body", "Daily", gateway=gw, config=build_reporting_config_from_dict({}),
        report_date="2026-06-26", audience="internal",
    )
    assert results == []


def test_deliver_extra_channels_email_queues(settings_factory, tmp_path):
    gw = ActionGateway(
        settings=settings_factory(dry_run=False), audit_log=AuditLog(tmp_path / "a.jsonl")
    )
    results = deliver_extra_channels(
        "body", "Daily", gateway=gw, config=_config_with_smtp(),
        report_date="2026-06-26", audience="internal",
    )
    assert len(results) == 1
    label, result = results[0]
    assert label == "email"
    assert result.status == "pending_approval"
    assert result.status in EXTRA_CHANNEL_OK_STATUSES


def test_smtplib_imported_only_in_email_write():
    """No side path: smtplib must not be imported anywhere but the gateway handler."""
    out = subprocess.run(
        ["grep", "-rln", "import smtplib", "src/"],
        capture_output=True, text=True, check=False,
    ).stdout.split()
    assert out == ["src/actions/email_write.py"], f"smtplib imported outside email_write: {out}"
