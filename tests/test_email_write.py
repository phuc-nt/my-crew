"""M3-P11 S3: Email (SMTP) delivery as a gateway-routed mutation.

ALL email is Lớp B (queues for approval). Fake SMTP via monkeypatched `smtplib.SMTP`
(stdlib only — no real send, no external lib). Verifies the gateway funnel: dry-run ⇒ no
connection; kill-switch ⇒ refused; secret/empty ⇒ denied; password never on the action.
"""

from __future__ import annotations

import pytest

from my_crew.actions import approved_dispatch, email_write
from my_crew.actions.action_gateway import ActionGateway, WriteDisabledError
from my_crew.audit.audit_log import AuditLog
from my_crew.config.config_builders import build_reporting_config_from_dict
from my_crew.config.smtp_config import SmtpConfig


def _smtp() -> SmtpConfig:
    return SmtpConfig(
        smtp_host="smtp.test", smtp_user="bot@test", from_addr="bot@test",
        recipients=("lead@team.com",),
    )


def _gateway(settings_factory, tmp_path, **kw):
    settings = settings_factory(**kw)
    return ActionGateway(settings=settings, audit_log=AuditLog(tmp_path / "audit.jsonl"))


class _FakeSMTP:
    """Records calls instead of connecting. Context-manager like smtplib.SMTP."""

    instances: list = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port
        self.started_tls = False
        self.logged_in = None
        self.sent = None
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, user, password):
        self.logged_in = (user, password)

    def send_message(self, msg):
        self.sent = msg


@pytest.fixture(autouse=True)
def _reset_fake():
    _FakeSMTP.instances = []


# --- Lớp B: every email queues for approval, never auto-sent ---


def test_email_queues_for_approval(settings_factory, tmp_path, monkeypatch):
    monkeypatch.setattr("my_crew.actions.email_write.smtplib.SMTP", _FakeSMTP)
    gw = _gateway(settings_factory, tmp_path, dry_run=False)
    result = email_write.deliver_email_report(
        "report body", "Daily", gateway=gw, smtp=_smtp(), report_date="2026-06-26"
    )
    assert result.status == "pending_approval"
    assert not _FakeSMTP.instances  # nothing sent — only queued


def test_dry_run_opens_no_connection(settings_factory, tmp_path, monkeypatch):
    monkeypatch.setattr("my_crew.actions.email_write.smtplib.SMTP", _FakeSMTP)
    # dry_run short-circuits in the gateway BEFORE the handler. Use approved path so the
    # Lớp B queue is skipped and we'd reach the handler if not for dry-run.
    gw = _gateway(settings_factory, tmp_path, dry_run=True)
    result = email_write.deliver_email_report(
        "body", "Daily", gateway=gw, smtp=_smtp(), report_date="2026-06-26", approved=True
    )
    assert result.status == "dry_run"
    assert not _FakeSMTP.instances


def test_kill_switch_refuses(settings_factory, tmp_path, monkeypatch):
    monkeypatch.setattr("my_crew.actions.email_write.smtplib.SMTP", _FakeSMTP)
    gw = _gateway(settings_factory, tmp_path, dry_run=False, write_disabled=True)
    with pytest.raises(WriteDisabledError):
        email_write.deliver_email_report(
            "body", "Daily", gateway=gw, smtp=_smtp(), report_date="2026-06-26", approved=True
        )
    assert not _FakeSMTP.instances


# --- wrapper refusals before the gateway ---


def test_refuses_empty_body(settings_factory, tmp_path):
    gw = _gateway(settings_factory, tmp_path, dry_run=False)
    with pytest.raises(ValueError, match="empty"):
        email_write.deliver_email_report(
            "  ", "Daily", gateway=gw, smtp=_smtp(), report_date="2026-06-26"
        )


def test_refuses_no_recipient(settings_factory, tmp_path):
    gw = _gateway(settings_factory, tmp_path, dry_run=False)
    smtp = SmtpConfig(smtp_host="smtp.test", smtp_user="b@test", from_addr="b@test")
    with pytest.raises(RuntimeError, match="recipient"):
        email_write.deliver_email_report(
            "body", "Daily", gateway=gw, smtp=smtp, report_date="2026-06-26"
        )


# --- approved dispatch performs the real (faked) send ---


def test_dispatch_approved_email_sends(monkeypatch):
    monkeypatch.setattr("my_crew.actions.email_write.smtplib.SMTP", _FakeSMTP)
    monkeypatch.setenv("SMTP_PASSWORD", "app-pw")
    config = build_reporting_config_from_dict(
        {"smtp": {"host": "smtp.test", "user": "bot@test", "recipients": "lead@team.com"}}
    )
    action = {
        "type": "email_send", "to": ["lead@team.com"], "subject": "Daily", "body": "3 done"
    }
    summary = approved_dispatch.dispatch_approved_action(action, config)
    assert "1 recipient" in summary
    sent = _FakeSMTP.instances[0]
    assert sent.started_tls is True
    assert sent.logged_in == ("bot@test", "app-pw")
    assert sent.sent["To"] == "lead@team.com"


