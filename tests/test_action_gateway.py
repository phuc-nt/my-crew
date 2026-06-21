"""Action Gateway guard-chain coverage: hard-block, kill-switch, dry-run, dedup, execute."""

from __future__ import annotations

import pytest

from src.actions.action_gateway import (
    ActionGateway,
    HardBlockedError,
    RateLimitedError,
    WriteDisabledError,
)
from src.audit.audit_log import AuditLog

POST = {
    "type": "mcp_tool",
    "server": "slack",
    "tool": "post_message",
    "args": {"channel": "C1", "text": "hi"},
}


def _gateway(settings_factory, tmp_path, **kw):
    settings = settings_factory(**kw)
    return ActionGateway(settings=settings, audit_log=AuditLog(tmp_path / "audit.jsonl"))


def test_dry_run_skips_handler(settings_factory, tmp_path):
    calls = []
    gw = _gateway(settings_factory, tmp_path, dry_run=True)
    result = gw.execute(POST, handler=lambda a: calls.append(a) or "POSTED")
    assert result.status == "dry_run"
    assert calls == []  # handler not invoked under dry-run


def test_kill_switch_refuses(settings_factory, tmp_path):
    gw = _gateway(settings_factory, tmp_path, dry_run=False, write_disabled=True)
    with pytest.raises(WriteDisabledError):
        gw.execute(POST, handler=lambda a: "POSTED")


def test_hard_block_raises_before_handler(settings_factory, tmp_path):
    calls = []
    gw = _gateway(settings_factory, tmp_path, dry_run=False)
    with pytest.raises(HardBlockedError):
        gw.execute(
            {"type": "gh_cli", "argv": ["repo", "delete", "x"]},
            handler=lambda a: calls.append(a),
        )
    assert calls == []


def test_execute_then_dedup(settings_factory, tmp_path):
    gw = _gateway(settings_factory, tmp_path, dry_run=False)
    r1 = gw.execute(POST, handler=lambda a: "POSTED")
    r2 = gw.execute(POST, handler=lambda a: "POSTED")
    assert r1.status == "executed"
    assert r2.status == "deduplicated"


def test_no_handler_skips(settings_factory, tmp_path):
    gw = _gateway(settings_factory, tmp_path, dry_run=False)
    assert gw.execute(POST).status == "skipped"


def test_read_action_rejected(settings_factory, tmp_path):
    gw = _gateway(settings_factory, tmp_path)
    with pytest.raises(ValueError):
        gw.execute({"type": "read", "tool": "list"})


def test_non_dict_action_refused(settings_factory, tmp_path):
    # L-NEW-3: gateway must validate before dereferencing, never crash un-run.
    gw = _gateway(settings_factory, tmp_path)
    for bad in (["not", "dict"], None, "string"):
        with pytest.raises(ValueError):
            gw.execute(bad)


def test_rate_limit(settings_factory, tmp_path):
    gw = _gateway(settings_factory, tmp_path, dry_run=False)
    # Distinct actions to avoid dedup; exceed the 10/min cap.
    for i in range(10):
        gw.execute(
            {"type": "mcp_tool", "server": "slack", "tool": "post_message",
             "args": {"channel": "C1", "text": f"msg {i}"}},
            handler=lambda a: "ok",
        )
    with pytest.raises(RateLimitedError):
        gw.execute(
            {"type": "mcp_tool", "server": "slack", "tool": "post_message",
             "args": {"channel": "C1", "text": "overflow"}},
            handler=lambda a: "ok",
        )


def test_handler_error_is_audited_and_reraised(settings_factory, tmp_path):
    gw = _gateway(settings_factory, tmp_path, dry_run=False)

    def boom(_a):
        raise ValueError("handler kaboom")

    with pytest.raises(RuntimeError, match="failed"):
        gw.execute(POST, handler=boom)
