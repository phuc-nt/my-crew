"""v16 workrooms: store room_id + list_workrooms rollup, room_for_task routing,
chat intent tiers (hard regex vs LLM-classified — M3/M4), question read-only,
coordinator health API semantics (M2)."""

from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

from my_crew.runtime.team_task_store import TeamTaskStore


def _store(tmp_path):
    return TeamTaskStore(tmp_path / "t.sqlite3")


def _plan(step="s1", who="u"):
    return [{"step_id": step, "title": "x", "assigned_to": who, "deps": []}]


# ---- store ------------------------------------------------------------------

def test_room_id_roundtrip_and_old_task_defaults(tmp_path):
    st = _store(tmp_path)
    st.create_task(task_id="a", title="T1")
    st.create_task(task_id="b", title="T2", room_id="a")
    assert st.get("a").room_id == ""  # pre-v16 shape: own room
    assert st.get("b").room_id == "a"
    with pytest.raises(ValueError, match="office"):
        st.create_task(task_id="c", title="T3", room_id="office")
    st.close()


def test_list_workrooms_rollup_and_draft_exclusion(tmp_path):
    st = _store(tmp_path)
    st.create_task(task_id="a", title="Room A")
    st.set_plan("a", _plan(), "h1")  # open
    st.create_task(task_id="b", title="Child", room_id="a")
    st.set_plan("b", _plan(), "h2")
    st.create_task(task_id="draft", title="Draft")  # planning — excluded
    rooms = st.list_workrooms()
    assert len(rooms) == 1
    assert rooms[0]["room_id"] == "a"
    assert rooms[0]["task_count"] == 2
    assert rooms[0]["status"] == "dang-chay"
    assert st.tasks_in_room("a") and len(st.tasks_in_room("a")) == 2
    st.close()


def test_room_for_task_effective_and_degrade(tmp_path, monkeypatch):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    from my_crew.runtime.office_room_append import room_for_task
    from my_crew.runtime.team_task_paths import team_tasks_db_path

    st = TeamTaskStore(team_tasks_db_path())
    st.create_task(task_id="root", title="R")
    st.create_task(task_id="child", title="C", room_id="root")
    st.close()
    assert room_for_task("root") == "root"
    assert room_for_task("child") == "root"
    assert room_for_task("khong-ton-tai") == "khong-ton-tai"  # degrade = own room


# ---- intent tiers (M3/M4) ----------------------------------------------------

def test_resolve_intent_hard_prefixes_no_llm(monkeypatch):
    import my_crew.server.routes_office_room_chat as mod

    def _boom(_msg):
        raise AssertionError("hard prefix must not call the LLM")

    monkeypatch.setattr(mod, "_classify_with_llm", _boom)
    assert mod.resolve_intent("@noi-dung viết bài") == ("new_task", "@noi-dung viết bài", "", True)
    assert mod.resolve_intent("giao thêm việc phân tích") == \
        ("new_task", "thêm việc phân tích", "", True)
    intent, payload, task, hard = mod.resolve_intent("chỉnh abc123: bỏ bước cuối")
    assert (intent, task, hard) == ("adjust", "abc123", True) and "bỏ bước cuối" in payload
    intent, _p, task, hard = mod.resolve_intent("chỉnh: thêm bước tổng hợp")
    assert (intent, task, hard) == ("adjust", "", True)


def test_resolve_intent_llm_tier_never_hard(monkeypatch):
    import my_crew.server.routes_office_room_chat as mod

    monkeypatch.setattr(mod, "_classify_with_llm", lambda m: "new_task")
    intent, payload, _t, hard = mod.resolve_intent("mình cần thêm một bài so sánh giá nhé")
    assert intent == "new_task" and hard is False
    monkeypatch.setattr(mod, "_classify_with_llm", lambda m: "question")
    assert mod.resolve_intent("tiến độ thế nào rồi?")[0] == "question"


def test_classify_garbage_defaults_to_question(monkeypatch):
    import my_crew.server.routes_office_room_chat as mod

    class _Llm:
        def complete(self, messages):
            class R:
                content = "not json"
                cost_usd = 0.0
            return R()

    monkeypatch.setattr("my_crew.llm.client.LlmClient", lambda s: _Llm())
    assert mod._classify_with_llm("gì đó mơ hồ") == "question"


