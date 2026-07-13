"""v33 P4 clarify flow — store guarantees, service sanitize/notify, Telegram callback
parse + inbox handling, work-node "ceo" branch, handoff delivery, web routes.

Load-bearing:
- first-answer-wins under a web/Telegram race (conditional UPDATE).
- pending cap per agent refuses floods at create.
- expired questions can never wedge anything (sweep flips, task already moved on).
- a button tap from a non-allowlisted chat never reaches the store.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.runtime import clarify_service
from src.runtime.clarify_store import (
    MAX_PENDING_PER_AGENT,
    ClarifyCapError,
    ClarifyStore,
)


@pytest.fixture()
def store(tmp_path):
    s = ClarifyStore(tmp_path / "clarify.sqlite3")
    yield s
    s.close()


@pytest.fixture()
def wired(tmp_path, monkeypatch):
    """Point the module-level path helper at a tmp store for service/route tests."""
    monkeypatch.setattr("src.runtime.team_task_paths.DATA_DIR", tmp_path)
    return tmp_path


# --- store ---


def test_first_answer_wins(store):
    cid = store.create_question(agent_id="a", task_id="t", question="Chọn?",
                                options=["A", "B"])
    assert store.apply_answer(cid, "A") is True
    assert store.apply_answer(cid, "B") is False  # the race loser lands nothing
    row = store.get(cid)
    assert row.status == "answered" and row.answer == "A"


def test_pending_cap_refuses_flood(store):
    for i in range(MAX_PENDING_PER_AGENT):
        store.create_question(agent_id="a", task_id="t", question=f"q{i}")
    with pytest.raises(ClarifyCapError):
        store.create_question(agent_id="a", task_id="t", question="q-thừa")
    # a different agent is unaffected
    store.create_question(agent_id="b", task_id="t", question="q-khác")


def test_expire_flips_only_overdue(store):
    overdue = store.create_question(agent_id="a", task_id="t", question="cũ",
                                    ttl_hours=0)
    fresh = store.create_question(agent_id="a", task_id="t", question="mới")
    assert store.expire_due() == 1
    assert store.get(overdue).status == "expired"
    assert store.get(fresh).status == "pending"
    assert store.apply_answer(overdue, "muộn") is False  # expired can't be answered


# --- service ---


def test_ask_ceo_sanitizes_stores_and_notifies(wired, monkeypatch):
    sent = {}

    def _notify(text, *, dedup_hint, rationale, buttons=None):
        sent.update({"text": text, "buttons": buttons, "dedup": dedup_hint})
        return True

    monkeypatch.setattr(
        "src.runtime.operator_notify.notify_operator_best_effort", _notify
    )
    note, clarify_id = clarify_service.ask_ceo(
        agent_id="nghien-cuu", task_id="t1",
        question="Ưu tiên\x00 chi phí   hay tốc độ?", options=["Chi phí", "Tốc độ"],
    )
    assert "Đã gửi câu hỏi cho CEO" in note and clarify_id is not None
    assert "\x00" not in sent["text"] and "Ưu tiên chi phí hay tốc độ?" in sent["text"]
    assert [b["text"] for b in sent["buttons"]] == ["Chi phí", "Tốc độ"]
    assert sent["buttons"][0]["callback_data"].startswith("clarify:")


def test_ask_ceo_cap_returns_safe_note_never_raises(wired, monkeypatch):
    monkeypatch.setattr(
        "src.runtime.operator_notify.notify_operator_best_effort",
        lambda *a, **k: True,
    )
    for _ in range(MAX_PENDING_PER_AGENT):
        clarify_service.ask_ceo(agent_id="a", task_id="t", question="q")
    note, clarify_id = clarify_service.ask_ceo(agent_id="a", task_id="t", question="q-thừa")
    assert "an toàn" in note and clarify_id is None  # degraded note, not an exception


def test_answer_from_callback_landing_and_stale(wired, monkeypatch):
    monkeypatch.setattr(
        "src.runtime.operator_notify.notify_operator_best_effort",
        lambda *a, **k: True,
    )
    clarify_service.ask_ceo(agent_id="a", task_id="t", question="Chọn?",
                            options=["A", "B"])
    from src.runtime.clarify_store import ClarifyStore as _S
    from src.runtime.team_task_paths import clarify_db_path

    cid = _S(clarify_db_path()).list_pending()[0].id
    landed, toast = clarify_service.answer_from_callback(f"clarify:{cid}:1")
    assert landed is True and "B" in toast
    landed2, toast2 = clarify_service.answer_from_callback(f"clarify:{cid}:0")
    assert landed2 is False and "đã được trả lời" in toast2
    assert clarify_service.answer_from_callback("rác:1:2") == (False, "Nút không hợp lệ.")


def test_answered_context_renders_for_next_step(wired, monkeypatch):
    monkeypatch.setattr(
        "src.runtime.operator_notify.notify_operator_best_effort",
        lambda *a, **k: True,
    )
    clarify_service.ask_ceo(agent_id="a", task_id="t9", question="Ngân sách bao nhiêu?")
    from src.runtime.clarify_store import ClarifyStore as _S
    from src.runtime.team_task_paths import clarify_db_path

    s = _S(clarify_db_path())
    cid = s.list_pending()[0].id
    s.apply_answer(cid, "Tối đa 5 triệu")
    s.close()
    ctx = clarify_service.answered_context_for_task("t9")
    assert "Ngân sách bao nhiêu?" in ctx and "Tối đa 5 triệu" in ctx
    assert clarify_service.answered_context_for_task("t-khac") == ""


# --- telegram read: callback parse + allowlist ---


def test_fetch_new_updates_splits_messages_and_callbacks(monkeypatch):
    from src.config.telegram_config import TelegramConfig
    from src.tools import telegram_read

    updates = [
        {"update_id": 10, "message": {"text": "hi", "message_id": 1,
                                      "chat": {"id": 555, "type": "private"},
                                      "from": {"id": 9}}},
        {"update_id": 11, "callback_query": {"id": "cbq1", "data": "clarify:3:0",
                                             "from": {"id": 9},
                                             "message": {"chat": {"id": 555}}}},
        # non-allowlisted chat: both kinds must drop
        {"update_id": 12, "callback_query": {"id": "cbq2", "data": "clarify:3:1",
                                             "from": {"id": 1},
                                             "message": {"chat": {"id": 666}}}},
    ]
    monkeypatch.setattr(telegram_read, "resolve_bot_token", lambda t: "tok")
    monkeypatch.setattr(telegram_read, "api_call", lambda *a, **k: updates)
    telegram = TelegramConfig(bot_token_env="X", chat_ids=("555",))

    messages, callbacks, next_offset = telegram_read.fetch_new_updates(
        telegram, offset=None)
    assert [m["text"] for m in messages] == ["hi"]
    assert [c["data"] for c in callbacks] == ["clarify:3:0"]
    assert callbacks[0]["callback_query_id"] == "cbq1"
    assert next_offset == 13


# --- telegram inbox: callback identity gate (review M2) ---


def test_callback_from_non_operator_user_is_ignored(monkeypatch):
    from types import SimpleNamespace

    from src.runtime.telegram_inbox import _handle_callback

    applied = []
    monkeypatch.setattr(
        "src.runtime.clarify_service.answer_from_callback",
        lambda data: applied.append(data) or (True, "ok"),
    )
    telegram = SimpleNamespace(ops_operator_id="111", bot_token_env="X")
    # wrong user in an allowlisted chat: ignored entirely (no store call, no ack)
    _handle_callback(telegram, {"data": "clarify:1:0", "user": "999",
                                "channel": "111", "callback_query_id": "cb"})
    assert applied == []
    # the operator's own tap goes through (ack failure is swallowed by design)
    _handle_callback(telegram, {"data": "clarify:1:0", "user": "111",
                                "channel": "111", "callback_query_id": ""})
    assert applied == ["clarify:1:0"]
    # no operator configured: only the user's own DM (chat id == user id) counts
    telegram_dm = SimpleNamespace(ops_operator_id="", bot_token_env="X")
    _handle_callback(telegram_dm, {"data": "clarify:2:0", "user": "5", "channel": "77",
                                   "callback_query_id": ""})
    assert applied == ["clarify:1:0"]
    _handle_callback(telegram_dm, {"data": "clarify:2:0", "user": "77", "channel": "77",
                                   "callback_query_id": ""})
    assert applied == ["clarify:1:0", "clarify:2:0"]


# --- work node "ceo" branch ---


def test_work_node_routes_ceo_proposal_to_ask_ceo():
    from src.agent.team_task_graph import TeamTaskDeps, build_team_task_graph

    asked = {}
    colleague_calls = []

    deps = TeamTaskDeps(
        read_handoff=lambda: "bối cảnh",
        run_work=lambda title, handoff, hook: (f"KQ|{handoff}", 0.01),
        run_self_check=lambda text, criteria: (True, [], 1.0),
        run_rework=lambda b, p, f: ("", None),
        deliver_step=lambda text, version, flag: (True, "msg"),
        ask_colleague=lambda a, q: colleague_calls.append((a, q)) or ("trả lời", 0.0),
        propose_consults=lambda title, handoff: [
            ("ceo", "Ưu tiên gì?", ["Chi phí", "Tốc độ"]),
        ],
        ask_ceo=lambda q, opts: asked.update({"q": q, "opts": opts}) or
        ("Đã gửi câu hỏi cho CEO (mã #7).", None),
        set_attempt_id=lambda a: None,
    )
    out = build_team_task_graph(deps=deps).invoke({"step_title": "Bước"})
    assert asked == {"q": "Ưu tiên gì?", "opts": ["Chi phí", "Tốc độ"]}
    assert colleague_calls == []  # the ceo target never hits ask_colleague
    assert any("Hỏi CEO" in line for line in out["consult_log"])
    assert "Đã gửi câu hỏi cho CEO" in out["result_text"]  # folded into handoff


# --- web routes ---


def test_routes_pending_and_answer(wired, monkeypatch):
    monkeypatch.setattr(
        "src.runtime.operator_notify.notify_operator_best_effort",
        lambda *a, **k: True,
    )
    clarify_service.ask_ceo(agent_id="a", task_id="t", question="Chọn?",
                            options=["A", "B"])
    from src.server.app import create_app

    client = TestClient(create_app())
    qs = client.get("/api/clarify/pending").json()["questions"]
    assert len(qs) == 1 and qs[0]["options"] == ["A", "B"]

    cid = qs[0]["id"]
    r = client.post(f"/api/clarify/{cid}/answer", json={"answer": "A"})
    assert r.status_code == 200
    # double answer → 409; blank → 400
    assert client.post(f"/api/clarify/{cid}/answer", json={"answer": "B"}).status_code == 409
    assert client.post(f"/api/clarify/{cid}/answer", json={"answer": " "}).status_code == 400
    assert client.get("/api/clarify/pending").json()["questions"] == []
