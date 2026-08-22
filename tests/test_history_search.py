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
    # The audit source walks the REGISTRY, which DATA_DIR does not redirect — without
    # this a test that skips `_seed_audit` sweeps the developer's real audit log
    # (observed: 66k rows). Point it at the tmp tree; `_seed_audit` refines it further.
    monkeypatch.setattr(
        "my_crew.runtime.agent_paths.agent_data_dir",
        lambda agent_id: tmp_path / "agents" / agent_id,
    )
    return tmp_path


def _seed_step(tmp_path, text="Quyết định: chốt agenda 4 mục cho buổi họp."):
    from my_crew.agent.team_task_artifact import write_step_artifact
    from my_crew.runtime.team_task_paths import team_tasks_db_path, team_tasks_root

    store = TeamTaskStore(team_tasks_db_path())
    store.create_task(task_id="t1", title="Họp tuần", pic_id="content")
    store.set_plan("t1", [
        {"step_id": "s1", "title": "Chốt agenda", "assigned_to": "content", "deps": []},
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


def _mark_sprint(step_id: str = "s1") -> None:
    from my_crew.runtime.team_task_paths import team_tasks_db_path

    store = TeamTaskStore(team_tasks_db_path())
    store._conn.execute(
        "UPDATE team_steps SET step_type='sprint' WHERE step_id=?", (step_id,))
    store._conn.commit()
    store.close()


def _seed_audit(tmp_path, monkeypatch):
    class _Entry:
        id = "content"

    monkeypatch.setattr("my_crew.runtime.registry.load_registry", lambda *a, **k: [_Entry()])
    audit_dir = tmp_path / "agents" / "content" / "audit"
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
        assert audit_hits[0]["agent_id"] == "content"
    finally:
        idx.close()


def test_sweep_indexes_a_sprint_step(wired):
    """A sprint task's only step is its whole output — skipping the type would make an
    entire mode of work unsearchable ("tuần trước đội khảo sát cái gì?")."""
    _seed_step(wired)
    _mark_sprint()
    idx = HistorySearchIndex()
    try:
        idx.sweep()
        hits = idx.search("agenda")
        assert [h["source"] for h in hits] == ["step"]
        assert hits[0]["ref"].startswith("t1:")
    finally:
        idx.close()


def test_search_escapes_fts_syntax_and_caps_results(wired):
    _seed_step(wired)
    idx = HistorySearchIndex()
    try:
        idx.sweep()
        # raw FTS operators/quotes must be treated as data, not syntax: the query
        # runs without an OperationalError and the operator words match nothing on
        # their own, so only the real word can pull a hit (via the any-word pass).
        rough = idx.search('agenda" OR NEAR(')
        assert all(h["matched"] == "any" for h in rough)
        assert idx.search('" OR NEAR(') == []
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
        assert idx.search("agenda", agent="content")
        assert idx.search("agenda", agent="ai-khac") == []
        assert idx.search("agenda", days=36500)
    finally:
        idx.close()


def test_all_words_wins_before_any_word_fallback(wired):
    _seed_step(wired)
    idx = HistorySearchIndex()
    try:
        idx.sweep()
        # every word present → exact pass answers, fallback never runs
        exact = idx.search("chốt agenda")
        assert exact and all(h["matched"] == "all" for h in exact)
        # a conversational question carries words the corpus lacks; the CEO still
        # gets the relevant rows instead of an empty answer
        loose = idx.search("tuần trước team chốt agenda gì")
        assert loose and all(h["matched"] == "any" for h in loose)
        # nothing relevant at all stays empty in both passes
        assert idx.search("zzz-khong-co qqq-khong-co") == []
    finally:
        idx.close()


def test_any_word_fallback_respects_filters(wired):
    _seed_step(wired)
    idx = HistorySearchIndex()
    try:
        idx.sweep()
        assert idx.search("tuần trước agenda gì", agent="content")
        assert idx.search("tuần trước agenda gì", agent="ai-khac") == []
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
    assert "t1:" in out and "content" in out  # citation rides along


def test_ops_command_search_history(wired):
    from my_crew.agent.ops_catalog import OPS_COMMANDS

    spec = OPS_COMMANDS["search_history"]
    assert spec["readonly"] is True
    _seed_step(wired)
    reply = spec["run"]({"query": "agenda"})
    assert "Tìm thấy" in reply and "Kết quả" in reply
    # a miss now coaches the CEO toward a narrower query instead of dead-ending
    miss = spec["run"]({"query": "zzz-khong-co"})
    assert "Không tìm thấy" in miss and "từ khoá ngắn hơn" in miss


def test_ops_command_search_history_days_slot(wired):
    from my_crew.agent.ops_catalog import OPS_COMMANDS

    spec = OPS_COMMANDS["search_history"]
    assert spec["slots"]["days"]["required"] is False
    _seed_step(wired)
    reply = spec["run"]({"query": "agenda", "days": "7"})
    assert "7 ngày qua" in reply
    # the seeded step is older than a week, so the window really filters
    assert "Không tìm thấy" in reply
    assert "Tìm thấy" in spec["run"]({"query": "agenda", "days": "36500"})


def test_ops_command_search_history_flags_loose_results(wired):
    from my_crew.agent.ops_catalog import OPS_COMMANDS

    _seed_step(wired)
    reply = OPS_COMMANDS["search_history"]["run"](
        {"query": "tuần trước team chốt agenda gì"})
    assert "Tìm thấy" in reply and "kết quả gần đúng" in reply
