"""Read-tool calls leave an audit row that says who, which step, and which round.

The policy shim was already the single chokepoint every read passes through, but it kept
no record — so a Lớp B audit could see the writes an agent made and not the reads that
informed them, and could not answer "which agent, on which step, on which round".

These tests pin the row and its context. They do NOT pin any allow/deny decision: that is
`hard_block.classify`'s, unchanged here, and pinned by test_hard_block.py and
test_tool_calling_runtime.py.
"""

from __future__ import annotations

import json

import pytest

from my_crew.runtime_backends.read_only_toolset import _shim
from my_crew.runtime_backends.tool_call_context import (
    NO_CONTEXT,
    current_tool_call_context,
    tool_call_context,
    tool_call_iteration,
)


@pytest.fixture
def audit_rows(tmp_path, monkeypatch):
    """Point the shared audit trail at a tmp dir; return a reader for its rows."""
    monkeypatch.setattr(
        "my_crew.runtime.team_task_paths.team_tasks_root", lambda: tmp_path
    )
    path = tmp_path / "audit" / "audit.jsonl"

    def read() -> list[dict]:
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    return read


def _ok_tool(name: str = "jira.issues"):
    """A shimmed read callable that succeeds and records what args it saw."""
    seen: list[dict] = []

    def _fn(args: dict):
        seen.append(args)
        return "result text"

    return _shim(name, _fn), seen


# --- the context carrier -------------------------------------------------------------


def test_no_context_outside_a_step():
    assert current_tool_call_context() == NO_CONTEXT


def test_context_is_restored_after_the_block():
    with tool_call_context(agent_id="a1", task_id="t1", step_id="s1"):
        assert current_tool_call_context().agent_id == "a1"
    assert current_tool_call_context() == NO_CONTEXT


def test_iteration_layers_onto_identity_without_erasing_it():
    """The runner knows who; the loop knows which round. Each sets the half it holds, so
    setting the round must not blank out the identity already in force."""
    with tool_call_context(agent_id="a1", task_id="t1", step_id="s1"):
        with tool_call_iteration(3):
            ctx = current_tool_call_context()
            assert (ctx.agent_id, ctx.task_id, ctx.step_id, ctx.iteration) == (
                "a1", "t1", "s1", 3
            )
        assert current_tool_call_context().iteration == -1


def test_unknown_iteration_is_distinct_from_round_zero():
    """-1 means "not in a counted loop"; 0 is a real first round. Collapsing them would
    make every uncounted call look like it happened on round one."""
    assert NO_CONTEXT.iteration == -1
    with tool_call_iteration(0):
        assert current_tool_call_context().iteration == 0


# --- the audit row -------------------------------------------------------------------


def test_a_successful_read_leaves_one_allow_row(audit_rows):
    tool, _seen = _ok_tool()
    tool({"project": "ABC"})

    rows = audit_rows()
    assert len(rows) == 1
    assert rows[0]["action_type"] == "mcp_tool_read"
    assert rows[0]["tool"] == "jira.issues"
    assert rows[0]["verdict"] == "allow"


def test_the_row_carries_the_full_call_context(audit_rows):
    tool, _seen = _ok_tool()
    with tool_call_context(agent_id="analyst", task_id="task-9", step_id="step-2"):
        with tool_call_iteration(4):
            tool({})

    row = audit_rows()[0]
    assert row["actor"] == "analyst"
    assert row["params"]["task_id"] == "task-9"
    assert row["params"]["step_id"] == "step-2"
    assert row["params"]["iteration"] == 4


def test_a_call_outside_a_step_is_still_recorded_just_unattributed(audit_rows):
    """A CLI report run has no step. It must still leave a trail rather than a gap."""
    tool, _seen = _ok_tool()
    tool({})

    row = audit_rows()[0]
    assert row["actor"] == ""
    assert row["params"]["task_id"] == ""
    assert row["params"]["iteration"] == -1


def test_tool_args_never_reach_the_trail(audit_rows):
    """Args are attacker-influenced free text on a path that now writes a row per call
    into a store with no rotation. The tool name and verdict are what an audit needs."""
    tool, _seen = _ok_tool()
    tool({"query": "SECRET-CANARY-VALUE", "note": "another-canary"})

    blob = json.dumps(audit_rows())
    assert "SECRET-CANARY-VALUE" not in blob
    assert "another-canary" not in blob


def test_a_policy_block_is_recorded_as_a_deny(audit_rows, monkeypatch):
    """The deny is the row an audit most needs; it must not be the one path that is
    silent."""
    from my_crew.actions import hard_block

    monkeypatch.setattr(
        hard_block, "classify",
        lambda action, **kw: hard_block.BlockVerdict(
            blocked=True, category=hard_block.BlockCategory.SECURITY, reason="nope"
        ),
    )
    ran = []
    guarded = _shim("jira.issues", lambda args: ran.append(1))

    # _shim's own error guard converts the refusal to a string for the model.
    assert "bị từ chối" in str(guarded({}))
    assert ran == []  # blocked before the tool body

    rows = audit_rows()
    assert len(rows) == 1
    assert rows[0]["verdict"] == "deny"
    assert "nope" in rows[0]["reason"]


def test_a_tool_that_raises_is_still_recorded_as_allowed(audit_rows):
    """Classify allowed the call, so "allow" is the honest policy verdict. Whether the
    tool body then worked is the error guard's business, not the policy trail's — and a
    failed read must not be able to erase its own row."""
    def _boom(args: dict):
        raise RuntimeError("upstream 500")

    guarded = _shim("confluence.page", _boom)
    assert "lỗi" in str(guarded({}))

    rows = audit_rows()
    assert len(rows) == 1
    assert rows[0]["verdict"] == "allow"


def test_each_call_leaves_its_own_row(audit_rows):
    tool, _seen = _ok_tool()
    for _ in range(3):
        tool({})

    assert len(audit_rows()) == 3


def test_an_audit_failure_never_breaks_the_read(audit_rows, monkeypatch):
    """Audit is observation. If the trail cannot be written, the agent still works."""
    from my_crew.audit import audit_log

    def _explode(self, entry):
        raise OSError("disk full")

    monkeypatch.setattr(audit_log.AuditLog, "record", _explode)
    tool, seen = _ok_tool()

    assert tool({"project": "ABC"}) == "result text"
    assert seen == [{"project": "ABC"}]


def test_the_verdict_reaches_the_row_unmodified_by_the_shim(audit_rows, monkeypatch):
    """A not_allowlisted verdict is EXPECTED for reads (they are not in the write
    allowlist) and must not read as a denial — the shim lets it through, so the row says
    allow."""
    from my_crew.actions import hard_block

    monkeypatch.setattr(
        hard_block, "classify",
        lambda action, **kw: hard_block.BlockVerdict(
            blocked=True, category=hard_block.BlockCategory.NOT_ALLOWLISTED, reason="n/a"
        ),
    )
    tool, seen = _ok_tool()
    assert tool({}) == "result text"  # not refused
    assert audit_rows()[0]["verdict"] == "allow"


def test_the_row_records_how_long_the_call_took(audit_rows):
    tool, _seen = _ok_tool()
    tool({})

    assert audit_rows()[0]["params"]["elapsed_ms"] >= 0
