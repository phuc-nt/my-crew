"""Phase 2: Lớp B interrupt (queue + approve) + audit query."""

from __future__ import annotations

import pytest

from my_crew.actions.action_gateway import ActionGateway, HardBlockedError
from my_crew.actions.hard_block import needs_interrupt
from my_crew.audit.audit_log import AuditEntry, AuditLog

MERGE = {"type": "gh_cli", "argv": ["pr", "merge", "42"]}
CLOSE_ISSUE = {"type": "mcp_tool", "server": "jira", "tool": "closeIssue", "args": {"key": "AB-1"}}
POST = {"type": "mcp_tool", "server": "slack", "tool": "post_message",
        "args": {"channel": "C1", "text": "x"}}


def _gw(settings_factory, tmp_path, **kw):
    return ActionGateway(
        settings=settings_factory(**kw), audit_log=AuditLog(tmp_path / "audit.jsonl")
    )


# --- Lớp B classification ---


@pytest.mark.parametrize("action", [MERGE, CLOSE_ISSUE,
                                    {"type": "gh_cli", "argv": ["pr", "close", "1"]}])
def test_lop_b_actions_need_interrupt(action):
    assert needs_interrupt(action).interrupt is True


@pytest.mark.parametrize("action", [POST,
                                    {"type": "gh_cli", "argv": ["pr", "list"]}])
def test_auto_actions_no_interrupt(action):
    assert needs_interrupt(action).interrupt is False


# --- Gateway queue + approve flow ---


def test_lop_b_queued_not_executed(settings_factory, tmp_path):
    gw = _gw(settings_factory, tmp_path, dry_run=False)
    posted = []
    result = gw.execute(MERGE, handler=lambda a: posted.append(a) or "MERGED")
    assert result.status == "pending_approval"
    assert result.approval_id is not None
    assert posted == []  # handler NOT called
    assert len(gw.pending_approvals()) == 1


def test_approve_executes(settings_factory, tmp_path):
    gw = _gw(settings_factory, tmp_path, dry_run=False)
    posted = []
    queued = gw.execute(MERGE, handler=lambda a: "x")
    result = gw.approve(queued.approval_id, handler=lambda a: posted.append(a) or "MERGED")
    assert result.status == "executed"
    assert len(posted) == 1
    assert gw.pending_approvals() == []  # consumed


def test_approve_unknown_id_raises(settings_factory, tmp_path):
    gw = _gw(settings_factory, tmp_path, dry_run=False)
    with pytest.raises(ValueError):
        gw.approve(999, handler=lambda a: "x")


def test_approve_twice_raises(settings_factory, tmp_path):
    gw = _gw(settings_factory, tmp_path, dry_run=False)
    queued = gw.execute(MERGE, handler=lambda a: "x")
    gw.approve(queued.approval_id, handler=lambda a: "x")
    with pytest.raises(ValueError, match="approved"):
        gw.approve(queued.approval_id, handler=lambda a: "x")


def test_lop_a_wins_over_lop_b(settings_factory, tmp_path):
    # A force-push is Lớp A (data loss) — must hard-block, never queue.
    gw = _gw(settings_factory, tmp_path, dry_run=False)
    with pytest.raises(HardBlockedError):
        gw.execute({"type": "gh_cli", "argv": ["push", "--force"]}, handler=lambda a: "x")
    assert gw.pending_approvals() == []


def test_reject(settings_factory, tmp_path):
    gw = _gw(settings_factory, tmp_path, dry_run=False)
    queued = gw.execute(MERGE, handler=lambda a: "x")
    gw.reject(queued.approval_id)
    assert gw.pending_approvals() == []
    with pytest.raises(ValueError):
        gw.approve(queued.approval_id, handler=lambda a: "x")  # not pending anymore


# --- M2-P5: execute_approved (graph-interrupt resume runs live, not re-queued) ---


def test_execute_approved_runs_live_not_requeued(settings_factory, tmp_path):
    # A Lớp B action via execute_approved must run NOW (human approved at the graph
    # interrupt), NOT enqueue a second pending_approval. This is the C1 fix.
    gw = _gw(settings_factory, tmp_path, dry_run=False)
    posted = []
    result = gw.execute_approved(MERGE, handler=lambda a: posted.append(a) or "MERGED")
    assert result.status == "executed"
    assert len(posted) == 1
    assert gw.pending_approvals() == []  # nothing queued


