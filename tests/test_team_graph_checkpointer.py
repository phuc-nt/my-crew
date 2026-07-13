"""v34 P1: team-graph checkpointer — resume mid-step without re-paying completed
nodes, finished-checkpoint short-circuit (no double-deliver), attempt adoption,
eager thread cleanup, ticker sweep of orphaned threads.

Load-bearing:
- a crash between nodes → the NEXT attempt resumes at the failed node; `run_work`
  is charged exactly once.
- a crash between graph-END and `mark_done` → the saved state returns as-is;
  `deliver` never runs twice.
- resumed state carries the NEW attempt_id (store writes must match the live lease).
- no checkpoint → byte-identical fresh run.
"""

from __future__ import annotations

import sqlite3

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from src.agent.team_task_graph import TeamTaskDeps, build_team_task_graph
from src.runtime.team_step_runner import _delete_thread_best_effort, _load_resume_state


def _saver(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "team_checkpoints.sqlite3"),
                           check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver


def _deps(work_calls, deliver_calls, *, check_box):
    """Fake deps: run_work counts calls; self_check consults `check_box['fail']` so a
    test can make the FIRST pass die (simulated crash) and the resumed pass succeed."""

    def run_work(title, handoff, hook):
        work_calls.append(title)
        return "KQ bước", 0.01

    def run_self_check(text, acceptance):
        if check_box.get("fail"):
            raise RuntimeError("crash giữa chừng (giả lập kill -9)")
        return True, [], 1.0

    def deliver(text, version, flag):
        deliver_calls.append(version)
        return True, f"[done] {text}"

    return TeamTaskDeps(
        read_handoff=lambda: "",
        run_work=run_work,
        run_self_check=run_self_check,
        run_rework=lambda b, p, f: ("", None),
        deliver_step=deliver,
    )


def _initial(attempt):
    return {"step_title": "Bước dài", "acceptance": "", "attempt_id": attempt,
            "version": attempt}


def _stream(graph, stream_input, config):
    state = dict(stream_input or {})
    for mode, chunk in graph.stream(stream_input, config, stream_mode=["updates", "custom"]):
        if mode == "updates":
            for out in chunk.values():
                if isinstance(out, dict):
                    state.update(out)
    return state


def test_resume_after_crash_does_not_repay_work(tmp_path):
    saver = _saver(tmp_path)
    work_calls, deliver_calls = [], []
    check_box = {"fail": True}
    config = {"configurable": {"thread_id": "team:t1:s1"}}

    graph = build_team_task_graph(saver, deps=_deps(work_calls, deliver_calls,
                                                    check_box=check_box))
    with pytest.raises(RuntimeError):
        _stream(graph, _initial("att-1"), config)
    assert work_calls == ["Bước dài"] and deliver_calls == []

    # "restart": new process = new graph object, same thread; the crash is gone.
    check_box["fail"] = False
    graph2 = build_team_task_graph(saver, deps=_deps(work_calls, deliver_calls,
                                                     check_box=check_box))
    stream_input, state, finished = _load_resume_state(
        graph2, config, _initial("att-2"), attempt_id="att-2",
        task_id="t1", step_id="s1",
    )
    assert finished is None and stream_input is None  # mid-run resume
    assert state["attempt_id"] == "att-2"  # the new lease's attempt was adopted
    final = _stream(graph2, None, config)
    final = {**state, **final} if final else state

    assert work_calls == ["Bước dài"]  # work was NOT re-paid
    assert deliver_calls == ["att-2"]  # deliver ran once, under the NEW attempt
    snapshot = graph2.get_state(config)
    assert snapshot.values.get("result_text") == "KQ bước"


def test_finished_checkpoint_short_circuits_no_double_deliver(tmp_path):
    saver = _saver(tmp_path)
    work_calls, deliver_calls = [], []
    config = {"configurable": {"thread_id": "team:t2:s1"}}
    graph = build_team_task_graph(saver, deps=_deps(work_calls, deliver_calls,
                                                    check_box={}))
    _stream(graph, _initial("att-1"), config)
    assert deliver_calls == ["att-1"]

    # crash landed AFTER graph-END but BEFORE mark_done → next attempt short-circuits
    stream_input, state, finished = _load_resume_state(
        graph, config, _initial("att-2"), attempt_id="att-2",
        task_id="t2", step_id="s1",
    )
    assert finished is not None
    assert finished.get("result_text") == "KQ bước"
    assert deliver_calls == ["att-1"]  # nothing re-ran


def test_no_checkpoint_is_a_fresh_run(tmp_path):
    saver = _saver(tmp_path)
    graph = build_team_task_graph(saver, deps=_deps([], [], check_box={}))
    config = {"configurable": {"thread_id": "team:t3:s1"}}
    initial = _initial("att-1")
    stream_input, state, finished = _load_resume_state(
        graph, config, initial, attempt_id="att-1", task_id="t3", step_id="s1",
    )
    assert stream_input == initial and finished is None


def test_delete_thread_cleans_up(tmp_path):
    saver = _saver(tmp_path)
    config = {"configurable": {"thread_id": "team:t4:s1"}}
    graph = build_team_task_graph(saver, deps=_deps([], [], check_box={}))
    _stream(graph, _initial("att-1"), config)
    assert graph.get_state(config).values  # thread exists

    _delete_thread_best_effort(saver, "team:t4:s1")
    assert not graph.get_state(config).values  # gone


def test_ticker_sweep_removes_only_terminal_task_threads(tmp_path, monkeypatch):
    monkeypatch.setattr("src.runtime.team_task_paths.DATA_DIR", tmp_path)
    from src.runtime.team_task_paths import team_checkpoints_db_path, team_tasks_db_path
    from src.runtime.team_task_store import TeamTaskStore
    from src.runtime.team_tick_runner import _sweep_team_checkpoints

    # two real tasks: one done, one open
    store = TeamTaskStore(team_tasks_db_path())
    for tid, status in (("t-done", "done"), ("t-live", "open")):
        store.create_task(task_id=tid, title=tid, pic_id="")
        store.set_plan(tid, [{"step_id": "s1", "title": "x", "assigned_to": "a",
                              "deps": []}], "h")
        store._conn.execute("UPDATE team_tasks SET status=? WHERE id=?", (status, tid))
        store._conn.commit()

    conn = sqlite3.connect(str(team_checkpoints_db_path()), check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    for tid in ("t-done", "t-live", "t-vanished"):
        graph = build_team_task_graph(saver, deps=_deps([], [], check_box={}))
        _stream(graph, _initial("a1"), {"configurable": {"thread_id": f"team:{tid}:s1"}})

    _sweep_team_checkpoints(store)

    remaining = {
        r[0] for r in conn.execute("SELECT DISTINCT thread_id FROM checkpoints")
    }
    assert "team:t-live:s1" in remaining  # live task thread kept (resume state)
    assert "team:t-done:s1" not in remaining
    assert "team:t-vanished:s1" not in remaining  # unknown task swept too
    store.close()
