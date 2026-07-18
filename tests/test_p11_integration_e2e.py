"""M3-P11 S4: offline integration e2e — channel registry wired into all 3 report graphs.

Drives the REAL `_deliver` node of each graph (via the deps factory) with a fake gateway/
SMTP. Proves: email is delivered (queued Lớp B) for internal when `smtp` configured; NO
email for external (red line) or when no smtp (backward-compat); the Linear comment +
email approve paths dispatch to the real (faked) handlers. No live keys, no real send.
"""

from __future__ import annotations

import pytest

from my_crew.actions import approved_dispatch
from my_crew.actions.action_gateway import ActionGateway
from my_crew.agent.okr_report_graph import default_okr_deps
from my_crew.agent.report_graph import default_report_deps
from my_crew.agent.resource_report_graph import default_resource_deps
from my_crew.audit.audit_log import AuditLog
from my_crew.config.config_builders import build_reporting_config_from_dict


def _config(*, smtp: bool):
    d = {
        "slack_report_channel": "#reports",
        "extra_servers": [
            {"name": "linear", "mcp_dist": "/x/index.js", "required_env": ["LINEAR_API_TOKEN"]}
        ],
    }
    if smtp:
        d["smtp"] = {"host": "smtp.test", "user": "bot@test", "recipients": "lead@team.com"}
    return build_reporting_config_from_dict(d)


def _gateway(settings_factory, tmp_path, **kw):
    settings = settings_factory(**kw)
    return ActionGateway(settings=settings, audit_log=AuditLog(tmp_path / "audit.jsonl"))


@pytest.fixture
def _fake_writes(monkeypatch):
    """Fake Confluence + Slack so _deliver's core path runs offline.

    `create_report_page` is lazy-imported inside every deps factory ⇒ patch at source.
    `deliver_report` is bound at MODULE level in report_graph (line 22) but lazy-imported
    in okr/resource ⇒ patch the source AND the report_graph module binding.
    """

    class _Page:
        url = "https://conf/x"

    def _fake_page(*a, **k):
        return type("R", (), {"status": "dry_run"})(), _Page()

    def _fake_slack(*a, **k):
        return type("R", (), {"status": "dry_run", "approval_id": None})()

    monkeypatch.setattr("my_crew.actions.confluence_write.create_report_page", _fake_page)
    monkeypatch.setattr("my_crew.actions.slack_write.deliver_report", _fake_slack)
    monkeypatch.setattr("my_crew.agent.report_graph.deliver_report", _fake_slack)


_DEPS = {
    "daily": lambda **kw: default_report_deps(report_kind="daily", **kw),
    "okr": lambda **kw: default_okr_deps(**kw),
    "resource": lambda **kw: default_resource_deps(**kw),
}


@pytest.mark.parametrize("kind", ["daily", "okr", "resource"])
def test_internal_with_smtp_queues_email(kind, settings_factory, tmp_path, _fake_writes):
    gw = _gateway(settings_factory, tmp_path, dry_run=False)
    deps = _DEPS[kind](
        config=_config(smtp=True), settings=settings_factory(dry_run=False),
        audience="internal", gateway=gw,
    )
    ok, summary = deps.deliver("short", "full report body")
    assert "email=pending_approval" in summary  # Lớp B queued
    assert gw.pending_approvals()  # the email is in the approval queue


def test_email_redeliver_matches_lop_b_pattern(settings_factory, tmp_path, _fake_writes):
    """A re-run of _deliver re-queues the email — same Lớp B behavior as external Slack.

    Lớp B actions enqueue for approval BEFORE the idempotency stage (gateway order:
    interrupt → ... → dedup), so a re-run queues a fresh approval rather than dedups. This
    is the existing, by-design property of every Lớp B action (external Slack post since
    Phase 5), not a P11 regression. The dedup_hint guards the APPROVED execute path below.
    """
    gw = _gateway(settings_factory, tmp_path, dry_run=False)
    deps = default_report_deps(
        report_kind="daily", config=_config(smtp=True),
        settings=settings_factory(dry_run=False), audience="internal", gateway=gw,
    )
    _, s1 = deps.deliver("short", "body")
    _, s2 = deps.deliver("short", "body")
    assert "email=pending_approval" in s1 and "email=pending_approval" in s2


