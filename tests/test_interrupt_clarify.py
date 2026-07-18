"""v34 P2: interrupt clarify — the graph pauses mid-step on a CEO question and
resumes with the answer folded in via rework.

Load-bearing:
- checkpointed graph + ceo proposal → interrupt (pause) → Command(resume=answer)
  → rework updates the draft; work is never re-paid.
- empty answer (expired / safe default) → no rework, the draft ships as-is.
- un-checkpointed graph → v33 fire-and-forget pass-through (no interrupt).
- ticker resume input: answered→Command(answer), expired→Command(""), pending→wait.
- store: mark_waiting_clarify persists status+clarify_id; a fresh reserve clears it.
"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from my_crew.agent.team_task_graph import TeamTaskDeps, build_team_task_graph


def _saver(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "cp.sqlite3"), check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver


def _deps(work_calls, rework_calls, deliver_versions):
    return TeamTaskDeps(
        read_handoff=lambda: "",
        run_work=lambda t, h, hook: (work_calls.append(t) or ("BẢN NHÁP AN TOÀN", 0.01)),
        run_self_check=lambda text, acc: (True, [], 1.0),
        run_rework=lambda brief, prior, failures: (
            rework_calls.append(failures) or (f"{prior} + THEO CEO", 0.01)
        ),
        deliver_step=lambda text, version, flag: (
            deliver_versions.append((version, text)) or (True, "ok")
        ),
        ask_colleague=lambda a, q: ("", 0.0),
        propose_consults=lambda t, h: [("ceo", "Ưu tiên gì?", ["Chi phí", "Tốc độ"])],
        ask_ceo=lambda q, opts: ("Đã gửi câu hỏi cho CEO (mã #42).", 42),
        set_attempt_id=lambda a: None,
    )


def _run(graph, stream_input, config):
    """Mirror `_run_graph`'s loop: merge updates, surface an interrupt as
    waiting_clarify + clarify_id (the runner's own contract)."""
    state: dict = dict(stream_input) if isinstance(stream_input, dict) else {}
    for mode, chunk in graph.stream(stream_input, config, stream_mode=["updates", "custom"]):
        if mode != "updates":
            continue
        if isinstance(chunk, dict) and "__interrupt__" in chunk:
            intr = chunk["__interrupt__"]
            payload = getattr(intr[0], "value", {}) if intr else {}
            state["status"] = "waiting_clarify"
            state["clarify_id"] = (payload or {}).get("clarify_id")
            continue
        for out in chunk.values():
            if isinstance(out, dict):
                state.update(out)
    return state


_INITIAL = {"step_title": "Bước", "acceptance": "", "attempt_id": "a1", "version": "a1"}


def test_interrupt_then_answer_reworks_the_draft(tmp_path):
    work_calls, rework_calls, delivered = [], [], []
    saver = _saver(tmp_path)
    graph = build_team_task_graph(saver, deps=_deps(work_calls, rework_calls, delivered))
    config = {"configurable": {"thread_id": "team:t1:s1"}}

    paused = _run(graph, dict(_INITIAL), config)
    assert paused["status"] == "waiting_clarify" and paused["clarify_id"] == 42
    assert work_calls == ["Bước"] and delivered == []  # drafted, then paused

    final = _run(graph, Command(resume="Tốc độ"), config)
    assert work_calls == ["Bước"]  # work never re-paid
    assert len(rework_calls) == 1 and "Tốc độ" in rework_calls[0][0]
    assert delivered and "THEO CEO" in delivered[0][1]
    assert final.get("status") != "waiting_clarify"


def test_empty_answer_ships_the_safe_draft_without_rework(tmp_path):
    work_calls, rework_calls, delivered = [], [], []
    saver = _saver(tmp_path)
    graph = build_team_task_graph(saver, deps=_deps(work_calls, rework_calls, delivered))
    config = {"configurable": {"thread_id": "team:t2:s1"}}

    paused = _run(graph, dict(_INITIAL), config)
    assert paused["status"] == "waiting_clarify"

    _run(graph, Command(resume=""), config)
    assert rework_calls == []  # no answer → no rework
    assert delivered and delivered[0][1] == "BẢN NHÁP AN TOÀN"


def test_uncheckpointed_graph_keeps_v33_fire_and_forget(tmp_path):
    work_calls, rework_calls, delivered = [], [], []
    graph = build_team_task_graph(deps=_deps(work_calls, rework_calls, delivered))

    state = _run(graph, dict(_INITIAL), None)
    assert state.get("status") != "waiting_clarify"  # never paused
    assert delivered and "BẢN NHÁP AN TOÀN" in delivered[0][1]
    assert rework_calls == []


def test_clarify_resume_input_maps_store_status(monkeypatch):
    from my_crew.runtime import team_step_runner as runner

    intr = SimpleNamespace(value={"clarify_id": 7, "question": "q"})
    snapshot = SimpleNamespace(tasks=(SimpleNamespace(interrupts=(intr,)),))

    monkeypatch.setattr(
        "my_crew.runtime.clarify_service.clarify_status", lambda cid: ("answered", "Tốc độ"))
    cmd, waiting = runner._clarify_resume_input(snapshot)
    assert waiting is False and isinstance(cmd, Command) and cmd.resume == "Tốc độ"

    monkeypatch.setattr(
        "my_crew.runtime.clarify_service.clarify_status", lambda cid: ("expired", ""))
    cmd, waiting = runner._clarify_resume_input(snapshot)
    assert waiting is False and cmd.resume == ""

    monkeypatch.setattr(
        "my_crew.runtime.clarify_service.clarify_status", lambda cid: ("pending", ""))
    cmd, waiting = runner._clarify_resume_input(snapshot)
    assert waiting is True and cmd is None


def test_store_waiting_clarify_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    from my_crew.runtime.team_task_paths import team_tasks_db_path
    from my_crew.runtime.team_task_store import TeamTaskStore

    store = TeamTaskStore(team_tasks_db_path())
    store.create_task(task_id="t1", title="T", pic_id="")
    store.set_plan("t1", [{"step_id": "s1", "title": "x", "assigned_to": "a",
                           "deps": []}], "h")
    attempt = store.reserve_step("t1", "s1")
    assert store.mark_waiting_clarify("t1", "s1", attempt_id=attempt, clarify_id=9)
    step = store.get_step("t1", "s1")
    assert step.status == "waiting_clarify" and step.clarify_id == 9

    # a fresh reserve (retry path) clears the stale gate ids
    store.reserve_step("t1", "s1")
    assert store.get_step("t1", "s1").clarify_id is None
    store.close()


def test_poll_waiting_clarify_step_dispatch_rules(monkeypatch):
    from my_crew.agent.coordinator_nodes import tick_actions

    spawned = []
    monkeypatch.setattr(
        tick_actions, "reserve_and_spawn",
        lambda deps, task, step: spawned.append(step.step_id) or
        SimpleNamespace(task_id=task.id, action="spawned", detail=step.step_id),
    )
    task = SimpleNamespace(id="t1")
    step = SimpleNamespace(step_id="s1", clarify_id=5)

    deps = SimpleNamespace(clarify_status=lambda cid: ("pending", ""))
    out = tick_actions.poll_waiting_clarify_step(deps, task, step)
    assert out.action == "none" and spawned == []

    deps = SimpleNamespace(clarify_status=lambda cid: ("answered", "OK"))
    out = tick_actions.poll_waiting_clarify_step(deps, task, step)
    assert out.action == "spawned" and spawned == ["s1"]

    deps = SimpleNamespace(clarify_status=lambda cid: ("expired", ""))
    out = tick_actions.poll_waiting_clarify_step(deps, task, step)
    assert spawned == ["s1", "s1"]

    # unresolvable id (wiped clarify DB) → leave alone
    deps = SimpleNamespace(clarify_status=lambda cid: None)
    out = tick_actions.poll_waiting_clarify_step(deps, task, step)
    assert out.action == "none" and len(spawned) == 2


# --- review H1/H2 regression guards ---


def test_dead_end_detector_counts_waiting_clarify_as_in_flight():
    """H1: one terminally-failed step + one clarify-paused sibling must NOT stall the
    task — the paused step is alive, and stalling would orphan the pending clarify
    (a stalled task leaves list_dispatchable, so the poll never runs again)."""
    from my_crew.agent.coordinator_graph import _dead_end_result

    task = SimpleNamespace(
        id="t1", title="T",
        steps=(
            SimpleNamespace(status="failed"),
            SimpleNamespace(status="waiting_clarify"),
        ),
    )
    assert _dead_end_result(SimpleNamespace(), task) is None


def test_pending_resume_carries_clarify_id_and_keeps_thread(tmp_path, monkeypatch):
    """H2: a premature dispatch of a still-pending clarify step must (a) report the
    clarify_id extracted from the INTERRUPT PAYLOAD (snapshot values never carry it —
    a None here would re-mark the step un-pollable after the crash window), and
    (b) leave the thread resumable afterwards."""
    from my_crew.runtime import team_step_runner as runner

    work_calls, rework_calls, delivered = [], [], []
    saver = _saver(tmp_path)
    graph = build_team_task_graph(saver, deps=_deps(work_calls, rework_calls, delivered))
    config = {"configurable": {"thread_id": "team:t9:s1"}}
    _run(graph, dict(_INITIAL), config)  # pauses on the interrupt (clarify_id=42)

    monkeypatch.setattr(
        "my_crew.runtime.clarify_service.clarify_status", lambda cid: ("pending", ""))
    stream_input, state, finished = runner._load_resume_state(
        graph, config, dict(_INITIAL), attempt_id="a2", task_id="t9", step_id="s1",
    )
    assert finished is not None and finished["status"] == "waiting_clarify"
    assert finished["clarify_id"] == 42  # from the interrupt payload, not values

    # thread must still be resumable once the CEO answers
    monkeypatch.setattr(
        "my_crew.runtime.clarify_service.clarify_status",
        lambda cid: ("answered", "Tốc độ"))
    stream_input, state, finished = runner._load_resume_state(
        graph, config, dict(_INITIAL), attempt_id="a3", task_id="t9", step_id="s1",
    )
    assert finished is None
    _run(graph, stream_input, config)
    assert delivered and "THEO CEO" in delivered[0][1]