def test_dispatch_email_without_smtp_raises():
    config = build_reporting_config_from_dict({})  # no smtp
    action = {"type": "email_send", "to": "x@y.com", "subject": "s", "body": "b"}
    with pytest.raises(RuntimeError, match="smtp not configured"):
        approved_dispatch.dispatch_approved_action(action, config)


# --- credential safety: password never on the persisted action ---


def test_password_never_on_action(settings_factory, tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "super-secret-pw")
    gw = _gateway(settings_factory, tmp_path, dry_run=False)
    email_write.deliver_email_report(
        "body", "Daily", gateway=gw, smtp=_smtp(), report_date="2026-06-26"
    )
    pending = gw.pending_approvals()
    assert pending
    assert "super-secret-pw" not in str(pending[0].action)
    assert "SMTP_PASSWORD" not in str(pending[0].action)


# --- attachment: confined to the artifact dir, still Lớp B, path (not bytes) on the action ---


def _make_xlsx(gw, name: str = "resource-2026-06-26.xlsx") -> str:
    """Write a tiny file inside the gateway's artifact dir; return its path string."""
    gw.artifact_root.mkdir(parents=True, exist_ok=True)
    p = gw.artifact_root / name
    p.write_bytes(b"PK\x03\x04 fake-xlsx-bytes")  # zip magic; content irrelevant here
    return str(p)


def test_attachment_inside_artifact_dir_queues_for_approval(settings_factory, tmp_path):
    gw = _gateway(settings_factory, tmp_path, dry_run=False)
    path = _make_xlsx(gw)
    result = email_write.deliver_email_report(
        "body", "Weekly", gateway=gw, smtp=_smtp(),
        report_date="2026-06-26", attachment_path=path,
    )
    assert result.status == "pending_approval"
    pending = gw.pending_approvals()
    assert pending
    # Path rides the action; bytes do not (audit/approval store stays small).
    assert pending[0].action["attachment_path"] == path
    assert "fake-xlsx-bytes" not in str(pending[0].action)


def test_attachment_traversal_is_hard_denied(settings_factory, tmp_path):
    from my_crew.actions.action_gateway import HardBlockedError

    gw = _gateway(settings_factory, tmp_path, dry_run=False)
    outside = tmp_path / "secret.xlsx"
    outside.write_bytes(b"PK\x03\x04")
    traversal = str(gw.artifact_root / ".." / "secret.xlsx")
    with pytest.raises(HardBlockedError):
        email_write.deliver_email_report(
            "body", "Weekly", gateway=gw, smtp=_smtp(),
            report_date="2026-06-26", attachment_path=traversal,
        )


def test_attachment_absolute_elsewhere_denied(settings_factory, tmp_path):
    from my_crew.actions.action_gateway import HardBlockedError

    gw = _gateway(settings_factory, tmp_path, dry_run=False)
    with pytest.raises(HardBlockedError):
        email_write.deliver_email_report(
            "body", "Weekly", gateway=gw, smtp=_smtp(),
            report_date="2026-06-26", attachment_path="/etc/passwd",
        )


def test_attachment_missing_file_denied(settings_factory, tmp_path):
    from my_crew.actions.action_gateway import HardBlockedError

    gw = _gateway(settings_factory, tmp_path, dry_run=False)
    ghost = str(gw.artifact_root / "resource-2026-06-26.xlsx")  # never written
    with pytest.raises(HardBlockedError):
        email_write.deliver_email_report(
            "body", "Weekly", gateway=gw, smtp=_smtp(),
            report_date="2026-06-26", attachment_path=ghost,
        )


def test_approved_send_attaches_xlsx(settings_factory, tmp_path, monkeypatch):
    monkeypatch.setattr("my_crew.actions.email_write.smtplib.SMTP", _FakeSMTP)
    monkeypatch.setenv("SMTP_PASSWORD", "app-pw")
    gw = _gateway(settings_factory, tmp_path, dry_run=False)
    path = _make_xlsx(gw, "okr-2026-06-26.xlsx")
    email_write.deliver_email_report(
        "body", "Weekly", gateway=gw, smtp=_smtp(),
        report_date="2026-06-26", attachment_path=path, approved=True,
    )
    sent = _FakeSMTP.instances[0].sent
    attachments = [p for p in sent.iter_attachments()]
    assert len(attachments) == 1
    assert attachments[0].get_filename() == "okr-2026-06-26.xlsx"
    assert attachments[0].get_content_type() == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
