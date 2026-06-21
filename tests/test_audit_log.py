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