# ---- chat endpoint ------------------------------------------------------------

@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    from my_crew.server.app import create_app

    return TestClient(create_app())


def test_chat_question_is_read_only_and_appends_ceo_event(client, monkeypatch, tmp_path):
    import my_crew.server.routes_office_room_chat as mod

    monkeypatch.setattr(mod, "_classify_with_llm", lambda m: "question")
    monkeypatch.setattr("my_crew.agent.office_room_qa.answer_room_question",
                        lambda room, q, settings: ("Đang chạy tốt.", 0.0))
    r = client.post("/api/office/rooms/room-1/chat", json={"message": "ổn không?"})
    assert r.status_code == 200
    assert r.json() == {"intent": "question", "reply": "Đang chạy tốt."}

    from my_crew.runtime.office_room_store import OfficeRoomStore, office_room_db_path
    from my_crew.runtime.team_task_paths import team_tasks_root

    store = OfficeRoomStore(office_room_db_path(team_tasks_root()))
    try:
        events = store.list("room-1")
    finally:
        store.close()
    assert [e.kind for e in events] == ["ceo"]  # question wrote NOTHING else
    # and no task row appeared
    from my_crew.runtime.team_task_paths import team_tasks_db_path

    st = TeamTaskStore(team_tasks_db_path())
    assert st.list_workrooms() == []
    st.close()


def test_chat_adjust_zero_and_many_tasks_ask_back(client, monkeypatch, tmp_path):
    from my_crew.runtime.team_task_paths import team_tasks_db_path

    r = client.post("/api/office/rooms/r1/chat", json={"message": "chỉnh: bỏ bước 2"})
    assert "Không tìm thấy việc" in r.json()["reply"]

    st = TeamTaskStore(team_tasks_db_path())
    st.create_task(task_id="t1", title="A", room_id="r1")
    st.set_plan("t1", _plan(), "h1")
    st.create_task(task_id="t2", title="B", room_id="r1")
    st.set_plan("t2", _plan(), "h2")
    st.close()
    r = client.post("/api/office/rooms/r1/chat", json={"message": "chỉnh: bỏ bước 2"})
    assert "nhiều việc" in r.json()["reply"]


def test_chat_new_task_llm_tier_forces_manual_confirm(client, monkeypatch):
    import my_crew.agent.ops_assign_team_task as assign_mod
    import my_crew.server.routes_office_room_chat as mod

    monkeypatch.setattr(mod, "_classify_with_llm", lambda m: "new_task")
    captured = {}

    def _fake_preview(slots):
        captured.update(slots)
        slots["task_id"] = "t-9"
        slots["plan_hash"] = "h-9"
        return "KẾ HOẠCH"

    monkeypatch.setattr(assign_mod, "preview_assign_team_task", _fake_preview)
    r = client.post("/api/office/rooms/r9/chat",
                    json={"message": "cần thêm một bảng so sánh giá"})
    assert r.status_code == 200
    assert captured["room_id"] == "r9"  # child task joins the room
    assert captured["no_auto_confirm"] == "1"  # LLM tier NEVER auto-confirms (M3)


# ---- health (M2) ---------------------------------------------------------------

def test_coordinator_health_states(client, monkeypatch, tmp_path):
    from types import SimpleNamespace

    import my_crew.runtime.company as company_mod
    import my_crew.server.routes_office_room_chat as mod

    monkeypatch.setattr("my_crew.config.settings.DATA_DIR", tmp_path)
    monkeypatch.setattr(company_mod, "load_company",
                        lambda: SimpleNamespace(coordinator_id=None))
    assert client.get("/api/health/coordinator").json()["reason"] == "no_coordinator"

    monkeypatch.setattr(company_mod, "load_company",
                        lambda: SimpleNamespace(coordinator_id="truong-phong"))
    assert client.get("/api/health/coordinator").json()["reason"] == "no_heartbeat"

    beat = tmp_path / "coordinator.heartbeat"
    beat.touch()
    body = client.get("/api/health/coordinator").json()
    assert body["alive"] is True and body["reason"] == ""

    old = time.time() - (mod._HEARTBEAT_STALE_S + 60)
    os.utime(beat, (old, old))
    body = client.get("/api/health/coordinator").json()
    assert body["alive"] is False and body["reason"] == "stale"
