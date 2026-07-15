"""v46 Phase 4: end-to-end actor attribution — two agents' actions are recorded + queryable by
actor, every outcome branch is attributed, approvals carry the actor, and governance is unchanged.
"""

from __future__ import annotations

import pytest

from src.actions.action_gateway import ActionGateway, HardBlockedError
from src.actions.approval_store import ApprovalStore
from src.audit.audit_log import AuditLog

POST = {"type": "mcp_tool", "server": "slack", "tool": "post_message",
        "args": {"channel": "C1", "text": "hi"}}


def _gw(settings_factory, tmp_path, agent, **kw):
    """A gateway for `agent` writing to that agent's own audit.jsonl (per-agent path)."""
    adir = tmp_path / agent
    kw.setdefault("dry_run", False)
    return ActionGateway(
        settings=settings_factory(**kw),
        audit_log=AuditLog(adir / "audit.jsonl"),
        approval_store=ApprovalStore(adir / "approvals.db"),
        actor=agent,
    )


def _rows(tmp_path, agent):
    import json

    p = tmp_path / agent / "audit.jsonl"
    return [json.loads(x) for x in p.read_text().strip().splitlines()] if p.exists() else []


def test_two_agents_attributed_and_filterable(settings_factory, tmp_path):
    """Cross-agent: each agent's actions carry its actor; a merged query filters by actor."""
    gw_hr = _gw(settings_factory, tmp_path, "hr")
    gw_tp = _gw(settings_factory, tmp_path, "truong-phong")
    gw_hr.execute(POST, handler=lambda a: "POSTED")
    gw_tp.execute(POST, handler=lambda a: "POSTED")

    hr_rows = _rows(tmp_path, "hr")
    tp_rows = _rows(tmp_path, "truong-phong")
    assert hr_rows and all(r["actor"] == "hr" for r in hr_rows)
    assert tp_rows and all(r["actor"] == "truong-phong" for r in tp_rows)

    # A cross-agent view (one log over merged rows) filters by the RECORDED actor, not the path.
    merged = tmp_path / "merged.jsonl"
    merged.write_text(
        (tmp_path / "hr" / "audit.jsonl").read_text()
        + (tmp_path / "truong-phong" / "audit.jsonl").read_text()
    )
    log = AuditLog(merged)
    assert all(r["actor"] == "hr" for r in log.query(actor="hr"))
    assert all(r["actor"] == "truong-phong" for r in log.query(actor="truong-phong"))
    assert len(log.query()) == len(hr_rows) + len(tp_rows)  # no-filter = all


def test_every_outcome_branch_attributed(settings_factory, tmp_path):
    """allow, dry-run, dedup, and a Lớp A deny all record the actor (single choke point)."""
    # allow + dedup on one gateway
    gw = _gw(settings_factory, tmp_path, "hr")
    gw.execute(POST, handler=lambda a: "POSTED")           # allow
    gw.execute(POST, handler=lambda a: "POSTED")           # dedup (same action)
    # deny on a hard-blocked action
    with pytest.raises(HardBlockedError):
        gw.execute({"type": "gh_cli", "argv": ["repo", "delete", "x"]}, handler=lambda a: None)
    # dry-run on a separate dry gateway (same agent)
    gw_dry = _gw(settings_factory, tmp_path, "hr", dry_run=True)
    gw_dry.execute(
        {"type": "mcp_tool", "server": "slack", "tool": "post_message",
         "args": {"channel": "C2", "text": "x"}},
        handler=lambda a: "P",
    )

    rows = _rows(tmp_path, "hr")
    verdicts = {r["verdict"] for r in rows}
    assert {"allow", "deny"} <= verdicts  # both outcome kinds present
    assert all(r["actor"] == "hr" for r in rows)  # EVERY branch attributed


def test_approval_carries_actor(settings_factory, tmp_path):
    """A queued (pending) approval records the acting agent; the store round-trips it."""
    store = ApprovalStore(tmp_path / "approvals.db")
    aid = store.enqueue({"type": "mcp_tool", "server": "slack"}, reason="external", actor="hr")
    assert store.get(aid).actor == "hr"
