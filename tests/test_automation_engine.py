"""M3-P12 S3 (D3): workflow engine — propose ENQUEUES Lớp B, never executes.

Core invariant: a `propose` step builds the action dict and routes it through a REAL
ActionGateway, which enqueues it (pending_approval) — no write handler ever runs. Dry-run
builds the same dict but never touches the gateway (ApprovalStore stays empty).
"""

from __future__ import annotations

from src.actions.action_gateway import ActionGateway
from src.audit.audit_log import AuditLog
from src.automation.engine import run_workflow
from src.automation.schema import parse_automation
from src.config.config_builders import build_settings_from_dict


def _gateway(tmp_path, **kw):
    settings = build_settings_from_dict(
        {"dry_run": False, "trust_mode": "guarded", "data_dir": str(tmp_path), **kw}
    )
    # 'stakeholders' is external ⇒ a slack post there is Lớp B (queues for approval).
    return ActionGateway(
        settings,
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
        external_channels=frozenset({"stakeholders"}),
    )


_WF = {
    "name": "blocker-note",
    "steps": [
        {"read": "jira.issues", "args": {}, "as": "issues"},
        {"analyze": "summarize_blockers", "using": ["issues"], "as": "note"},
        {"propose": "slack.post", "args": {"channel": "stakeholders", "text": "{{note}}"}},
    ],
}


def _collab():
    reads = {"jira.issues": lambda args: [{"key": "SCRUM-1"}]}
    analyze = lambda prompt, vars: "Blocker: SCRUM-1 cần review"  # noqa: E731
    return reads, analyze


def test_propose_enqueues_lop_b_never_executes(tmp_path):
    gw = _gateway(tmp_path)
    reads, analyze = _collab()
    results = run_workflow(
        parse_automation(_WF), read_tools=reads, analyze_fn=analyze, gateway=gw
    )
    propose = results[-1]
    assert propose.status == "pending_approval"
    assert propose.approval_id is not None
    pending = gw.pending_approvals()
    assert len(pending) == 1  # the proposal is queued, NOT executed
    assert pending[0].action["server"] == "slack"
    assert pending[0].action["args"]["text"] == "Blocker: SCRUM-1 cần review"  # templated


def test_dry_run_never_enqueues(tmp_path):
    gw = _gateway(tmp_path)
    reads, analyze = _collab()
    results = run_workflow(
        parse_automation(_WF), read_tools=reads, analyze_fn=analyze, gateway=gw, dry_run=True
    )
    assert results[-1].proposed is not None  # the action dict was built + surfaced
    assert results[-1].status is None  # gateway never called
    assert gw.pending_approvals() == []  # nothing enqueued


def test_analyze_uses_named_registry_prompt(tmp_path):
    gw = _gateway(tmp_path)
    seen = {}

    def analyze(prompt_text, variables):
        seen["prompt"] = prompt_text
        return "x"

    reads = {"jira.issues": lambda args: []}
    run_workflow(parse_automation(_WF), read_tools=reads, analyze_fn=analyze, gateway=gw)
    # the engine fed the REGISTRY's prompt text (not yaml text) to analyze_fn
    assert "blocker" in seen["prompt"].lower()


def test_when_false_skips_all_steps(tmp_path):
    gw = _gateway(tmp_path)
    reads, analyze = _collab()
    wf = dict(_WF, when="priority == P0")  # context has no 'priority' ⇒ false
    results = run_workflow(parse_automation(wf), read_tools=reads, analyze_fn=analyze, gateway=gw)
    assert results == results[:1] and results[0].kind == "skipped"
    assert gw.pending_approvals() == []


def test_when_true_runs(tmp_path):
    gw = _gateway(tmp_path)
    reads, analyze = _collab()
    wf = dict(_WF, when="priority == P0")
    results = run_workflow(
        parse_automation(wf), read_tools=reads, analyze_fn=analyze, gateway=gw,
        context={"priority": "P0"},
    )
    assert results[-1].status == "pending_approval"


def test_linear_comment_propose_enqueues(tmp_path):
    gw = _gateway(tmp_path)
    wf = {
        "name": "lc",
        "steps": [
            {"propose": "linear.comment", "args": {"issue_id": "ISS-1", "body": "ping"}},
        ],
    }
    results = run_workflow(
        parse_automation(wf), read_tools={}, analyze_fn=lambda p, v: "", gateway=gw
    )
    # linear createComment is always Lớp B ⇒ queued
    assert results[-1].status == "pending_approval"
    assert gw.pending_approvals()[0].action["tool"] == "linear_createComment"