def test_execute_approved_still_blocked_by_lop_a(settings_factory, tmp_path):
    # The approve-bypass passes a NOT_ALLOWLISTED block, but a real Lớp A hard-deny
    # (data loss) is NEVER overridable, even when approved.
    gw = _gw(settings_factory, tmp_path, dry_run=False)
    with pytest.raises(HardBlockedError):
        gw.execute_approved({"type": "gh_cli", "argv": ["push", "--force"]},
                            handler=lambda a: "x")
    assert gw.pending_approvals() == []


def test_execute_approved_dedup_blocks_double_post(settings_factory, tmp_path):
    # Resuming twice (double-approve) must not double-execute: dedup reserves the key.
    gw = _gw(settings_factory, tmp_path, dry_run=False)
    posted = []
    a = dict(MERGE, dedup_hint="merge-42-once")
    first = gw.execute_approved(a, handler=lambda x: posted.append(x) or "MERGED")
    second = gw.execute_approved(a, handler=lambda x: posted.append(x) or "MERGED")
    assert first.status == "executed"
    assert second.status == "deduplicated"
    assert len(posted) == 1  # ran once


# --- Audit query ---


def test_audit_query_filters(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.record(AuditEntry(action_type="mcp_tool", tool="slack:post", verdict="allow",
                          timestamp="2026-06-20T10:00:00"))
    log.record(AuditEntry(action_type="mcp_tool", tool="confluence:createPage", verdict="deny",
                          timestamp="2026-06-21T10:00:00"))
    log.record(AuditEntry(action_type="gh_cli", tool="gh pr merge", verdict="pending",
                          timestamp="2026-06-22T10:00:00"))

    assert len(log.query()) == 3
    assert log.query()[0]["tool"] == "gh pr merge"  # newest first
    assert len(log.query(verdict="deny")) == 1
    assert len(log.query(tool="slack")) == 1
    assert len(log.query(since="2026-06-21")) == 2
    assert len(log.query(limit=1)) == 1


def test_audit_query_empty(tmp_path):
    assert AuditLog(tmp_path / "nope.jsonl").query() == []


# --- Review fixes: H1, M1, M2, M3, L1, H2 ---


def test_execute_has_no_public_skip_interrupt():
    # H1: the approval bypass must not be reachable via the public execute().
    import inspect

    assert "skip_interrupt" not in inspect.signature(ActionGateway.execute).parameters


def test_dedup_released_on_handler_failure(settings_factory, tmp_path):
    # M1: a failed handler releases its dedup reservation so a retry can run.
    gw = _gw(settings_factory, tmp_path, dry_run=False)
    with pytest.raises(RuntimeError):
        gw.execute(POST, handler=lambda a: (_ for _ in ()).throw(ValueError("boom")))
    assert gw.execute(POST, handler=lambda a: "OK").status == "executed"


def test_reject_is_audited(settings_factory, tmp_path):
    # M3: rejecting a sensitive action leaves a trace in the immutable log.
    gw = _gw(settings_factory, tmp_path, dry_run=False)
    queued = gw.execute(MERGE, handler=lambda a: "x")
    gw.reject(queued.approval_id)
    rejects = [e for e in AuditLog(tmp_path / "audit.jsonl").query() if e["verdict"] == "reject"]
    assert len(rejects) == 1


def test_approval_store_redacts_secret(settings_factory, tmp_path):
    # M2: a secret in a queued action is redacted in the approval store.
    from my_crew.actions.approval_store import ApprovalStore

    store = ApprovalStore(tmp_path / "approvals.db")
    aid = store.enqueue(
        {"type": "gh_cli", "argv": ["pr", "merge"], "token": "xoxb-FAKE1234567890"},
        reason="r",
    )
    got = store.get(aid)
    assert "xoxb-FAKE1234567890" not in str(got.action)
    assert got.action.get("token") == "***REDACTED***"


def test_external_channel_post_needs_approval(settings_factory, tmp_path):
    # H2: posting to an external channel is Lớp B; internal stays auto.
    gw = ActionGateway(
        settings=settings_factory(dry_run=False),
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
        external_channels=frozenset({"C_EXTERNAL"}),
    )
    ext = {"type": "mcp_tool", "server": "slack", "tool": "post_message",
           "args": {"channel": "C_EXTERNAL", "text": "hi stakeholder"}}
    internal = {"type": "mcp_tool", "server": "slack", "tool": "post_message",
                "args": {"channel": "C_INTERNAL", "text": "team update"}}
    assert gw.execute(ext, handler=lambda a: "x").status == "pending_approval"
    assert gw.execute(internal, handler=lambda a: "x").status == "executed"
