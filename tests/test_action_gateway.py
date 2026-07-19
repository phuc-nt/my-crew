"""Action Gateway guard-chain coverage: hard-block, kill-switch, dry-run, dedup, execute."""

from __future__ import annotations

import pytest

from my_crew.actions.action_gateway import (
    ActionGateway,
    HardBlockedError,
    RateLimitedError,
    WriteDisabledError,
)
from my_crew.audit.audit_log import AuditLog

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


def test_dedup_persists_across_restart(settings_factory, tmp_path):
    # A fresh gateway (simulating a process restart) sharing the same data dir
    # must still see a previously-executed action as a duplicate.
    gw1 = _gateway(settings_factory, tmp_path, dry_run=False)
    assert gw1.execute(POST, handler=lambda a: "POSTED").status == "executed"

    gw2 = _gateway(settings_factory, tmp_path, dry_run=False)  # "restart"
    assert gw2.execute(POST, handler=lambda a: "POSTED").status == "deduplicated"


def test_dedup_not_claimed_on_handler_failure(settings_factory, tmp_path):
    # A failed handler must NOT claim the dedup key, so a retry can run.
    gw = _gateway(settings_factory, tmp_path, dry_run=False)
    with pytest.raises(RuntimeError):
        gw.execute(POST, handler=lambda a: (_ for _ in ()).throw(ValueError("boom")))
    # retry with a working handler succeeds (key was not claimed).
    assert gw.execute(POST, handler=lambda a: "POSTED").status == "executed"


def _audit_rows(tmp_path):
    import json as _json

    p = tmp_path / "audit.jsonl"
    if not p.exists():
        return []
    return [_json.loads(ln) for ln in p.read_text().strip().splitlines() if ln.strip()]


def test_actor_recorded_on_allow(settings_factory, tmp_path):
    """v46: the acting agent's actor is stamped on an allowed action's audit row."""
    gw = ActionGateway(settings=settings_factory(dry_run=False),
                       audit_log=AuditLog(tmp_path / "audit.jsonl"), actor="hr")
    gw.execute(POST, handler=lambda a: "POSTED")
    rows = _audit_rows(tmp_path)
    assert rows and all(r.get("actor") == "hr" for r in rows)


def test_actor_recorded_on_deny(settings_factory, tmp_path):
    """v46: actor is stamped even on a Lớp A hard-deny (every outcome branch, one choke point)."""
    gw = ActionGateway(settings=settings_factory(dry_run=False),
                       audit_log=AuditLog(tmp_path / "audit.jsonl"), actor="tp")
    with pytest.raises(HardBlockedError):
        gw.execute({"type": "gh_cli", "argv": ["repo", "delete", "x"]}, handler=lambda a: None)
    rows = _audit_rows(tmp_path)
    assert rows and rows[-1].get("actor") == "tp" and rows[-1]["verdict"] == "deny"


def test_actor_defaults_empty_when_not_passed(settings_factory, tmp_path):
    """Back-compat: a gateway built without actor records "" (byte-identical to pre-v46)."""
    gw = _gateway(settings_factory, tmp_path, dry_run=False)  # no actor
    gw.execute(POST, handler=lambda a: "POSTED")
    rows = _audit_rows(tmp_path)
    assert rows and all(r.get("actor", "") == "" for r in rows)


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


# --- v54: external_action office-event bridge ---


def _office_events(tmp_path, room="office"):
    from my_crew.runtime.office_room_append import office_room_db_path
    from my_crew.runtime.office_room_store import OfficeRoomStore

    path = office_room_db_path(tmp_path)
    if not path.exists():
        return []
    store = OfficeRoomStore(path)
    try:
        return store.list(room)
    finally:
        store.close()


def _bridge_gateway(settings_factory, tmp_path, monkeypatch, **kw):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    settings = settings_factory(**kw)
    return ActionGateway(
        settings=settings, audit_log=AuditLog(tmp_path / "audit.jsonl"), actor="hr",
    )


def test_bridge_emits_one_event_on_allow(settings_factory, tmp_path, monkeypatch):
    gw = _bridge_gateway(settings_factory, tmp_path, monkeypatch, dry_run=False)
    result = gw.execute(POST, handler=lambda a: "POSTED")
    assert result.status == "executed"
    events = _office_events(tmp_path)
    assert len(events) == 1
    assert events[0].kind == "external_action"
    assert events[0].body["outcome"] == "allow"
    assert events[0].body["actor"] == "hr"
    assert events[0].body["tool"] == "slack:post_message"
    assert events[0].body["detail"] == "C1"  # no-content-echo: target id, never text body


def test_bridge_emits_one_event_on_deny(settings_factory, tmp_path, monkeypatch):
    gw = _bridge_gateway(settings_factory, tmp_path, monkeypatch, dry_run=False)
    with pytest.raises(HardBlockedError):
        gw.execute({"type": "gh_cli", "argv": ["repo", "delete", "x"]}, handler=lambda a: None)
    events = _office_events(tmp_path)
    assert len(events) == 1
    assert events[0].body["outcome"] == "deny"


def test_bridge_emits_one_event_on_skipped(settings_factory, tmp_path, monkeypatch):
    gw = _bridge_gateway(settings_factory, tmp_path, monkeypatch, dry_run=False)
    result = gw.execute(POST)  # no handler ⇒ skipped
    assert result.status == "skipped"
    events = _office_events(tmp_path)
    assert len(events) == 1
    assert events[0].body["outcome"] == "skipped"


def test_bridge_append_failure_does_not_change_action_or_audit(
    settings_factory, tmp_path, monkeypatch,
):
    """A broken office-room append must never affect the gateway result or the audit rows."""
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)

    def _boom(*_a, **_kw):
        raise RuntimeError("office store exploded")

    monkeypatch.setattr(
        "my_crew.runtime.office_room_append.append_office_event", _boom
    )
    settings = settings_factory(dry_run=False)
    gw = ActionGateway(
        settings=settings, audit_log=AuditLog(tmp_path / "audit.jsonl"), actor="hr",
    )
    result = gw.execute(POST, handler=lambda a: "POSTED")
    assert result.status == "executed"  # action path unaffected
    rows = _audit_rows(tmp_path)
    assert len(rows) == 1 and rows[0]["verdict"] == "allow"  # audit byte-identical


def test_bridge_never_echoes_message_content(settings_factory, tmp_path, monkeypatch):
    gw = _bridge_gateway(settings_factory, tmp_path, monkeypatch, dry_run=False)
    secret_text = "super secret payload body should never leak"
    action = {
        "type": "mcp_tool", "server": "slack", "tool": "post_message",
        "args": {"channel": "C1", "text": secret_text},
    }
    gw.execute(action, handler=lambda a: "POSTED")
    events = _office_events(tmp_path)
    body_dump = str(events[0].body)
    assert secret_text not in body_dump
