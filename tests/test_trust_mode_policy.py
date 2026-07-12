"""v30 autonomy-first: trust_mode policy at the gateway + approval gate. Offline.

Autonomous executes immediately what guarded queues (Lớp B) or denies
(allowlist-miss) — with a real handler only. Lớp A, kill-switch, dry-run and
dedup apply identically in both modes; a propose-only call always queues.
"""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from src.actions.action_gateway import (
    AUTONOMOUS_RATIONALE,
    ActionGateway,
    HardBlockedError,
    WriteDisabledError,
)
from src.audit.audit_log import AuditLog
from src.config.config_builders import build_settings_from_dict
from src.profile.loader_mapping import build_settings_dict

MERGE = {"type": "gh_cli", "argv": ["pr", "merge", "42"]}  # Lớp B (interrupt)
UNLISTED = {"type": "mcp_tool", "server": "jira", "tool": "createDashboard", "args": {}}
DELETE_PAGE = {  # Lớp A data-loss — must be denied in every mode
    "type": "mcp_tool", "server": "confluence", "tool": "deletePage", "args": {"id": "1"},
}
POST = {"type": "mcp_tool", "server": "slack", "tool": "post_message",
        "args": {"channel": "C1", "text": "x"}}


def _gw(settings_factory, tmp_path, **kw):
    return ActionGateway(
        settings=settings_factory(**kw), audit_log=AuditLog(tmp_path / "audit.jsonl")
    )


# --- autonomous: run-now for gated-but-reversible actions ---


def test_autonomous_lop_b_executes_immediately(settings_factory, tmp_path):
    gw = _gw(settings_factory, tmp_path, dry_run=False, trust_mode="autonomous")
    posted = []
    result = gw.execute(MERGE, handler=lambda a: posted.append(a) or "MERGED")
    assert result.status == "executed"
    assert len(posted) == 1
    assert gw.pending_approvals() == []


def test_autonomous_allowlist_miss_executes(settings_factory, tmp_path):
    gw = _gw(settings_factory, tmp_path, dry_run=False, trust_mode="autonomous")
    result = gw.execute(UNLISTED, handler=lambda a: "OK")
    assert result.status == "executed"


def test_autonomous_audit_rationale_is_the_marker_constant(settings_factory, tmp_path):
    gw = _gw(settings_factory, tmp_path, dry_run=False, trust_mode="autonomous")
    gw.execute(MERGE, handler=lambda a: "MERGED")
    log = AuditLog(tmp_path / "audit.jsonl")
    rows = log.query(verdict="allow")
    assert rows and rows[0]["rationale"] == AUTONOMOUS_RATIONALE


def test_autonomous_propose_only_still_queues(settings_factory, tmp_path):
    """A handler-less call (automation ProposeStep) must queue, never silently skip."""
    gw = _gw(settings_factory, tmp_path, dry_run=False, trust_mode="autonomous")
    result = gw.execute(MERGE, handler=None)
    assert result.status == "pending_approval"
    assert len(gw.pending_approvals()) == 1


# --- both modes: the nets that never lift ---


@pytest.mark.parametrize("mode", ["autonomous", "guarded"])
def test_lop_a_denied_in_both_modes(settings_factory, tmp_path, mode):
    gw = _gw(settings_factory, tmp_path, dry_run=False, trust_mode=mode)
    with pytest.raises(HardBlockedError):
        gw.execute(DELETE_PAGE, handler=lambda a: "x")


def test_autonomous_dry_run_still_no_ops(settings_factory, tmp_path):
    gw = _gw(settings_factory, tmp_path, dry_run=True, trust_mode="autonomous")
    result = gw.execute(MERGE, handler=lambda a: "MERGED")
    assert result.status == "dry_run"


def test_autonomous_kill_switch_still_refuses(settings_factory, tmp_path):
    gw = _gw(settings_factory, tmp_path, dry_run=False, write_disabled=True,
             trust_mode="autonomous")
    with pytest.raises(WriteDisabledError):
        gw.execute(MERGE, handler=lambda a: "MERGED")


def test_autonomous_dedup_still_applies(settings_factory, tmp_path):
    gw = _gw(settings_factory, tmp_path, dry_run=False, trust_mode="autonomous")
    assert gw.execute(MERGE, handler=lambda a: "MERGED").status == "executed"
    assert gw.execute(MERGE, handler=lambda a: "MERGED").status == "deduplicated"


def test_guarded_still_queues(settings_factory, tmp_path):
    gw = _gw(settings_factory, tmp_path, dry_run=False, trust_mode="guarded")
    result = gw.execute(MERGE, handler=lambda a: "MERGED")
    assert result.status == "pending_approval"


def test_marker_absent_from_guarded_approval_rationales(settings_factory, tmp_path):
    gw = _gw(settings_factory, tmp_path, dry_run=False, trust_mode="guarded")
    queued = gw.execute(MERGE, handler=lambda a: "x")
    gw.approve(queued.approval_id, handler=lambda a: "MERGED")
    log = AuditLog(tmp_path / "audit.jsonl")
    assert all(AUTONOMOUS_RATIONALE not in str(r.get("rationale", "")) for r in log.query())


