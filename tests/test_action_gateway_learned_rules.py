"""v67 learned Lớp B rules at the gateway guarded path: deny refuses, always runs,
neither loosens Lớp A / kill-switch; autonomous never consults rules."""

from __future__ import annotations

import pytest

from my_crew.actions.action_gateway import ActionGateway, WriteDisabledError
from my_crew.actions.approval_rule_store import SCOPE_ALWAYS, SCOPE_DENY
from my_crew.audit.audit_log import AuditLog

EMAIL = {
    "type": "email_send",
    "to": "ceo@acme.com",
    "subject": "hi",
    "body": "the quarterly numbers are attached in the body text here",
}


def _gw(settings_factory, tmp_path, **kw):
    return ActionGateway(
        settings=settings_factory(dry_run=False, **kw),
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
    )


def test_no_rule_still_queues(settings_factory, tmp_path):
    """Baseline: email with no learned rule queues for approval (unchanged behavior)."""
    gw = _gw(settings_factory, tmp_path)
    r = gw.execute(EMAIL, handler=lambda a: "SENT")
    assert r.status == "pending_approval"


def test_always_rule_runs_straight_through(settings_factory, tmp_path):
    gw = _gw(settings_factory, tmp_path)
    gw.approval_rules.add_rule(EMAIL, scope=SCOPE_ALWAYS, created_by="ceo")
    calls = []
    r = gw.execute(EMAIL, handler=lambda a: calls.append(a) or "SENT")
    assert r.status == "executed"
    assert calls  # handler actually ran


def test_deny_rule_refuses_and_does_not_run(settings_factory, tmp_path):
    gw = _gw(settings_factory, tmp_path)
    gw.approval_rules.add_rule(EMAIL, scope=SCOPE_DENY, created_by="ceo")
    calls = []
    r = gw.execute(EMAIL, handler=lambda a: calls.append(a) or "SENT")
    assert r.status == "rejected_by_rule"
    assert calls == []  # never executed, never queued


def test_changed_recipient_domain_misses_always_rule(settings_factory, tmp_path):
    """The always-rule is bound to the recipient domain; a stranger domain misses → queue."""
    gw = _gw(settings_factory, tmp_path)
    gw.approval_rules.add_rule(EMAIL, scope=SCOPE_ALWAYS, created_by="ceo")
    other = {**EMAIL, "to": "stranger@evil.com"}
    r = gw.execute(other, handler=lambda a: "SENT")
    assert r.status == "pending_approval"


def test_always_rule_never_loosens_kill_switch(settings_factory, tmp_path):
    """Stricter-of-two: an always-rule cannot bypass the global kill switch."""
    gw = _gw(settings_factory, tmp_path, write_disabled=True)
    gw.approval_rules.add_rule(EMAIL, scope=SCOPE_ALWAYS, created_by="ceo")
    with pytest.raises(WriteDisabledError):
        gw.execute(EMAIL, handler=lambda a: "SENT")


def test_always_rule_never_loosens_hard_deny(settings_factory, tmp_path):
    """A Lớp A hard-deny (gh repo delete) is never a rule candidate — always-rule can't help."""
    from my_crew.actions.action_gateway import HardBlockedError

    danger = {"type": "gh_cli", "argv": ["repo", "delete", "me/x"]}
    gw = _gw(settings_factory, tmp_path)
    gw.approval_rules.add_rule(danger, scope=SCOPE_ALWAYS, created_by="ceo")
    with pytest.raises(HardBlockedError):
        gw.execute(danger, handler=lambda a: "RAN")


def test_autonomous_ignores_deny_rule(settings_factory, tmp_path):
    """CEO decision 2026-08-04: deny rules apply only in guarded. Autonomous keeps full
    authority — a deny rule must NOT block an autonomous run."""
    gw = _gw(settings_factory, tmp_path, trust_mode="autonomous")
    gw.approval_rules.add_rule(EMAIL, scope=SCOPE_DENY, created_by="ceo")
    calls = []
    r = gw.execute(EMAIL, handler=lambda a: calls.append(a) or "SENT")
    assert r.status == "executed"
    assert calls  # autonomous ran it despite the deny rule


def test_deny_rule_audited(settings_factory, tmp_path):
    import json

    gw = _gw(settings_factory, tmp_path)
    gw.approval_rules.add_rule(EMAIL, scope=SCOPE_DENY, created_by="ceo")
    gw.execute(EMAIL, handler=lambda a: "SENT")
    rows = [
        json.loads(ln)
        for ln in (tmp_path / "audit.jsonl").read_text().strip().splitlines()
        if ln.strip()
    ]
    assert rows and rows[-1]["verdict"] == "deny"
    assert "learned deny rule" in rows[-1]["reason"]
