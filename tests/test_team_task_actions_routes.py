"""v88 P3 one-click unstick + cancel (`routes_team_task_actions.py`): thin REST wrappers
over `ops_stalled_task`'s retry/accept/drop and the new `TeamTaskStore.cancel_task` — the
Work board's "≤2 clicks, no chat" recovery path for a stalled task.

Real on-disk store (SQLite, tmp_path), real FastAPI app, real ops functions — no mocks:
these are thin route wrappers, so the value under test IS the wiring (correct ops
function, correct status codes, no read-then-act race).
"""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from my_crew.agent.team_task_artifact import write_review_verdict_artifact, write_step_artifact
from my_crew.runtime.team_task_store import TeamTaskStore
from my_crew.server.app import create_app


@pytest.fixture(autouse=True)
def _isolated_team_tasks_root(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    return tmp_path


def _store(tmp_path) -> TeamTaskStore:
    return TeamTaskStore(tmp_path / "team_tasks.sqlite3")


def _client() -> TestClient:
    return TestClient(create_app())


def _content_hash(steps: list[dict]) -> str:
    """The real dispatch-time hash — matches `test_ops_stalled_task.py`'s helper so the
    ticker's plan_hash re-check (not exercised here) would agree if it ran."""
    from types import SimpleNamespace

    from my_crew.agent.task_decomposition import decomposition_content_hash

    return decomposition_content_hash(SimpleNamespace(steps=[
        SimpleNamespace(step_id=s["step_id"], title=s["title"],
                        assigned_to=s["assigned_to"], deps=tuple(s.get("deps", ())))
        for s in steps
    ]))


def _mk_dead_step_stalled_task(tmp_path, task_id="t2") -> None:
    """One step failed → the dead-step stall shape retry/drop act on."""
    store = _store(tmp_path)
    try:
        store.create_task(task_id=task_id, title="Demo dead", original_request="x",
                          assigned_by="ceo")
        steps = [{"step_id": "s1", "title": "thu thap", "assigned_to": "agent-a", "deps": []}]
        store.set_plan(task_id, steps, _content_hash(steps))
        attempt = store.reserve_step(task_id, "s1")
        store.mark_failed(task_id, "s1", attempt_id=attempt)
        store.set_task_status(task_id, "stalled")
    finally:
        store.close()


def _mk_review_stalled_task(tmp_path, task_id="t1") -> None:
    """One content step (done, needs_review) + one round-2 failed review — the shape
    `accept` needs (review-exhausted stall, no dead step)."""
    store = _store(tmp_path)
    try:
        store.create_task(task_id=task_id, title="Demo", original_request="x",
                          assigned_by="ceo")
        steps = [{"step_id": "s1", "title": "draft bao cao", "assigned_to": "agent-a",
                 "deps": [], "needs_review": True}]
        store.set_plan(task_id, steps, _content_hash(steps))
        attempt = store.reserve_step(task_id, "s1")
        store.mark_done(task_id, "s1", outcome_ref=f"team-tasks/{task_id}/step-1.json",
                        attempt_id=attempt)
        store.insert_step(task_id, {
            "step_id": "s1-review-2-2", "title": "Soat cheo: draft bao cao",
            "assigned_to": "agent-b", "deps": ["s1"], "step_type": "review",
            "parent_step_id": "s1", "review_round": 2,
        })
        r_attempt = store.reserve_step(task_id, "s1-review-2-2")
        store.mark_done(task_id, "s1-review-2-2", attempt_id=r_attempt)
        store.set_task_status(task_id, "stalled")
    finally:
        store.close()
    write_step_artifact(tmp_path, task_id, 1, {"result_text": "ban nhap", "version": attempt})
    write_review_verdict_artifact(
        tmp_path, task_id, 1, 2,
        {"passed": False, "failures": ["thieu so lieu"], "notes": [],
         "reviewed_version": attempt, "round": 2, "result_text": "ban nhap"},
    )


def _mk_running_task(tmp_path, task_id="t3", pid=4242) -> str:
    store = _store(tmp_path)
    try:
        store.create_task(task_id=task_id, title="Live task", original_request="x",
                          assigned_by="ceo")
        steps = [{"step_id": "s1", "title": "dang chay", "assigned_to": "agent-a", "deps": []}]
        store.set_plan(task_id, steps, _content_hash(steps))
        attempt = store.reserve_step(task_id, "s1")
        store.record_spawn(task_id, "s1", pid)
    finally:
        store.close()
    return attempt


# --- retry ---


def test_retry_happy_path_reopens_dead_step(tmp_path):
    _mk_dead_step_stalled_task(tmp_path)
    r = _client().post("/api/team-tasks/t2/steps/s1/retry")
    assert r.status_code == 200
    body = r.json()
    assert body["task_id"] == "t2"
    assert body["status"] in ("open", "running")
    assert _store(tmp_path).get_step("t2", "s1").status == "pending"


def test_retry_not_stalled_409_verbatim(tmp_path):
    store = _store(tmp_path)
    try:
        store.create_task(task_id="t9", title="ok", assigned_by="ceo")
        steps = [{"step_id": "s1", "title": "a", "assigned_to": "x", "deps": []}]
        store.set_plan("t9", steps, _content_hash(steps))
    finally:
        store.close()
    r = _client().post("/api/team-tasks/t9/steps/s1/retry")
    assert r.status_code == 409
    assert "không phải 'stalled'" in r.json()["detail"]


def test_retry_unknown_task_404(tmp_path):
    r = _client().post("/api/team-tasks/ghost/steps/s1/retry")
    assert r.status_code == 404


def test_two_concurrent_retries_one_wins_one_409(tmp_path):
    """The ops layer's own precondition check (`status == 'stalled'`) is the guard —
    the first request's retry flips the task off 'stalled', so the second necessarily
    sees a non-stalled task and gets a clean 409, never a double-apply."""
    _mk_dead_step_stalled_task(tmp_path)
    results = []
    barrier = threading.Barrier(2)

    def _call():
        barrier.wait()
        results.append(_client().post("/api/team-tasks/t2/steps/s1/retry").status_code)

    threads = [threading.Thread(target=_call) for _ in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    assert sorted(results) == [200, 409]


def test_retry_duplicate_insert_race_maps_to_409_not_500(tmp_path, monkeypatch):
    """The genuine TOCTOU window: both requests pass the `status == 'stalled'` check
    before either inserts, so the loser's INSERT hits UNIQUE(task_id, step_id) and
    raises sqlite3.IntegrityError. That is still a clean "someone beat you" rejection,
    so the route maps it to 409 — never a raw 500 to the operator."""
    import sqlite3

    import my_crew.agent.ops_stalled_task as ops

    _mk_dead_step_stalled_task(tmp_path)

    def _raise_integrity(_slots):
        raise sqlite3.IntegrityError("UNIQUE constraint failed: team_steps.step_id")

    monkeypatch.setattr(ops, "run_retry_stalled_step", _raise_integrity)
    r = _client().post("/api/team-tasks/t2/steps/s1/retry")
    assert r.status_code == 409


# --- accept ---


def test_accept_happy_path_reopens_task(tmp_path):
    _mk_review_stalled_task(tmp_path)
    r = _client().post("/api/team-tasks/t1/steps/_/accept")
    assert r.status_code == 200
    assert r.json()["status"] == "open"


def test_accept_not_stalled_409_verbatim(tmp_path):
    store = _store(tmp_path)
    try:
        store.create_task(task_id="t9", title="ok", assigned_by="ceo")
        steps = [{"step_id": "s1", "title": "a", "assigned_to": "x", "deps": []}]
        store.set_plan("t9", steps, _content_hash(steps))
    finally:
        store.close()
    r = _client().post("/api/team-tasks/t9/steps/s1/accept")
    assert r.status_code == 409
    assert "không phải 'stalled'" in r.json()["detail"]


def test_accept_unknown_task_404(tmp_path):
    r = _client().post("/api/team-tasks/ghost/steps/s1/accept")
    assert r.status_code == 404


# --- drop ---


def test_drop_happy_path_marks_step_done_empty(tmp_path):
    _mk_dead_step_stalled_task(tmp_path)
    r = _client().post("/api/team-tasks/t2/steps/s1/drop")
    assert r.status_code == 200
    assert _store(tmp_path).get_step("t2", "s1").status == "done"


def test_drop_not_stalled_409_verbatim(tmp_path):
    store = _store(tmp_path)
    try:
        store.create_task(task_id="t9", title="ok", assigned_by="ceo")
        steps = [{"step_id": "s1", "title": "a", "assigned_to": "x", "deps": []}]
        store.set_plan("t9", steps, _content_hash(steps))
    finally:
        store.close()
    r = _client().post("/api/team-tasks/t9/steps/s1/drop")
    assert r.status_code == 409


def test_drop_unknown_task_404(tmp_path):
    r = _client().post("/api/team-tasks/ghost/steps/s1/drop")
    assert r.status_code == 404


# --- cancel ---


def test_cancel_happy_path_open_task(tmp_path):
    store = _store(tmp_path)
    try:
        store.create_task(task_id="t5", title="Draft-less live", assigned_by="ceo")
        steps = [{"step_id": "s1", "title": "a", "assigned_to": "x", "deps": []}]
        store.set_plan("t5", steps, _content_hash(steps))
    finally:
        store.close()
    r = _client().post("/api/team-tasks/t5/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"


def test_cancel_running_task_stops_the_running_step_not_orphaned(tmp_path, monkeypatch):
    """Cancelling a task with a step mid-flight must not leave that step forever
    'running' — the inline `run_cancel_reap_sweep` call reaps it in the SAME request,
    not on the next tick."""
    attempt = _mk_running_task(tmp_path, task_id="t3", pid=13579)
    killed = []
    monkeypatch.setattr(
        "my_crew.runtime.team_tick_runner._kill_pid",
        lambda pid, attempt_id, **k: killed.append((pid, attempt_id)),
    )

    r = _client().post("/api/team-tasks/t3/cancel")

    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"
    step = _store(tmp_path).get_step("t3", "s1")
    assert step.status == "failed"  # reaped, not left 'running'
    assert killed == [(13579, attempt)]


def test_cancel_terminal_task_409(tmp_path):
    store = _store(tmp_path)
    try:
        store.create_task(task_id="t6", title="Done already", assigned_by="ceo")
        steps = [{"step_id": "s1", "title": "a", "assigned_to": "x", "deps": []}]
        store.set_plan("t6", steps, _content_hash(steps))
        store.set_task_status("t6", "done")
    finally:
        store.close()
    r = _client().post("/api/team-tasks/t6/cancel")
    assert r.status_code == 409
    assert "t6" in r.json()["detail"]


def test_cancel_unknown_task_404(tmp_path):
    r = _client().post("/api/team-tasks/ghost/cancel")
    assert r.status_code == 404


def test_two_concurrent_cancels_one_wins_one_409(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "my_crew.runtime.team_tick_runner._kill_pid", lambda pid, attempt_id, **k: None,
    )
    store = _store(tmp_path)
    try:
        store.create_task(task_id="t7", title="Race me", assigned_by="ceo")
        steps = [{"step_id": "s1", "title": "a", "assigned_to": "x", "deps": []}]
        store.set_plan("t7", steps, _content_hash(steps))
    finally:
        store.close()
    results = []
    barrier = threading.Barrier(2)

    def _call():
        barrier.wait()
        results.append(_client().post("/api/team-tasks/t7/cancel").status_code)

    threads = [threading.Thread(target=_call) for _ in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    assert sorted(results) == [200, 409]