# --- chat origin (enqueue_for_approval) ---


def test_autonomous_chat_any_sender_executes(settings_factory, tmp_path):
    """Explicit CEO decision: autonomous drops the trusted-sender gate for chat."""
    gw = _gw(settings_factory, tmp_path, dry_run=False, trust_mode="autonomous")
    posted = []
    result = gw.enqueue_for_approval(
        POST, reason="chat request", sender_id="stranger-99", transport="slack",
        chat_id="C1", auto_handler=lambda a: posted.append(a) or "POSTED",
    )
    assert result.status == "executed"
    assert len(posted) == 1
    assert gw.pending_approvals() == []


def test_guarded_chat_stranger_still_queues(settings_factory, tmp_path):
    gw = _gw(settings_factory, tmp_path, dry_run=False, trust_mode="guarded")
    result = gw.enqueue_for_approval(
        POST, reason="chat request", sender_id="stranger-99", transport="slack",
        chat_id="C1", auto_handler=lambda a: "POSTED",
    )
    assert result.status == "pending_approval"


def test_autonomous_chat_lop_a_still_refused(settings_factory, tmp_path):
    gw = _gw(settings_factory, tmp_path, dry_run=False, trust_mode="autonomous")
    result = gw.enqueue_for_approval(
        DELETE_PAGE, reason="chat request", sender_id="ceo", transport="telegram",
        chat_id="1", auto_handler=lambda a: "x",
    )
    assert result.status == "skipped"  # hard-denied, not queued, not run


# --- config resolution ---


def test_trust_mode_default_is_autonomous():
    assert build_settings_from_dict({}).trust_mode == "autonomous"


def test_trust_mode_invalid_value_fails_loud():
    with pytest.raises(ValueError, match="trust_mode"):
        build_settings_from_dict({"trust_mode": "yolo"})


def test_profile_yaml_overrides_env_both_directions(monkeypatch, tmp_path):
    monkeypatch.setenv("TRUST_MODE", "autonomous")
    d = build_settings_dict({"safety": {"trust_mode": "guarded"}}, tmp_path)
    assert build_settings_from_dict(d).trust_mode == "guarded"

    monkeypatch.setenv("TRUST_MODE", "guarded")
    d = build_settings_dict({"safety": {"trust_mode": "autonomous"}}, tmp_path)
    assert build_settings_from_dict(d).trust_mode == "autonomous"
    # yaml silent + env set → env wins
    d = build_settings_dict({}, tmp_path)
    assert build_settings_from_dict(d).trust_mode == "guarded"


# --- approval_gate node (graph-native Lớp B seam) ---


def _checkpointer() -> SqliteSaver:
    saver = SqliteSaver(sqlite3.connect(":memory:", check_same_thread=False))
    saver.setup()
    return saver


def _fake_deps(deliver):
    from src.agent.report_graph import ReportDeps
    from src.tools.models import CiRun, Issue, PullRequest, Risk

    return ReportDeps(
        fetch_issues=lambda: [Issue(key="AB-1", summary="x", status="In Progress",
                                    assignee="P", due_date=date(2026, 6, 1),
                                    labels=("blocked",))],
        fetch_prs=lambda: [PullRequest(number=9, title="y", author="p",
                                       updated_at=date(2026, 6, 1), review_decision=None,
                                       checks_state="FAILURE", age_days=20, stale=True)],
        fetch_ci=lambda: [CiRun(workflow="ci", status="completed", conclusion="failure")],
        analyze_risks=lambda i, p, c: [Risk(kind="blocker", severity="high", subject="AB-1",
                                            detail="d", suggested_action="a")],
        compose=lambda risks: ("<h2>Báo cáo</h2>", 0.0002, "*short*"),
        deliver=deliver,
    )


class _DeliverSpy:
    def __init__(self):
        self.calls = 0

    def __call__(self, short, body, approved=False):
        self.calls += 1
        return True, "slack=executed"


def test_approval_gate_autonomous_delivers_without_interrupt(settings_factory):
    from src.agent.report_graph import build_report_graph

    spy = _DeliverSpy()
    graph = build_report_graph(
        deps=_fake_deps(spy), audience="external", checkpointer=_checkpointer(),
        settings=settings_factory(trust_mode="autonomous"),
    )
    cfg = {"configurable": {"thread_id": "t-auto"}}
    result = graph.invoke({}, cfg)
    assert spy.calls == 1  # delivered with no human resume
    assert result.get("auto_approved") is True


def test_approval_gate_without_settings_still_interrupts():
    """settings=None (deps-injected callers) must stay guarded — fail-safe default."""
    from src.agent.report_graph import build_report_graph

    spy = _DeliverSpy()
    graph = build_report_graph(
        deps=_fake_deps(spy), audience="external", checkpointer=_checkpointer(),
    )
    cfg = {"configurable": {"thread_id": "t-none"}}
    result = graph.invoke({}, cfg)
    assert spy.calls == 0  # paused at the gate
    assert "__interrupt__" in result
