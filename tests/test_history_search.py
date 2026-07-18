"""v33 P5: history search — FTS5 index over steps + audit, incremental sweep,
escaped queries, capped cited results; toolset + ops-command surfaces.

Load-bearing:
- sweep is incremental (watermark): re-sweep adds nothing new.
- FTS5 MATCH syntax in the query is data, not operators (no OperationalError).
- results carry a citable source ref; excerpts are capped.
- `history.search` is internal-only in the read toolset (external audience drops it).
"""

from __future__ import annotations

import json

import pytest

from my_crew.runtime.history_search_index import HistorySearchIndex
from my_crew.runtime.team_task_store import TeamTaskStore


@pytest.fixture()
def wired(tmp_path, monkeypatch):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    return tmp_path


def _seed_step(tmp_path, text="Quyết định: chốt agenda 4 mục cho buổi họp."):
    from my_crew.agent.team_task_artifact import write_step_artifact
    from my_crew.runtime.team_task_paths import team_tasks_db_path, team_tasks_root

    store = TeamTaskStore(team_tasks_db_path())
    store.create_task(task_id="t1", title="Họp tuần", pic_id="noi-dung")
    store.set_plan("t1", [
        {"step_id": "s1", "title": "Chốt agenda", "assigned_to": "noi-dung", "deps": []},
    ], "h1")
    seq = store.get("t1").steps[0].seq
    store._conn.execute(
        "UPDATE team_steps SET status='done', last_seen='2026-07-12T09:00:00+00:00' "
        "WHERE step_id='s1'")
    store._conn.commit()
    store.close()
    write_step_artifact(team_tasks_root(), "t1", seq, {
        "status": "done", "result_text": text,
        "step_title": "Chốt agenda", "attempt": "a1", "self_check_failed": False,
    })


def _seed_audit(tmp_path, monkeypatch):
    class _Entry:
        id = "noi-dung"

    monkeypatch.setattr("my_crew.runtime.registry.load_registry", lambda *a, **k: [_Entry()])
    audit_dir = tmp_path / "agents" / "noi-dung" / "audit"
    audit_dir.mkdir(parents=True)
    (audit_dir / "audit.jsonl").write_text(
        json.dumps({"tool": "slack:post", "verdict": "allow",
                    "result_summary": "đã gửi báo cáo tuần lên kênh nội bộ",
                    "timestamp": "2026-07-12T10:00:00+00:00"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "my_crew.runtime.agent_paths.agent_data_dir",
        lambda agent_id: tmp_path / "agents" / agent_id,
    )


def test_sweep_indexes_steps_and_audit_then_is_incremental(wired, monkeypatch):
    _seed_step(wired)
    _seed_audit(wired, monkeypatch)
    idx = HistorySearchIndex()
    try:
        assert idx.sweep() == 2  # one step artifact + one audit row
        assert idx.sweep() == 0  # watermark: nothing new on re-sweep
        step_hits = idx.search("agenda")
        assert len(step_hits) == 1 and step_hits[0]["source"] == "step"
        assert step_hits[0]["ref"].startswith("t1:")
        audit_hits = idx.search("báo cáo tuần")
        assert len(audit_hits) == 1 and audit_hits[0]["source"] == "audit"
        assert audit_hits[0]["agent_id"] == "noi-dung"
    finally:
        idx.close()


def test_search_escapes_fts_syntax_and_caps_results(wired):
    _seed_step(wired)
    idx = HistorySearchIndex()
    try:
        idx.sweep()
        # raw FTS operators/quotes must be treated as data, not syntax
        assert idx.search('agenda" OR NEAR(') == []
        assert idx.search("   ") == []
        hit = idx.search("agenda")[0]
        assert len(hit["excerpt"]) <= 500
    finally:
        idx.close()


def test_agent_and_days_filters(wired):
    _seed_step(wired)
    idx = HistorySearchIndex()
    try:
        idx.sweep()
        assert idx.search("agenda", agent="noi-dung")
        assert idx.search("agenda", agent="ai-khac") == []
        assert idx.search("agenda", days=36500)
    finally:
        idx.close()


def test_toolset_exposes_history_search_internal_only(wired):
    from my_crew.runtime_backends.read_only_toolset import build_read_toolset

    internal = build_read_toolset(None, audience="internal")
    external = build_read_toolset(None, audience="external")
    assert "history.search" in internal
    assert "history.search" not in external
    # empty query degrades to a message, never raises
    assert "cần tham số" in internal["history.search"]({})


def test_tool_returns_cited_wrapped_results(wired):
    from my_crew.runtime_backends.read_only_toolset import build_read_toolset

    _seed_step(wired)
    out = build_read_toolset(None, audience="internal")["history.search"](
        {"query": "agenda"})
    assert "t1:" in out and "noi-dung" in out  # citation rides along


def test_ops_command_search_history(wired):
    from my_crew.agent.ops_catalog import OPS_COMMANDS

    spec = OPS_COMMANDS["search_history"]
    assert spec["readonly"] is True
    _seed_step(wired)
    reply = spec["run"]({"query": "agenda"})
    assert "Tìm thấy" in reply and "Kết quả" in reply
    assert "Không tìm thấy" in spec["run"]({"query": "zzz-khong-co"})
