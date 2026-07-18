"""M3-P11 S4: consolidated red-line suite for the new write authority (Linear + email).

Every new write stays behind the default-DENY allowlist + Lớp A red line + Lớp B approval.
This file is the one-stop assertion that P11 did not weaken the guardrail.
"""

from __future__ import annotations

import pytest

from my_crew.actions.action_gateway import ActionGateway, HardBlockedError, WriteDisabledError
from my_crew.actions.hard_block import BlockCategory, classify, needs_interrupt
from my_crew.audit.audit_log import AuditLog


def _gw(settings_factory, tmp_path, **kw):
    return ActionGateway(
        settings=settings_factory(**kw), audit_log=AuditLog(tmp_path / "a.jsonl")
    )


# --- Lớp A: destructive Linear tools hard-denied even though linear is allowlisted ---


@pytest.mark.parametrize(
    "tool", ["linear_deleteIssue", "linear_archiveProject", "linear_removeLabel"]
)
def test_destructive_linear_data_loss(tool):
    v = classify({"type": "mcp_tool", "server": "linear", "tool": tool, "args": {"id": "X"}})
    assert v.blocked and v.category == BlockCategory.DATA_LOSS


# --- default-DENY: a NEW (unlisted) linear write tool is denied by default ---


@pytest.mark.parametrize("tool", ["linear_updateIssue", "linear_createIssue", "linear_setState"])
def test_unlisted_linear_write_denied(tool):
    v = classify({"type": "mcp_tool", "server": "linear", "tool": tool, "args": {}})
    assert v.blocked and v.category == BlockCategory.NOT_ALLOWLISTED


# --- Lớp B: the one allowlisted Linear write queues for approval ---


def test_linear_comment_is_lop_b():
    a = {"type": "mcp_tool", "server": "linear", "tool": "linear_createComment",
         "args": {"issueId": "I", "body": "x"}}
    assert classify(a).blocked is False
    assert needs_interrupt(a).interrupt is True


# --- email: secrets / empty denied; every well-formed send is Lớp B ---


def test_email_secret_credential_denied():
    a = {"type": "email_send", "to": "x@y.com", "subject": "r",
         "body": "ghp_abcdefghij1234567890XYZ"}
    assert classify(a).category == BlockCategory.CREDENTIAL


@pytest.mark.parametrize(
    "action",
    [
        {"type": "email_send", "to": "", "subject": "r", "body": "hi"},
        {"type": "email_send", "to": "x@y.com", "subject": "r", "body": "  "},
    ],
)
def test_email_malformed_denied(action):
    assert classify(action).blocked is True


def test_every_email_is_lop_b():
    for to in ["internal@company.com", "external@vendor.com", ["a@x.com", "b@y.com"]]:
        a = {"type": "email_send", "to": to, "subject": "r", "body": "report"}
        assert classify(a).blocked is False
        assert needs_interrupt(a).interrupt is True


# --- kill-switch refuses both new writes ---


def test_kill_switch_refuses_linear(settings_factory, tmp_path, monkeypatch):
    monkeypatch.setattr("my_crew.actions.linear_write.call_tool", lambda *a, **k: {"id": "x"})
    gw = _gw(settings_factory, tmp_path, dry_run=False, write_disabled=True)
    a = {"type": "mcp_tool", "server": "linear", "tool": "linear_createComment",
         "args": {"issueId": "I", "body": "x"}}
    # createComment is Lớp B → queued before kill-switch on the public path; force the
    # approved path so the kill-switch guard is the one that fires.
    with pytest.raises(WriteDisabledError):
        gw.execute_approved(a, handler=lambda x: "ran")


def test_kill_switch_refuses_email(settings_factory, tmp_path):
    gw = _gw(settings_factory, tmp_path, dry_run=False, write_disabled=True)
    a = {"type": "email_send", "to": "x@y.com", "subject": "s", "body": "b"}
    with pytest.raises(WriteDisabledError):
        gw.execute_approved(a, handler=lambda x: "sent")


# --- Lớp A is never overridable, even on the approved path ---


def test_approved_cannot_override_lop_a_email_secret(settings_factory, tmp_path):
    gw = _gw(settings_factory, tmp_path, dry_run=False)
    a = {"type": "email_send", "to": "x@y.com", "subject": "s",
         "body": "ghp_abcdefghij1234567890XYZ"}
    with pytest.raises(HardBlockedError):
        gw.execute_approved(a, handler=lambda x: "sent")
