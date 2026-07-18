"""v15 wiring: @PIC through `preview_assign_team_task` (store pic_id, preview text,
assignment event body) + the `team_task_auto_confirm` branch (Q1/F3/F9): on ⇒ the
previewed plan is confirmed immediately via the SAME hash-bind path, `auto_confirmed`
slot set (ops-chat then parks NO awaiting_confirm draft); auto-run failure cancels the
draft instead of orphaning it.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import my_crew.agent.ops_assign_team_task as mod
import my_crew.profile.loader as loader_mod
import my_crew.runtime.company as company_mod
import my_crew.runtime.registry as registry_mod
from my_crew.runtime.registry import RegistryEntry


@pytest.fixture(autouse=True)
def _isolated_team_tasks_root(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)


def _company(*, auto_confirm=False):
    return SimpleNamespace(
        name="", coordinator_id="coord-1", team_task_cap_usd=2.0,
        team_task_concurrency=2, team_task_auto_confirm=auto_confirm,
    )


def _wire(monkeypatch, *, auto_confirm=False):
    """Routable escalation (coordinator has telegram) + roster [noi-dung, nghien-cuu]
    + a canned LLM decompose that honors the pic prompt line."""
    monkeypatch.setattr(company_mod, "load_company", lambda: _company(auto_confirm=auto_confirm))
    telegram = SimpleNamespace(bot_token_env="X", chat_ids=("op",), poll_minutes=5,
                               ops_operator_id="op")

    def _load_profile(agent_id, *, data_dir):
        domain = {"coord-1": "pm", "noi-dung": "office", "nghien-cuu": "office"}[agent_id]
        return SimpleNamespace(domain=domain, config=SimpleNamespace(telegram=telegram),
                               soul="", project="", memory="")

    monkeypatch.setattr(loader_mod, "load_profile", _load_profile)
    monkeypatch.setattr(
        registry_mod, "load_registry",
        lambda: (RegistryEntry(id="coord-1", enabled=True),
                 RegistryEntry(id="noi-dung", enabled=True),
                 RegistryEntry(id="nghien-cuu", enabled=True)),
    )

    def _canned_llm():
        class _Result:
            cost_usd = 0.001
            content = json.dumps({
                "steps": [
                    {"step_id": "s1", "title": "thu thập", "assigned_to": "nghien-cuu",
                     "deps": []},
                    {"step_id": "s2", "title": "tổng hợp", "assigned_to": "noi-dung",
                     "deps": ["s1"]},
                ],
                "pic_id": "noi-dung",
                "requires_approval": True,
            })

        class _Llm:
            def complete(self, messages):
                return _Result()

        return _Llm(), None

    monkeypatch.setattr(mod, "_build_llm", _canned_llm)


def _store():
    from my_crew.runtime.team_task_paths import team_tasks_db_path
    from my_crew.runtime.team_task_store import TeamTaskStore

    return TeamTaskStore(team_tasks_db_path())


def test_at_pic_preview_persists_pic_and_renders_line(monkeypatch):
    _wire(monkeypatch)
    slots = {"brief": "@noi-dung viết bộ tài liệu ra mắt"}
    text = mod.preview_assign_team_task(slots)

    assert "PIC (chịu trách nhiệm chính): noi-dung" in text
    assert "xác nhận" in text.lower()  # still awaiting the CEO — flag off
    assert slots["pic_id"] == "noi-dung"
    store = _store()
    try:
        task = store.get(slots["task_id"])
        assert task.pic_id == "noi-dung"
        assert task.status == "planning"  # NOT dispatched yet
        # the @prefix is stripped from the title but kept in the original request
        assert not task.title.startswith("@")
        assert task.original_request.startswith("@noi-dung")
    finally:
        store.close()


def test_bad_at_pic_rejected_before_any_llm_call(monkeypatch):
    _wire(monkeypatch)

    def _boom():
        raise AssertionError("LLM must not be called for an invalid @pic")

    monkeypatch.setattr(mod, "_build_llm", _boom)
    with pytest.raises(ValueError, match="@ai-do không có trong danh sách"):
        mod.preview_assign_team_task({"brief": "@ai-do làm gì đó"})


def test_auto_confirm_on_dispatches_immediately_and_flags_slot(monkeypatch):
    _wire(monkeypatch, auto_confirm=True)
    slots = {"brief": "@noi-dung viết bộ tài liệu ra mắt"}
    text = mod.preview_assign_team_task(slots)

    assert "ĐÃ TỰ XÁC NHẬN" in text
    assert slots.get("auto_confirmed") == "1"
    store = _store()
    try:
        task = store.get(slots["task_id"])
        assert task.status == "open"  # dispatched without a manual confirm
        assert task.plan_hash == slots["plan_hash"]  # same hash-bind path
    finally:
        store.close()


def test_auto_confirm_failure_cancels_draft_not_orphans(monkeypatch):
    _wire(monkeypatch, auto_confirm=True)
    task_ids = []

    real_run = mod.run_assign_team_task

    def _failing_run(slots):
        task_ids.append(slots["task_id"])
        raise ValueError("giả lập confirm hỏng")

    monkeypatch.setattr(mod, "run_assign_team_task", _failing_run)
    with pytest.raises(ValueError, match="tự xác nhận thất bại"):
        mod.preview_assign_team_task({"brief": "@noi-dung viết tài liệu"})

    store = _store()
    try:
        task = store.get(task_ids[0])
        assert task.status == "cancelled"  # terminalized, never ticker-visible
    finally:
        store.close()
    assert real_run is not None  # silence unused warning


def test_assignment_event_carries_pic_and_task_id(monkeypatch):
    _wire(monkeypatch)
    slots = {"brief": "@noi-dung viết tài liệu"}
    mod.preview_assign_team_task(slots)
    mod.run_assign_team_task(slots)

    from my_crew.runtime.office_room_store import OfficeRoomStore, office_room_db_path
    from my_crew.runtime.team_task_paths import team_tasks_root

    store = OfficeRoomStore(office_room_db_path(team_tasks_root()))
    try:
        events = store.list("office")
    finally:
        store.close()
    assignment = next(e for e in events if e.kind == "assignment")
    assert assignment.body["pic"] == "noi-dung"
    assert assignment.body["task_id"] == slots["task_id"]
    assert assignment.body["summary"].startswith("PIC: noi-dung")
