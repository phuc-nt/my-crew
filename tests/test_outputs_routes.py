"""v33 P3: outputs hub + team-task board — read-only index, confined downloads.

Load-bearing:
- Index lists ONLY delivered steps (done + work/rework) plus exported files; filters
  by agent; newest first.
- Download is path-confined: unknown agent 404, separators in name 404, symlink
  escaping the artifact dir 404.
- Board lanes group by status; planning drafts visible; read-only (no write route).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.runtime.team_task_store import TeamTaskStore


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("src.runtime.team_task_paths.DATA_DIR", tmp_path)
    from src.server.app import create_app

    return TestClient(create_app())


class _Entry:
    def __init__(self, agent_id):
        self.id = agent_id


@pytest.fixture()
def agent_artifacts(monkeypatch, tmp_path):
    """One registry agent `noi-dung` with an artifact dir containing a real file and
    a symlink escaping the dir."""
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("secret", encoding="utf-8")
    art = tmp_path / "agents" / "noi-dung" / "artifacts"
    art.mkdir(parents=True)
    (art / "bao-cao.xlsx").write_bytes(b"xlsx-bytes")
    (art / "leak.txt").symlink_to(outside)

    monkeypatch.setattr(
        "src.runtime.registry.load_registry", lambda *a, **k: [_Entry("noi-dung")]
    )
    monkeypatch.setattr(
        "src.runtime.agent_paths.agent_data_dir",
        lambda agent_id: tmp_path / "agents" / agent_id,
    )
    return art


def _seed_tasks(*, statuses=("open",)):
    from src.runtime.team_task_paths import team_tasks_db_path

    store = TeamTaskStore(team_tasks_db_path())
    for i, status in enumerate(statuses, start=1):
        tid = f"t{i}"
        store.create_task(task_id=tid, title=f"Việc {i}", pic_id="noi-dung")
        store.set_plan(tid, [
            {"step_id": f"{tid}s1", "title": "Soạn", "assigned_to": "noi-dung", "deps": []},
            {"step_id": f"{tid}s2", "title": "Rà", "assigned_to": "kiem-dinh",
             "deps": [f"{tid}s1"]},
        ], f"h{i}")
        store._conn.execute(
            "UPDATE team_steps SET status='done' WHERE step_id=?", (f"{tid}s1",))
        if status != "open":
            store._conn.execute(
                "UPDATE team_tasks SET status=? WHERE id=?", (status, tid))
        store._conn.commit()
    store.close()


def test_index_lists_only_delivered_steps(client, tmp_path):
    _seed_tasks()
    items = client.get("/api/outputs").json()["items"]
    assert len(items) == 1  # s1 done; s2 pending stays out
    assert items[0]["kind"] == "step"
    assert items[0]["agent_id"] == "noi-dung"
    assert items[0]["step_title"] == "Soạn"


def test_index_agent_filter(client, tmp_path):
    _seed_tasks()
    assert client.get("/api/outputs?agent=noi-dung").json()["items"]
    assert client.get("/api/outputs?agent=kiem-dinh").json()["items"] == []


def test_index_includes_exported_files(client, tmp_path, agent_artifacts):
    _seed_tasks()
    items = client.get("/api/outputs").json()["items"]
    kinds = {i["kind"] for i in items}
    assert kinds == {"step", "file"}
    file_item = next(i for i in items if i["kind"] == "file" and i["name"] == "bao-cao.xlsx")
    assert file_item["agent_id"] == "noi-dung"


def test_step_content_via_hub_endpoint(client, tmp_path):
    from src.agent.team_task_artifact import write_step_artifact
    from src.runtime.team_task_paths import team_tasks_db_path, team_tasks_root

    _seed_tasks()
    store = TeamTaskStore(team_tasks_db_path())
    seq = next(s.seq for s in store.get("t1").steps if s.step_id == "t1s1")
    store.close()
    write_step_artifact(team_tasks_root(), "t1", seq, {
        "status": "done", "result_text": "nội dung bàn giao",
        "step_title": "Soạn", "attempt": "a1", "self_check_failed": False,
    })
    body = client.get(f"/api/outputs/step/t1/{seq}").json()
    assert body["result_text"] == "nội dung bàn giao"


def test_download_real_file(client, agent_artifacts):
    r = client.get("/api/outputs/file/noi-dung/bao-cao.xlsx")
    assert r.status_code == 200
    assert r.content == b"xlsx-bytes"
    assert "attachment" in r.headers.get("content-disposition", "")


def test_download_symlink_escape_is_404(client, agent_artifacts):
    assert client.get("/api/outputs/file/noi-dung/leak.txt").status_code == 404


def test_download_traversal_and_unknown_agent_404(client, agent_artifacts):
    assert client.get("/api/outputs/file/noi-dung/..%2f..%2fsecret").status_code == 404
    assert client.get("/api/outputs/file/ai-la/bao-cao.xlsx").status_code == 404


def test_board_lanes_group_by_status(client, tmp_path):
    _seed_tasks(statuses=("open", "done", "stalled"))
    # plus a planning draft (create_task without confirm keeps planning)
    from src.runtime.team_task_paths import team_tasks_db_path

    store = TeamTaskStore(team_tasks_db_path())
    store.create_task(task_id="draft1", title="Nháp", pic_id="")
    store.close()

    lanes = {l["id"]: l["cards"] for l in client.get("/api/team-tasks/board").json()["lanes"]}
    assert [c["task_id"] for c in lanes["planning"]] == ["draft1"]
    assert [c["task_id"] for c in lanes["open"]] == ["t1"]
    assert [c["task_id"] for c in lanes["done"]] == ["t2"]
    assert [c["task_id"] for c in lanes["khac"]] == ["t3"]
    card = lanes["open"][0]
    assert card["steps_done"] == 1 and card["steps_total"] == 2
    assert card["steps_needs_shell"] == 0  # v50: default no-shell (create_agent tier)


def test_board_card_counts_needs_shell_steps(client, tmp_path):
    """v50: a task with a needs_shell step reports steps_needs_shell so the FE can flag the
    deep_agent (Docker sandbox) tier."""
    from src.runtime.team_task_paths import team_tasks_db_path

    store = TeamTaskStore(team_tasks_db_path())
    store.create_task(task_id="tsh", title="Có shell", pic_id="noi-dung")
    store.set_plan("tsh", [
        {"step_id": "tsh1", "title": "Đọc", "assigned_to": "noi-dung", "deps": []},
        {"step_id": "tsh2", "title": "Chạy code", "assigned_to": "nghien-cuu",
         "deps": ["tsh1"], "needs_shell": True},
    ], "hsh")
    store._conn.execute("UPDATE team_tasks SET status='open' WHERE id='tsh'")
    store._conn.commit()
    store.close()

    lanes = {l["id"]: l["cards"] for l in client.get("/api/team-tasks/board").json()["lanes"]}
    card = next(c for c in lanes["open"] if c["task_id"] == "tsh")
    assert card["steps_needs_shell"] == 1 and card["steps_total"] == 2


def test_task_cost_no_captures_returns_zero_totals(client):
    """v50: a task with no capture rows (or no store yet) returns empty steps + zero totals,
    never a 500."""
    body = client.get("/api/team-tasks/nope/cost").json()
    assert body["steps"] == [] and body["total_cost_usd"] == 0.0


def test_task_cost_projects_steps_and_sums_totals(client):
    """v50: per-step-attempt telemetry is projected (allowlisted) + totals summed; None cost
    contributes 0 to the total."""
    from src.runtime.capture_store import CaptureStore
    from src.runtime.team_task_paths import capture_db_path

    store = CaptureStore(capture_db_path())
    store.record(attempt_id="a1", task_id="tc", step_id="s1", agent_id="noi-dung",
                 engine="create_agent", status="done", cost_usd=0.02,
                 input_tokens=100, output_tokens=40)
    store.record(attempt_id="a2", task_id="tc", step_id="s2", agent_id="nghien-cuu",
                 engine="deep_agent", status="done", cost_usd=None,  # dry-run → None
                 input_tokens=None, output_tokens=None)
    store.close()

    body = client.get("/api/team-tasks/tc/cost").json()
    assert body["task_id"] == "tc"
    assert len(body["steps"]) == 2
    assert body["total_cost_usd"] == 0.02  # None contributes 0
    assert body["total_input_tokens"] == 100 and body["total_output_tokens"] == 40
    # allowlist: only projected fields, no raw internal columns like attempt_id/started_at/error
    # (error could carry a stack trace or internal path — must never leak to the cost view).
    leaked = {"attempt_id", "started_at", "ended_at", "error"} & set(body["steps"][0])
    assert not leaked
