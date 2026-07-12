"""M3-P12 S3 (D3): the RED-LINE suite — a workflow can only PROPOSE, never bypass the gateway.

Proves: a destructive/secret proposal hits Lớp A hard-deny; the engine never executes a
write (no handler path); the engine imports ONLY the gateway (grep-guard) and never calls
execute_approved/approve.
"""

from __future__ import annotations

import pathlib

import pytest

from src.actions.action_gateway import ActionGateway, HardBlockedError
from src.audit.audit_log import AuditLog
from src.automation.engine import run_workflow
from src.automation.schema import ProposeStep, Workflow
from src.config.config_builders import build_settings_from_dict

_AUTOMATION_DIR = pathlib.Path("src/automation")


def _gateway(tmp_path):
    settings = build_settings_from_dict(
        {"dry_run": False, "trust_mode": "guarded", "data_dir": str(tmp_path)}
    )
    return ActionGateway(
        settings,
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
        external_channels=frozenset({"stakeholders"}),
    )


def _wf_with_propose_args(target, args):
    """A single-propose workflow whose action dict we control directly."""
    return Workflow(name="redline", when=None, steps=(ProposeStep(target=target, args=args),))


def test_secret_in_proposal_credential_denied(tmp_path):
    """A token-shaped string in a proposed action ⇒ Lớp A CREDENTIAL deny (gateway refuses)."""
    gw = _gateway(tmp_path)
    wf = _wf_with_propose_args(
        "linear.comment",
        {"issue_id": "ISS-1", "body": "deploy key ghp_abcdefghij1234567890XYZ"},
    )
    with pytest.raises(HardBlockedError):
        run_workflow(wf, read_tools={}, analyze_fn=lambda p, v: "", gateway=gw)
    assert gw.pending_approvals() == []  # nothing enqueued, nothing executed


def test_engine_never_executes_a_write(tmp_path):
    """The gateway is given NO handler by the engine ⇒ a write can never run from here."""
    gw = _gateway(tmp_path)
    executed = {"n": 0}
    orig = gw.execute

    def _spy(action, *, handler=None, rationale=""):
        # The engine must call execute WITHOUT a handler (so nothing can execute).
        assert handler is None, "engine must not pass a write handler"
        if handler is not None:
            executed["n"] += 1
        return orig(action, handler=handler, rationale=rationale)

    gw.execute = _spy
    wf = _wf_with_propose_args(
        "slack.post", {"channel": "stakeholders", "text": "hi"}
    )
    run_workflow(wf, read_tools={}, analyze_fn=lambda p, v: "", gateway=gw)
    assert executed["n"] == 0


def test_engine_never_calls_approve_paths(tmp_path):
    """The engine must never call execute_approved/approve (those run a write)."""
    gw = _gateway(tmp_path)
    forbidden = {"hit": False}
    gw.execute_approved = lambda *a, **k: forbidden.__setitem__("hit", True)
    gw.approve = lambda *a, **k: forbidden.__setitem__("hit", True)
    wf = _wf_with_propose_args("slack.post", {"channel": "stakeholders", "text": "hi"})
    run_workflow(wf, read_tools={}, analyze_fn=lambda p, v: "", gateway=gw)
    assert forbidden["hit"] is False


# --- grep-guard: the automation package imports ONLY the gateway, no write module ---


_FORBIDDEN_MODULES = (
    "slack_write",
    "linear_write",
    "email_write",
    "confluence_write",
    "approved_dispatch",
    "mcp_adapter",
)


def _import_lines(src: str) -> list[str]:
    """The actual import statements (so a docstring mentioning a name doesn't false-positive)."""
    return [
        ln.strip()
        for ln in src.splitlines()
        if ln.strip().startswith(("import ", "from "))
    ]


@pytest.mark.parametrize("pyfile", sorted(_AUTOMATION_DIR.glob("*.py")))
def test_automation_imports_no_write_module(pyfile):
    imports = "\n".join(_import_lines(pyfile.read_text(encoding="utf-8")))
    for bad in _FORBIDDEN_MODULES:
        assert bad not in imports, f"{pyfile.name} must not import {bad!r}"
    # `call_tool` must never be IMPORTED or CALLED (a real MCP write path).
    assert "call_tool(" not in pyfile.read_text(encoding="utf-8")


def test_automation_engine_never_calls_approve_paths_in_code():
    """The engine never CALLS execute_approved/approve (docstring mentions are fine)."""
    src = (_AUTOMATION_DIR / "engine.py").read_text(encoding="utf-8")
    assert "ActionGateway" in src
    assert ".execute_approved(" not in src
    assert ".approve(" not in src
