"""Slice 1: per-agent isolation matrix — two agents at two data dirs never mix.

Drives two `Settings` at two tmp data dirs (no subprocess, no daemon) to prove that
audit / dedup / budget / approval are isolated and thread_ids never collide. This is
the headline acceptance of P3: isolation falls out of `settings.data_dir`.
"""

from __future__ import annotations

import pytest

from src.actions.action_gateway import ActionGateway
from src.config.config_builders import build_settings_from_dict
from src.llm.budget_tracker import BudgetExceededError, BudgetTracker
from src.runtime.agent_paths import agent_data_dir, agent_thread_id


def _settings(data_dir, *, monthly_budget_usd=50.0):
    return build_settings_from_dict(
        {
            "openrouter_api_key": None,
            "dry_run": False,  # so a Lớp B post reaches the interrupt, not the dry-run branch
            "monthly_budget_usd": monthly_budget_usd,
            "data_dir": data_dir,
        }
    )


def _two_agents(tmp_path, **kw):
    a = _settings(tmp_path / "a", **kw)
    b = _settings(tmp_path / "b", **kw)
    return a, b


_SLACK_ACTION = {
    "type": "mcp_tool", "server": "slack", "tool": "post_message",
    "args": {"channel": "C_STAKE", "text": "hi"},
    "dedup_hint": "report:daily:2026-06-24",
}


# --- acceptance 1: separate data dirs (stores under each own dir) ---


def test_stores_live_under_each_agents_dir(tmp_path):
    sa, sb = _two_agents(tmp_path)
    ga, gb = ActionGateway(sa), ActionGateway(sb)
    assert str(ga._audit.path).startswith(str(tmp_path / "a"))
    assert str(gb._audit.path).startswith(str(tmp_path / "b"))
    # the two store roots are disjoint
    assert tmp_path / "a" != tmp_path / "b"
    assert BudgetTracker(sa)._budget_dir.parent == tmp_path / "a"
    assert BudgetTracker(sb)._budget_dir.parent == tmp_path / "b"


# --- acceptance 2: audit does not mix ---


def test_audit_does_not_mix(tmp_path):
    sa, _sb = _two_agents(tmp_path)
    ga = ActionGateway(sa)
    ga.execute({"type": "mcp_tool", "server": "slack", "tool": "post_message",
                "args": {"channel": "C_A", "text": "from-A"}, "dedup_hint": "a"},
               handler=lambda _a: "ok")
    a_audit = (tmp_path / "a" / "audit" / "audit.jsonl").read_text(encoding="utf-8")
    assert "C_A" in a_audit
    b_audit_path = tmp_path / "b" / "audit" / "audit.jsonl"
    assert not b_audit_path.exists() or "C_A" not in b_audit_path.read_text(encoding="utf-8")


# --- acceptance 3: dedup does not mix ---


def test_dedup_does_not_mix(tmp_path):
    sa, sb = _two_agents(tmp_path)
    ga, gb = ActionGateway(sa), ActionGateway(sb)
    r1 = ga.execute(dict(_SLACK_ACTION), handler=lambda _a: "ok")
    r2 = ga.execute(dict(_SLACK_ACTION), handler=lambda _a: "ok")
    assert r1.status == "executed" and r2.status == "deduplicated"  # A dedups itself
    # B has its own dedup.db → the SAME action is NOT a duplicate for B.
    rb = gb.execute(dict(_SLACK_ACTION), handler=lambda _a: "ok")
    assert rb.status == "executed"


# --- acceptance 4: budget A at 100% does not block B ---


def test_budget_a_exhausted_does_not_block_b(tmp_path):
    sa, sb = _two_agents(tmp_path, monthly_budget_usd=0.01)
    ta, tb = BudgetTracker(sa), BudgetTracker(sb)
    ta.record_cost(0.02)  # push A over its own cap
    with pytest.raises(BudgetExceededError):
        ta.check_allowed()
    # B's budget lives under tmp_path/b → unaffected, still admits a call.
    allowed, _ratio = tb.check_allowed()
    assert allowed is True


# --- acceptance 5: a Lớp B approval queued for A is not in B's queue ---


def test_approval_queue_does_not_mix(tmp_path):
    sa, sb = _two_agents(tmp_path)
    ga = ActionGateway(sa, external_channels=frozenset({"C_STAKE"}))
    gb = ActionGateway(sb, external_channels=frozenset({"C_STAKE"}))
    res = ga.execute(dict(_SLACK_ACTION), handler=lambda _a: "posted")
    assert res.status == "pending_approval"  # external channel → Lớp B
    assert len(ga.pending_approvals()) == 1
    assert len(gb.pending_approvals()) == 0  # B's approvals.db is independent


# --- acceptance 6: thread_id never collides ---


def test_thread_id_no_collision():
    a = agent_thread_id("acme-web", "daily", "internal")
    b = agent_thread_id("beta-app", "daily", "internal")
    assert a != b
    assert "acme-web" in a and "beta-app" in b
    assert a == "acme-web:daily:internal"


def test_agent_data_dir_is_per_id():
    assert agent_data_dir("acme-web") != agent_data_dir("beta-app")
    assert agent_data_dir("acme-web").name == "acme-web"
    assert agent_data_dir("acme-web").parent.name == "agents"


# --- path-traversal guard: a malformed id cannot escape the .data/agents jail ---


@pytest.mark.parametrize(
    "bad_id",
    ["/etc/passwd", "../../tmp/evil", "a/b", "..", "", "Acme", "a b", "agent.1"],
)
def test_agent_id_rejects_unsafe(bad_id):
    with pytest.raises(ValueError, match="Invalid agent id"):
        agent_data_dir(bad_id)
    with pytest.raises(ValueError, match="Invalid agent id"):
        agent_thread_id(bad_id, "daily", "internal")


def test_agent_id_accepts_safe():
    for good in ("default", "acme-web", "beta_app", "a1", "x"):
        assert agent_data_dir(good).name == good
