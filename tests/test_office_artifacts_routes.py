"""v17 `/api/office/.../artifacts` — read-only viewer routes: room catalog shape,
full-step read via the REAL artifact writer, clean 404s (unknown task / foreign seq /
unwritten file / path-layer validation error), int-coercion on seq, not-public pin."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from my_crew.runtime.team_task_store import TeamTaskStore


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    from my_crew.server.app import create_app

    return TestClient(create_app())


def _seed(tmp_path, *, with_artifact=True):
    from my_crew.agent.team_task_artifact import write_step_artifact
    from my_crew.runtime.team_task_paths import team_tasks_db_path, team_tasks_root

    store = TeamTaskStore(team_tasks_db_path())
    store.create_task(task_id="t1", title="Việc A", pic_id="noi-dung")
    store.set_plan("t1", [
        {"step_id": "s1", "title": "Nghiên cứu", "assigned_to": "nghien-cuu", "deps": []},
        {"step_id": "s2", "title": "Tổng hợp", "assigned_to": "noi-dung", "deps": ["s1"]},
    ], "h1")
    seqs = {s.step_id: s.seq for s in store.get("t1").steps}
    store._conn.execute("UPDATE team_steps SET status='done' WHERE step_id='s1'")
    store._conn.commit()
    store.close()
    if with_artifact:
        write_step_artifact(team_tasks_root(), "t1", seqs["s1"], {
            "status": "done", "result_text": "## Kết quả\n- một\n- hai",
            "step_title": "Nghiên cứu", "attempt": "att-1", "self_check_failed": False,
        })
    return seqs


def test_room_catalog_lists_tasks_and_steps(client, tmp_path):
    _seed(tmp_path)
    r = client.get("/api/office/rooms/t1/artifacts")
    assert r.status_code == 200
    tasks = r.json()["tasks"]
    assert tasks[0]["task_id"] == "t1" and tasks[0]["pic_id"] == "noi-dung"
    steps = {s["step_id"]: s for s in tasks[0]["steps"]}
    assert steps["s1"]["status"] == "done" and steps["s1"]["step_type"] == "work"
    assert isinstance(steps["s1"]["seq"], int)


def test_step_artifact_full_read(client, tmp_path):
    seqs = _seed(tmp_path)
    r = client.get(f"/api/office/tasks/t1/steps/{seqs['s1']}/artifact")
    assert r.status_code == 200
    body = r.json()
    assert body["result_text"].startswith("## Kết quả")
    assert body["step_title"] == "Nghiên cứu"
    assert body["self_check_failed"] is False


def test_404s_are_clean(client, tmp_path):
    seqs = _seed(tmp_path, with_artifact=False)
    assert client.get("/api/office/tasks/khong-co/steps/1/artifact").status_code == 404
    assert client.get(f"/api/office/tasks/t1/steps/{seqs['s1'] + 99}/artifact").status_code == 404
    # step exists but artifact never written (not delivered yet)
    assert client.get(f"/api/office/tasks/t1/steps/{seqs['s1']}/artifact").status_code == 404


def test_seq_traversal_is_type_blocked(client, tmp_path):
    _seed(tmp_path)
    assert client.get("/api/office/tasks/t1/steps/..%2F..%2Fetc/artifact").status_code in (404, 422)
    assert client.get("/api/office/tasks/t1/steps/abc/artifact").status_code == 422


def test_artifact_routes_are_not_public():
    from my_crew.server.auth import _PUBLIC_PREFIXES

    assert not any(p.startswith("/api/office") for p in _PUBLIC_PREFIXES)


def test_timeout_kill_emits_step_status_failed(monkeypatch, tmp_path):
    """v17 M2 pin: the ticker's timeout path must free the desk via a `step_status
    failed` room event (previously only a milestone → bubble hung forever)."""
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    from types import SimpleNamespace

    from my_crew.agent.coordinator_nodes.tick_actions import _append_timeout_step_event
    from my_crew.runtime.office_room_store import OfficeRoomStore, office_room_db_path
    from my_crew.runtime.team_task_paths import team_tasks_root

    task = SimpleNamespace(id="t-9", title="Việc X")
    step = SimpleNamespace(title="Bước Y", assigned_to="noi-dung")
    _append_timeout_step_event(task, step)

    store = OfficeRoomStore(office_room_db_path(team_tasks_root()))
    try:
        events = store.list("t-9")
    finally:
        store.close()
    assert events[0].kind == "step_status"
    assert events[0].body["status"] == "failed"
    assert events[0].body["assigned_to"] == "noi-dung"
