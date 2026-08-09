"""v76 fail-mode contract: store-backed Lớp B checkpoints fail CLOSED by default and
degrade to their no-op answers ONLY under the break-glass env; Lớp A and the ops-scope
of approval commands never relax."""

from __future__ import annotations

import pytest

from my_crew.actions.action_gateway import ActionGateway
from my_crew.actions.gateway_fail_contract import (
    CHECKPOINT_FAIL_MODES,
    FAIL_CLOSED,
    FAIL_OPEN,
    break_glass_active,
)
from my_crew.audit.audit_log import AuditLog

EMAIL = {"type": "email_send", "to": "ceo@acme.com", "subject": "hi", "body": "text"}


def _gw(settings_factory, tmp_path, **kw):
    return ActionGateway(
        settings=settings_factory(dry_run=False, **kw),
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
    )


def _break(gw, which):
    def _boom(*a, **k):
        raise RuntimeError("store down")

    if which == "rules":
        gw.approval_rules.match = _boom
    elif which == "enqueue":
        gw._approvals.enqueue = _boom
    return gw


def test_contract_table_shape():
    assert CHECKPOINT_FAIL_MODES["lop_a_classify"] == FAIL_CLOSED
    assert CHECKPOINT_FAIL_MODES["audit_record"] == FAIL_CLOSED
    assert CHECKPOINT_FAIL_MODES["dedup"] == FAIL_CLOSED
    assert CHECKPOINT_FAIL_MODES["approval_push_notify"] == FAIL_OPEN
    assert CHECKPOINT_FAIL_MODES["office_bridge"] == FAIL_OPEN


def test_rules_store_down_fails_closed_without_break_glass(
    settings_factory, tmp_path, monkeypatch,
):
    monkeypatch.delenv("MYCREW_GATEWAY_FAIL_OPEN", raising=False)
    gw = _break(_gw(settings_factory, tmp_path), "rules")
    calls = []
    with pytest.raises(RuntimeError, match="store down"):
        gw.execute(EMAIL, handler=lambda a: calls.append(a) or "SENT")
    assert calls == []  # the write did NOT happen


def test_rules_store_down_with_break_glass_degrades_to_no_rule(
    settings_factory, tmp_path, monkeypatch,
):
    monkeypatch.setenv("MYCREW_GATEWAY_FAIL_OPEN", "1")
    gw = _break(_gw(settings_factory, tmp_path), "rules")
    r = gw.execute(EMAIL, handler=lambda a: "SENT")
    assert r.status == "pending_approval"  # no-rule answer: still queues, never auto-runs


def test_enqueue_down_fails_closed_without_break_glass(
    settings_factory, tmp_path, monkeypatch,
):
    monkeypatch.delenv("MYCREW_GATEWAY_FAIL_OPEN", raising=False)
    gw = _break(_gw(settings_factory, tmp_path), "enqueue")
    with pytest.raises(RuntimeError, match="store down"):
        gw.execute(EMAIL, handler=lambda a: "SENT")


def test_enqueue_down_with_break_glass_runs_with_named_rationale(
    settings_factory, tmp_path, monkeypatch,
):
    monkeypatch.setenv("MYCREW_GATEWAY_FAIL_OPEN", "1")
    gw = _break(_gw(settings_factory, tmp_path), "enqueue")
    calls = []
    r = gw.execute(EMAIL, handler=lambda a: calls.append(a) or "SENT")
    assert r.status == "executed" and calls
    rows = AuditLog(tmp_path / "audit.jsonl").query(verdict="allow")
    assert any("break-glass" in str(e.get("rationale", "")) for e in rows)


def test_break_glass_never_relaxes_lop_a(settings_factory, tmp_path, monkeypatch):
    """The env flag must not move the hard line: a Lớp A action stays denied."""
    from my_crew.actions.action_gateway import HardBlockedError

    monkeypatch.setenv("MYCREW_GATEWAY_FAIL_OPEN", "1")
    gw = _gw(settings_factory, tmp_path)
    danger = {"type": "mcp_tool", "tool_name": "jira_delete_project",
              "arguments": {"project": "SCRUM"}}
    with pytest.raises(HardBlockedError):
        gw.execute(danger, handler=lambda a: "RAN")


def test_break_glass_reads_env_only(monkeypatch):
    monkeypatch.delenv("MYCREW_GATEWAY_FAIL_OPEN", raising=False)
    assert break_glass_active() is False
    monkeypatch.setenv("MYCREW_GATEWAY_FAIL_OPEN", "true")
    assert break_glass_active() is True


def test_approval_decision_commands_stay_admin_scope():
    """my-dandori's invariant is 'the approve tool does not exist'; my-crew's is
    'it exists only behind the admin fleet scope'. Enumerate the catalog: every
    approval-DECIDING command must be absent from the non-admin (orchestration)
    subset — a personal secretary must never be able to approve for other agents."""
    from my_crew.agent.ops_catalog import OPS_COMMANDS, catalog_for_domain

    deciders = [cid for cid in OPS_COMMANDS
                if "approve" in cid or "reject" in cid or "pending_action" in cid]
    assert deciders, "catalog moved — update this test"
    non_admin = catalog_for_domain("personal")
    for cid in deciders:
        assert cid not in non_admin, f"{cid} lọt vào scope non-admin"
    assert all(cid in catalog_for_domain("admin") for cid in deciders)
