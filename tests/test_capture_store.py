"""Per-attempt telemetry store: record/read, review-row distinction, upsert, multi-writer.

Proves the capture layer records one row per attempt with the columns a later grade/ROI pass
needs, distinguishes review rows from work rows, and tolerates two concurrent connections
(the ticker + a spawned worker) like the sibling team-task store.
"""

from __future__ import annotations

from my_crew.runtime.capture_store import CaptureStore


def _store(tmp_path):
    return CaptureStore(tmp_path / "captures.sqlite3")


def test_record_and_read_back(tmp_path):
    cs = _store(tmp_path)
    cs.record(
        attempt_id="a1", task_id="t1", step_id="S1", agent_id="nghien-cuu",
        engine="deep_agent", status="done", step_type="work", review_round=0,
        cost_usd=0.005, cost_source="estimated", input_tokens=100, output_tokens=200,
        started_at="2026-07-12T00:00:00+00:00", ended_at="2026-07-12T00:00:05+00:00",
        duration_ms=5000, error=None,
    )
    row = cs.get("a1")
    assert row["engine"] == "deep_agent"
    assert row["cost_source"] == "estimated"
    assert row["duration_ms"] == 5000
    assert row["input_tokens"] == 100
    assert row["ts"]  # write timestamp always set
    cs.close()


def test_review_row_distinguished_by_type_and_round(tmp_path):
    cs = _store(tmp_path)
    cs.record(attempt_id="w", task_id="t1", step_id="S1", agent_id="a", engine="native",
              status="done", step_type="work", review_round=0)
    cs.record(attempt_id="r", task_id="t1", step_id="S1-review-0-0", agent_id="b",
              engine="native", status="done", step_type="review", review_round=1)
    rows = {r["attempt_id"]: r for r in cs.list_for_task("t1")}
    assert rows["w"]["step_type"] == "work" and rows["w"]["review_round"] == 0
    assert rows["r"]["step_type"] == "review" and rows["r"]["review_round"] == 1
    cs.close()


def test_upsert_is_idempotent_on_attempt_id(tmp_path):
    cs = _store(tmp_path)
    cs.record(attempt_id="a1", task_id="t1", step_id="S1", agent_id="a", engine="native",
              status="done")
    cs.record(attempt_id="a1", task_id="t1", step_id="S1", agent_id="a", engine="native",
              status="failed", error="boom")
    assert cs.get("a1")["status"] == "failed"
    assert len(cs.list_for_task("t1")) == 1  # one row, replaced
    cs.close()


def test_two_writers_share_the_file(tmp_path):
    # WAL + busy_timeout: the ticker and a spawned worker each open a connection concurrently.
    path = tmp_path / "captures.sqlite3"
    a = CaptureStore(path)
    b = CaptureStore(path)
    a.record(attempt_id="a1", task_id="t1", step_id="S1", agent_id="x", engine="native",
             status="done")
    b.record(attempt_id="a2", task_id="t1", step_id="S2", agent_id="y", engine="create_agent",
             status="done")
    assert len(a.list_for_task("t1")) == 2
    a.close()
    b.close()


def test_missing_attempt_returns_none(tmp_path):
    cs = _store(tmp_path)
    assert cs.get("nope") is None
    cs.close()


def test_criteria_json_migration_is_idempotent_on_reopen(tmp_path):
    # Same posture as v46's `approvals.actor` ALTER: opening the store twice against the
    # same file must not raise "duplicate column" — the second `_create_schema()` call
    # hits the guarded ALTER and swallows it.
    path = tmp_path / "captures.sqlite3"
    a = CaptureStore(path)
    a.record(attempt_id="a1", task_id="t1", step_id="S1", agent_id="x", engine="native",
              status="done")
    a.close()
    b = CaptureStore(path)  # re-open — must not raise
    assert b.get("a1")["status"] == "done"
    b.close()


def test_criteria_written_on_review_capture_and_returned_by_get(tmp_path):
    cs = _store(tmp_path)
    criteria = [
        {"criterion": "handles empty input", "passed": True, "note": "ok"},
        {"criterion": "returns typed errors", "passed": False, "note": "missing validation"},
    ]
    cs.record(
        attempt_id="r1", task_id="t1", step_id="S1-review-0-0", agent_id="reviewer",
        engine="native", status="done", step_type="review", review_round=1,
        criteria=criteria,
    )
    row = cs.get("r1")
    assert row["criteria_json"] is not None
    import json
    assert json.loads(row["criteria_json"]) == criteria


def test_criteria_absent_on_work_capture_is_null(tmp_path):
    cs = _store(tmp_path)
    cs.record(attempt_id="w1", task_id="t1", step_id="S1", agent_id="a", engine="native",
              status="done", step_type="work")
    assert cs.get("w1")["criteria_json"] is None


def test_list_reads_exclude_criteria_json(tmp_path):
    cs = _store(tmp_path)
    cs.record(
        attempt_id="r1", task_id="t1", step_id="S1-review-0-0", agent_id="reviewer",
        engine="native", status="done", step_type="review", review_round=1,
        criteria=[{"criterion": "x", "passed": True, "note": ""}],
    )
    rows = cs.list_for_task("t1")
    assert "criteria_json" not in rows[0]
    rows = cs.list_recent(limit=10)
    assert "criteria_json" not in rows[0]
