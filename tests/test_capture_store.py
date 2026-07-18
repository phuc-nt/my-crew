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
