"""v76 audit hash-chain: canonical encoding, tamper/chain detection, writer wiring."""

from __future__ import annotations

import json

from my_crew.audit.audit_chain import canonical_hash, chain_fields, verify_chain
from my_crew.audit.audit_log import AuditEntry, AuditLog


def _record(log, tool="jira:comment", verdict="allow"):
    log.record(AuditEntry(action_type="mcp_tool", tool=tool, verdict=verdict))


def test_delimiter_join_collides_but_length_prefix_does_not():
    """The reason canonical_hash length-prefixes: a '|' join collides on shifted
    boundaries; the length-prefixed encoding cannot."""
    a = {"x": "a|b", "y": "c"}
    b = {"x": "a", "y": "b|c"}
    joined_a = "|".join([a["x"], a["y"]])
    joined_b = "|".join([b["x"], b["y"]])
    assert joined_a == joined_b  # the collision a join-based hash inherits
    assert canonical_hash(a) != canonical_hash(b)


def test_verify_ok_on_real_writer_output(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    for i in range(5):
        _record(log, tool=f"tool:{i}")
    v = verify_chain(log.path)
    assert v["ok"] is True and v["hashed"] == 5 and v["restarts"] == 0


def test_verify_catches_field_edit(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    for i in range(3):
        _record(log, tool=f"tool:{i}")
    lines = log.path.read_text().splitlines()
    doctored = json.loads(lines[1])
    doctored["verdict"] = "deny"  # rewrite history: flip a verdict
    lines[1] = json.dumps(doctored, ensure_ascii=False)
    log.path.write_text("\n".join(lines) + "\n")
    v = verify_chain(log.path)
    assert v["ok"] is False and v["broken_line"] == 2 and v["reason"] == "tamper"


def test_verify_catches_deleted_middle_line(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    for i in range(3):
        _record(log, tool=f"tool:{i}")
    lines = log.path.read_text().splitlines()
    del lines[1]
    log.path.write_text("\n".join(lines) + "\n")
    v = verify_chain(log.path)
    assert v["ok"] is False and v["reason"] == "chain"


def test_verify_catches_inserted_forged_line(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    for i in range(2):
        _record(log, tool=f"tool:{i}")
    forged = chain_fields({"action_type": "mcp_tool", "tool": "forged:action",
                           "verdict": "allow"}, prev_hash="not-the-real-prev")
    lines = log.path.read_text().splitlines()
    lines.insert(1, json.dumps(forged, ensure_ascii=False))
    log.path.write_text("\n".join(lines) + "\n")
    assert verify_chain(log.path)["ok"] is False


def test_legacy_prefix_is_valid_but_legacy_after_hashed_is_a_break(tmp_path):
    path = tmp_path / "audit.jsonl"
    path.write_text(json.dumps({"action_type": "mcp_tool", "tool": "old:row",
                                "verdict": "allow"}) + "\n")
    log = AuditLog(path)
    _record(log)
    v = verify_chain(path)
    assert v["ok"] is True and v["legacy_prefix"] == 1 and v["hashed"] == 1
    # stripping hash fields from a NEW row must read as a break, not as "legacy"
    with path.open("a") as fh:
        fh.write(json.dumps({"action_type": "mcp_tool", "tool": "strip:row",
                             "verdict": "allow"}) + "\n")
    v = verify_chain(path)
    assert v["ok"] is False and v["reason"] == "chain"


def test_concurrent_writers_keep_one_unbroken_chain(tmp_path):
    import threading

    log_path = tmp_path / "audit.jsonl"

    def _worker(n):
        log = AuditLog(log_path)
        for i in range(10):
            _record(log, tool=f"w{n}:{i}")

    threads = [threading.Thread(target=_worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    v = verify_chain(log_path)
    assert v["ok"] is True and v["hashed"] == 40 and v["restarts"] == 0
