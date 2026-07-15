"""Audit log: append-only, valid JSON lines, secret redaction."""

from __future__ import annotations

import json

from src.audit.audit_log import AuditEntry, AuditLog, redact


def test_append_only_one_line_per_record(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    for i in range(3):
        log.record(AuditEntry(action_type="mcp_tool", tool=f"t{i}", verdict="allow"))
    lines = (tmp_path / "audit.jsonl").read_text().strip().splitlines()
    assert len(lines) == 3
    for line in lines:
        json.loads(line)  # each line is valid JSON


def test_actor_defaults_empty_and_round_trips(tmp_path):
    """v46 P1: actor defaults "" and serializes on the row."""
    log = AuditLog(tmp_path / "audit.jsonl")
    assert AuditEntry(action_type="x", tool="t", verdict="allow").actor == ""
    log.record(AuditEntry(action_type="mcp_tool", tool="jira:create", verdict="allow", actor="hr"))
    row = json.loads((tmp_path / "audit.jsonl").read_text().strip().splitlines()[0])
    assert row["actor"] == "hr"


def test_query_filters_by_actor(tmp_path):
    """v46 P3: query(actor=...) selects only that agent's rows; no filter unchanged."""
    log = AuditLog(tmp_path / "audit.jsonl")
    log.record(AuditEntry(action_type="a", tool="t1", verdict="allow", actor="hr"))
    log.record(AuditEntry(action_type="a", tool="t2", verdict="allow", actor="tp"))
    log.record(AuditEntry(action_type="a", tool="t3", verdict="allow"))  # pre-v46-style, no actor
    hr = log.query(actor="hr")
    assert len(hr) == 1 and hr[0]["tool"] == "t1"
    assert log.query(actor="tp")[0]["tool"] == "t2"
    assert log.query(actor="nobody") == []  # actor filter excludes no-actor rows too
    assert len(log.query()) == 3  # no filter unchanged


def test_params_secret_redacted_on_write(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.record(
        AuditEntry(
            action_type="mcp_tool",
            tool="slack:post",
            verdict="allow",
            params={"channel": "C1", "token": "xoxb-supersecret", "text": "hi"},
        )
    )
    entry = json.loads((tmp_path / "audit.jsonl").read_text().strip())
    assert entry["params"]["token"] == "***REDACTED***"
    assert entry["params"]["channel"] == "C1"
    assert "xoxb-supersecret" not in (tmp_path / "audit.jsonl").read_text()


def test_redact_nested_and_lists():
    out = redact(
        {
            "api_key": "sk-or-abcdefghij12345678",
            "nested": {"password": "p", "ok": "keep"},
            "items": [{"secret": "s"}, {"plain": "v"}],
        }
    )
    assert out["api_key"] == "***REDACTED***"
    assert out["nested"]["password"] == "***REDACTED***"
    assert out["nested"]["ok"] == "keep"
    assert out["items"][0]["secret"] == "***REDACTED***"
    assert out["items"][1]["plain"] == "v"


def test_secret_in_freetext_field_redacted(tmp_path):
    # Regression for C1: a secret in a NON-secret-named field (free text) must
    # not be written verbatim — including in the reason/result_summary fields.
    log = AuditLog(tmp_path / "audit.jsonl")
    log.record(
        AuditEntry(
            action_type="mcp_tool",
            tool="slack:post",
            verdict="deny",
            reason="value contains xoxb-FAKE1234",
            params={"channel": "C1", "text": "leak xoxb-FAKE1234"},
            result_summary="posted key AKIAFFFFFFFFFFFFFFFF",
        )
    )
    raw = (tmp_path / "audit.jsonl").read_text()
    assert "xoxb-FAKE1234" not in raw
    assert "AKIAFFFFFFFFFFFFFFFF" not in raw
    assert "***REDACTED***" in raw
