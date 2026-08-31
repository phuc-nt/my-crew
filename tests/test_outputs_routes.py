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

from my_crew.runtime.team_task_store import TeamTaskStore


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    from my_crew.server.app import create_app

    return TestClient(create_app())


class _Entry:
    def __init__(self, agent_id):
        self.id = agent_id


@pytest.fixture()
def agent_artifacts(monkeypatch, tmp_path):
    """One registry agent `content` with an artifact dir containing a real file and
    a symlink escaping the dir."""
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("secret", encoding="utf-8")
    art = tmp_path / "agents" / "content" / "artifacts"
    art.mkdir(parents=True)
    (art / "bao-cao.xlsx").write_bytes(b"xlsx-bytes")
    (art / "leak.txt").symlink_to(outside)

    monkeypatch.setattr(
        "my_crew.runtime.registry.load_registry", lambda *a, **k: [_Entry("content")]
    )
    monkeypatch.setattr(
        "my_crew.runtime.agent_paths.agent_data_dir",
        lambda agent_id: tmp_path / "agents" / agent_id,
    )
    return art


def _seed_tasks(*, statuses=("open",)):
    from my_crew.runtime.team_task_paths import team_tasks_db_path

    store = TeamTaskStore(team_tasks_db_path())
    for i, status in enumerate(statuses, start=1):
        tid = f"t{i}"
        store.create_task(task_id=tid, title=f"Việc {i}", pic_id="content")
        store.set_plan(tid, [
            {"step_id": f"{tid}s1", "title": "Soạn", "assigned_to": "content", "deps": []},
            {"step_id": f"{tid}s2", "title": "Rà", "assigned_to": "qa",
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
    assert items[0]["agent_id"] == "content"
    assert items[0]["step_title"] == "Soạn"


def test_index_lists_a_sprint_step(client, tmp_path):
    """A sprint task has exactly ONE content step, so its artifact is not part of the
    output — it IS the output. Omitting the type hid a whole mode of work from the hub."""
    from my_crew.runtime.team_task_paths import team_tasks_db_path

    _seed_tasks()
    store = TeamTaskStore(team_tasks_db_path())
    store._conn.execute("UPDATE team_steps SET step_type='sprint' WHERE step_id='t1s1'")
    store._conn.commit()
    store.close()
    items = client.get("/api/outputs").json()["items"]
    assert [i["step_title"] for i in items] == ["Soạn"]


def test_index_agent_filter(client, tmp_path):
    _seed_tasks()
    assert client.get("/api/outputs?agent=content").json()["items"]
    assert client.get("/api/outputs?agent=qa").json()["items"] == []


def test_index_includes_exported_files(client, tmp_path, agent_artifacts):
    _seed_tasks()
    items = client.get("/api/outputs").json()["items"]
    kinds = {i["kind"] for i in items}
    assert kinds == {"step", "file"}
    file_item = next(i for i in items if i["kind"] == "file" and i["name"] == "bao-cao.xlsx")
    assert file_item["agent_id"] == "content"


def test_step_content_via_hub_endpoint(client, tmp_path):
    from my_crew.agent.team_task_artifact import write_step_artifact
    from my_crew.runtime.team_task_paths import team_tasks_db_path, team_tasks_root

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
    r = client.get("/api/outputs/file/content/bao-cao.xlsx")
    assert r.status_code == 200
    assert r.content == b"xlsx-bytes"
    assert "attachment" in r.headers.get("content-disposition", "")


def test_download_symlink_escape_is_404(client, agent_artifacts):
    assert client.get("/api/outputs/file/content/leak.txt").status_code == 404


def test_download_traversal_and_unknown_agent_404(client, agent_artifacts):
    assert client.get("/api/outputs/file/content/..%2f..%2fsecret").status_code == 404
    assert client.get("/api/outputs/file/ai-la/bao-cao.xlsx").status_code == 404


def test_board_lanes_group_by_status(client, tmp_path):
    _seed_tasks(statuses=("open", "done", "stalled"))
    # plus a planning draft (create_task without confirm keeps planning)
    from my_crew.runtime.team_task_paths import team_tasks_db_path

    store = TeamTaskStore(team_tasks_db_path())
    store.create_task(task_id="draft1", title="Nháp", pic_id="")
    store.close()

    board = client.get("/api/team-tasks/board").json()
    lanes = {lane["id"]: lane["cards"] for lane in board["lanes"]}
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
    from my_crew.runtime.team_task_paths import team_tasks_db_path

    store = TeamTaskStore(team_tasks_db_path())
    store.create_task(task_id="tsh", title="Có shell", pic_id="content")
    store.set_plan("tsh", [
        {"step_id": "tsh1", "title": "Đọc", "assigned_to": "content", "deps": []},
        {"step_id": "tsh2", "title": "Chạy code", "assigned_to": "researcher",
         "deps": ["tsh1"], "needs_shell": True},
    ], "hsh")
    store._conn.execute("UPDATE team_tasks SET status='open' WHERE id='tsh'")
    store._conn.commit()
    store.close()

    board = client.get("/api/team-tasks/board").json()
    lanes = {lane["id"]: lane["cards"] for lane in board["lanes"]}
    card = next(c for c in lanes["open"] if c["task_id"] == "tsh")
    assert card["steps_needs_shell"] == 1 and card["steps_total"] == 2


def test_board_queue_position_orders_dispatchable_oldest_first(client, tmp_path):
    """v58 P2: open/running mang queue_position theo ĐÚNG thứ tự ticker phục vụ
    (created_at cũ trước — khớp list_dispatchable); planning/done/stalled không có field
    (client cũ không vỡ, card không badge)."""
    from my_crew.runtime.team_task_paths import team_tasks_db_path

    store = TeamTaskStore(team_tasks_db_path())
    for i, (tid, status) in enumerate(
        [("q1", "running"), ("q2", "open"), ("q3", "open"), ("qdone", "done")]
    ):
        store.create_task(task_id=tid, title=f"Việc {i}", pic_id="")
        store._conn.execute(
            "UPDATE team_tasks SET status=?, created_at=? WHERE id=?",
            (status, f"2026-08-03T10:0{i}:00+00:00", tid),
        )
    store._conn.commit()
    store.close()

    board = client.get("/api/team-tasks/board").json()
    cards = {c["task_id"]: c for lane in board["lanes"] for c in lane["cards"]}
    assert cards["q1"]["queue_position"] == 0  # cũ nhất — đang tới lượt
    assert cards["q2"]["queue_position"] == 1
    assert cards["q3"]["queue_position"] == 2
    assert "queue_position" not in cards["qdone"]  # ngoài hàng dispatchable


def test_task_cost_no_captures_returns_zero_totals(client):
    """v50: a task with no capture rows (or no store yet) returns empty steps + zero totals,
    never a 500."""
    body = client.get("/api/team-tasks/nope/cost").json()
    assert body["steps"] == [] and body["total_cost_usd"] == 0.0


def test_task_cost_projects_steps_and_sums_totals(client):
    """v50: per-step-attempt telemetry is projected (allowlisted); tokens summed from the
    capture rows. `total_cost_usd` is the task ledger's total (what the cost cap enforces
    against), NOT the sum of capture rows — so the task is seeded in BOTH stores here."""
    from my_crew.runtime.capture_store import CaptureStore
    from my_crew.runtime.team_task_paths import capture_db_path, team_tasks_db_path
    from my_crew.runtime.team_task_store import TeamTaskStore

    tasks = TeamTaskStore(team_tasks_db_path())
    tasks.create_task(task_id="tc", title="Việc test", pic_id="content")
    tasks.set_plan("tc", [
        {"step_id": "s1", "title": "bước 1", "assigned_to": "content", "deps": []},
        {"step_id": "s2", "title": "bước 2", "assigned_to": "researcher", "deps": []},
    ], plan_hash="h")
    tasks.mark_done("tc", "s1", cost_usd=0.02)
    tasks.mark_done("tc", "s2", cost_usd=None)  # dry-run → contributes 0
    tasks.close()

    store = CaptureStore(capture_db_path())
    store.record(attempt_id="a1", task_id="tc", step_id="s1", agent_id="content",
                 engine="create_agent", status="done", cost_usd=0.02,
                 input_tokens=100, output_tokens=40)
    store.record(attempt_id="a2", task_id="tc", step_id="s2", agent_id="researcher",
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


def test_task_route_unknown_task_returns_empty_fields(client):
    """v82: unknown task (or one predating route_json) → empty fields, never a 404/500 —
    absence is a normal state (cost-endpoint discipline)."""
    body = client.get("/api/team-tasks/nope/route").json()
    assert body == {"task_id": "nope", "mode": "", "source": "", "reason": ""}


def test_task_route_projects_allowlisted_fields(client, tmp_path):
    """v82: the persisted routing decision surfaces mode/source/reason only — `signals`
    (raw keyword matches over the brief) stays internal."""
    _seed_tasks(statuses=("open",))
    from my_crew.runtime.team_task_paths import team_tasks_db_path

    store = TeamTaskStore(team_tasks_db_path())
    store.set_route("t1", {"mode": "sprint", "source": "heuristic",
                           "reason": "việc 1 người, không cần review",
                           "signals": ["draft-only"]})
    store.close()

    body = client.get("/api/team-tasks/t1/route").json()
    assert body == {"task_id": "t1", "mode": "sprint", "source": "heuristic",
                    "reason": "việc 1 người, không cần review"}


def test_task_metrics_unknown_task_404s(client):
    """v82: metrics has no meaningful all-empty shape (unlike /route) — unknown task
    is a clean 404, and a missing db file must not be created as a side effect."""
    resp = client.get("/api/team-tasks/nope/metrics")
    assert resp.status_code == 404


def test_task_metrics_projects_store_metrics(client, tmp_path):
    """v82: wall-clock (created_at → latest last_seen, queue wait included) + step mix
    + cost, store-only — no per-agent transcript decomposition on this surface."""
    _seed_tasks(statuses=("open",))
    from my_crew.runtime.team_task_paths import team_tasks_db_path

    store = TeamTaskStore(team_tasks_db_path())
    store._conn.execute(
        "UPDATE team_tasks SET created_at='2026-08-16T10:00:00', cost_usd_total=0.5 "
        "WHERE id='t1'")
    store._conn.execute(
        "UPDATE team_steps SET last_seen='2026-08-16T10:03:19' WHERE step_id='t1s2'")
    store._conn.commit()
    store.close()

    body = client.get("/api/team-tasks/t1/metrics").json()
    assert body["task_id"] == "t1"
    assert body["mode"] == "team"  # no sprint step seeded
    assert body["wall_clock_seconds"] == 199.0
    assert body["wall_clock_text"] == "3m19s"
    assert body["cost_usd"] == 0.5
    assert body["step_count"] == 2
    assert body["content_steps"] == 2
    assert body["review_steps"] == 0 and body["rework_steps"] == 0
    assert [s["seq"] for s in body["steps"]] == [1, 2]
    # allowlist: step rows carry no step_id/agent internals on this surface
    assert set(body["steps"][0]) == {"seq", "step_type", "status", "cost_usd", "seconds"}
