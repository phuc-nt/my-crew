"""M3-P11 S2: gated Linear write (linear_createComment) — allowlist + Lớp B + dispatch.

Proves a NEW server's write tool is DENIED until allowlisted, then queued for human
approval (Lớp B), and that destructive Linear tools still hit the Lớp A red line.
Offline: a FAKE `call_tool` (no live key, no spawn).
"""

from __future__ import annotations

import pytest

from src.actions import approved_dispatch, linear_write
from src.actions.action_gateway import ActionGateway
from src.actions.hard_block import BlockCategory, classify, needs_interrupt
from src.audit.audit_log import AuditLog
from src.config.config_builders import build_reporting_config_from_dict

_CREATE_COMMENT = {
    "type": "mcp_tool",
    "server": "linear",
    "tool": "linear_createComment",
    "args": {"issueId": "ISS-1", "body": "overdue: please update"},
}


def _config(monkeypatch):
    monkeypatch.setenv("LINEAR_API_TOKEN", "x")
    return build_reporting_config_from_dict(
        {
            "extra_servers": [
                {"name": "linear", "mcp_dist": "/x/index.js", "required_env": ["LINEAR_API_TOKEN"]}
            ]
        }
    )


def _gateway(settings_factory, tmp_path, **kw):
    settings = settings_factory(**kw)
    return ActionGateway(settings=settings, audit_log=AuditLog(tmp_path / "audit.jsonl"))


# --- allowlist: createComment is allowed past Lớp A, but Lớp B (not auto-run) ---


def test_create_comment_is_allowlisted_not_blocked():
    """linear_createComment passes the default-DENY allowlist (it's listed)."""
    assert classify(_CREATE_COMMENT).blocked is False


def test_create_comment_is_lop_b():
    """The write is a Lớp B marker → needs human approval before executing."""
    assert needs_interrupt(_CREATE_COMMENT).interrupt is True


def test_gateway_queues_create_comment_for_approval(settings_factory, tmp_path):
    gw = _gateway(settings_factory, tmp_path, dry_run=False)
    result = gw.execute(_CREATE_COMMENT, handler=lambda a: "should-not-run")
    assert result.status == "pending_approval"
    assert result.approval_id is not None


# --- red line: destructive Linear tools hard-denied even with linear now known ---


@pytest.mark.parametrize(
    "tool", ["linear_deleteIssue", "linear_deleteComment", "linear_archiveProject"]
)
def test_destructive_linear_tools_hard_denied(tool):
    action = {"type": "mcp_tool", "server": "linear", "tool": tool, "args": {"id": "X"}}
    verdict = classify(action)
    assert verdict.blocked is True
    assert verdict.category == BlockCategory.DATA_LOSS


def test_secret_in_comment_body_credential_denied():
    action = {
        "type": "mcp_tool",
        "server": "linear",
        "tool": "linear_createComment",
        "args": {"issueId": "ISS-1", "body": "key ghp_abcdefghij1234567890XYZ"},
    }
    assert classify(action).category == BlockCategory.CREDENTIAL


# --- regression: the new "createcomment" marker must NOT catch other servers' tools ---


def test_jira_addcomment_still_auto_not_lop_b():
    jira = {"type": "mcp_tool", "server": "jira", "tool": "addComment",
            "args": {"key": "AB-1", "body": "ok"}}
    assert needs_interrupt(jira).interrupt is False
    assert classify(jira).blocked is False


def test_confluence_createpage_still_auto_not_lop_b():
    conf = {"type": "mcp_tool", "server": "confluence", "tool": "createPage",
            "args": {"title": "t", "body": "b"}}
    assert needs_interrupt(conf).interrupt is False


# --- post_comment wrapper: refuses bad input before the gateway ---


def test_post_comment_refuses_empty_body(monkeypatch, settings_factory, tmp_path):
    gw = _gateway(settings_factory, tmp_path, dry_run=False)
    with pytest.raises(ValueError, match="empty"):
        linear_write.post_comment(
            "  ", gateway=gw, config=_config(monkeypatch), issue_id="ISS-1",
            report_date="2026-06-26",
        )


def test_post_comment_refuses_missing_issue(monkeypatch, settings_factory, tmp_path):
    gw = _gateway(settings_factory, tmp_path, dry_run=False)
    with pytest.raises(ValueError, match="issue_id"):
        linear_write.post_comment(
            "body", gateway=gw, config=_config(monkeypatch), issue_id="", report_date="2026-06-26"
        )


def test_post_comment_queues_for_approval(monkeypatch, settings_factory, tmp_path):
    gw = _gateway(settings_factory, tmp_path, dry_run=False)
    result = linear_write.post_comment(
        "overdue", gateway=gw, config=_config(monkeypatch), issue_id="ISS-1",
        report_date="2026-06-26",
    )
    assert result.status == "pending_approval"


# --- approved dispatch routes the approved comment to the real (faked) handler ---


def test_dispatch_approved_linear_comment(monkeypatch):
    config = _config(monkeypatch)
    captured = {}

    def fake_call_tool(spec, tool_name, args):
        captured["spec"] = spec.name
        captured["tool"] = tool_name
        captured["args"] = args
        return {"id": "CMT-9"}

    monkeypatch.setattr("src.actions.linear_write.call_tool", fake_call_tool)
    summary = approved_dispatch.dispatch_approved_action(_CREATE_COMMENT, config)
    assert captured == {
        "spec": "linear",
        "tool": "linear_createComment",
        "args": {"issueId": "ISS-1", "body": "overdue: please update"},
    }
    assert "CMT-9" in summary


def test_dispatch_unknown_server_raises(monkeypatch):
    config = _config(monkeypatch)
    action = {"type": "mcp_tool", "server": "monday", "tool": "createItem", "args": {}}
    with pytest.raises(RuntimeError, match="No live handler"):
        approved_dispatch.dispatch_approved_action(action, config)


def test_credentials_never_on_persisted_action(monkeypatch, settings_factory, tmp_path):
    """The token-bearing server env stays in the handler closure, not on the action dict."""
    gw = _gateway(settings_factory, tmp_path, dry_run=False)
    result = linear_write.post_comment(
        "overdue", gateway=gw, config=_config(monkeypatch), issue_id="ISS-1",
        report_date="2026-06-26",
    )
    pending = gw.pending_approvals()
    assert pending  # queued
    assert "LINEAR_API_TOKEN" not in str(pending[0].action)
    assert result.status == "pending_approval"