def test_approved_email_dedups_on_resend(settings_factory, tmp_path, monkeypatch):
    """The APPROVED send path dedups by (recipients, date) — a re-approve is idempotent."""
    from my_crew.actions.email_write import deliver_email_report
    from my_crew.config.smtp_config import SmtpConfig

    monkeypatch.setattr("my_crew.actions.email_write.smtplib.SMTP", lambda *a, **k: _NoopSMTP())
    smtp = SmtpConfig(smtp_host="smtp.test", smtp_user="b@test", from_addr="b@test",
                      recipients=("lead@team.com",))
    gw = _gateway(settings_factory, tmp_path, dry_run=False)
    r1 = deliver_email_report("body", "Daily", gateway=gw, smtp=smtp,
                              report_date="2026-06-27", approved=True)
    r2 = deliver_email_report("body", "Daily", gateway=gw, smtp=smtp,
                              report_date="2026-06-27", approved=True)
    assert r1.status == "executed"
    assert r2.status == "deduplicated"  # same (recipients, date) ⇒ idempotent


class _NoopSMTP:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, *a):
        pass

    def send_message(self, m):
        pass


@pytest.mark.parametrize("kind", ["daily", "okr", "resource"])
def test_external_never_emails(kind, settings_factory, tmp_path, _fake_writes):
    """Red line: external audience takes no extra channel (email withheld)."""
    gw = _gateway(settings_factory, tmp_path, dry_run=False)
    config = _config(smtp=True)
    # external needs a stakeholder channel; set one so _deliver doesn't raise.
    config = build_reporting_config_from_dict(
        {
            "slack_report_channel": "#reports",
            "slack_stakeholder_channel": "#stake",
            "slack_external_channels": ["#stake"],
            "smtp": {"host": "smtp.test", "user": "b@test", "recipients": "x@y.com"},
        }
    )
    deps = _DEPS[kind](
        config=config, settings=settings_factory(dry_run=False), audience="external", gateway=gw,
    )
    ok, summary = deps.deliver("short", "full report body")
    assert "email=" not in summary
    assert not gw.pending_approvals()  # nothing queued for email


@pytest.mark.parametrize("kind", ["daily", "okr", "resource"])
def test_no_smtp_backward_compat(kind, settings_factory, tmp_path, _fake_writes):
    """No smtp ⇒ no email channel ⇒ summary byte-identical (no email= suffix)."""
    gw = _gateway(settings_factory, tmp_path, dry_run=False)
    deps = _DEPS[kind](
        config=_config(smtp=False), settings=settings_factory(dry_run=False),
        audience="internal", gateway=gw,
    )
    ok, summary = deps.deliver("short", "full report body")
    assert "email=" not in summary
    assert summary.startswith("confluence=")


def test_approve_linear_comment_dispatches(monkeypatch):
    config = _config(smtp=True)
    monkeypatch.setattr("my_crew.actions.linear_write.call_tool", lambda s, t, a: {"id": "CMT-1"})
    action = {
        "type": "mcp_tool", "server": "linear", "tool": "linear_createComment",
        "args": {"issueId": "ISS-1", "body": "ping"},
    }
    assert "CMT-1" in approved_dispatch.dispatch_approved_action(action, config)


def test_approve_email_dispatches(monkeypatch):
    config = _config(smtp=True)
    monkeypatch.setenv("SMTP_PASSWORD", "pw")
    sent = {}

    class _FakeSMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            sent["tls"] = True

        def login(self, u, p):
            sent["login"] = (u, p)

        def send_message(self, m):
            sent["to"] = m["To"]

    monkeypatch.setattr("my_crew.actions.email_write.smtplib.SMTP", _FakeSMTP)
    action = {"type": "email_send", "to": ["lead@team.com"], "subject": "s", "body": "b"}
    summary = approved_dispatch.dispatch_approved_action(action, config)
    assert "recipient" in summary and sent["to"] == "lead@team.com"
