"""v15 red-team F2 + F7 pins.

F2: an amend on a PIC task must keep/re-establish the one-terminal-owned-by-PIC rule
over the NEW pending slice (frozen steps always look terminal — excluding them is what
makes a valid amend possible at all); a no-PIC task amends exactly as before.

F7: POST /api/company must not clobber fields it doesn't carry — the pre-v15 handler
reset `team_task_concurrency` to 2 on every save.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import my_crew.agent.team_task_amend_prompt as amend_mod


def _task(pic_id="", steps=()):
    return SimpleNamespace(steps=list(steps), pic_id=pic_id)


def _frozen(sid, who):
    return SimpleNamespace(step_id=sid, title=f"t-{sid}", assigned_to=who, deps=(),
                           status="done", system_inserted=0)


def _wire_llm(monkeypatch, new_steps):
    class _Result:
        cost_usd = 0.001
        content = json.dumps({"steps": new_steps, "requires_approval": True})

    class _Llm:
        def complete(self, messages):
            return _Result()

    monkeypatch.setattr(amend_mod, "_build_llm", lambda: (_Llm(), None))


STAFF = [("noi-dung", "office"), ("nghien-cuu", "office")]


def test_amend_pic_task_accepts_single_terminal_owned_by_pic(monkeypatch):
    _wire_llm(monkeypatch, [
        {"step_id": "n1", "title": "bổ sung", "assigned_to": "nghien-cuu", "deps": []},
        {"step_id": "n2", "title": "tổng hợp lại", "assigned_to": "noi-dung", "deps": ["n1"]},
    ])
    task = _task(pic_id="noi-dung", steps=[_frozen("s1", "noi-dung")])
    new_pending, combined, _cost = amend_mod.amend_with_retries(task, "thêm bước", STAFF)
    assert [s["step_id"] for s in new_pending] == ["n1", "n2"]


def test_amend_pic_task_rejects_terminal_not_owned_by_pic(monkeypatch):
    _wire_llm(monkeypatch, [
        {"step_id": "n1", "title": "bổ sung", "assigned_to": "noi-dung", "deps": []},
        {"step_id": "n2", "title": "chốt", "assigned_to": "nghien-cuu", "deps": ["n1"]},
    ])
    task = _task(pic_id="noi-dung", steps=[_frozen("s1", "noi-dung")])
    from my_crew.agent.task_decomposition import DecompositionError

    with pytest.raises(DecompositionError):
        amend_mod.amend_with_retries(task, "thêm bước", STAFF)


def test_amend_no_pic_task_unchanged_multiple_terminals_ok(monkeypatch):
    # two independent new steps (two terminals) — fine for a pre-v15 task without a PIC.
    _wire_llm(monkeypatch, [
        {"step_id": "n1", "title": "a", "assigned_to": "noi-dung", "deps": []},
        {"step_id": "n2", "title": "b", "assigned_to": "nghien-cuu", "deps": []},
    ])
    task = _task(pic_id="", steps=[_frozen("s1", "noi-dung")])
    new_pending, _combined, _cost = amend_mod.amend_with_retries(task, "thêm bước", STAFF)
    assert len(new_pending) == 2


def test_amend_prompt_carries_pic_line_only_for_pic_tasks():
    with_pic = amend_mod._build_amend_messages(
        task=_task(pic_id="noi-dung", steps=[_frozen("s1", "noi-dung")]),
        request="đổi hướng", staff=STAFF,
    )
    without_pic = amend_mod._build_amend_messages(
        task=_task(pic_id="", steps=[_frozen("s1", "noi-dung")]),
        request="đổi hướng", staff=STAFF,
    )
    assert "PIC: noi-dung" in with_pic[1]["content"]
    assert "PIC:" not in without_pic[1]["content"]


def test_post_company_preserves_concurrency_and_auto_confirm(tmp_path, monkeypatch):
    """F7: fields the request body does not carry survive a save round-trip."""
    from my_crew.runtime import company as company_mod
    from my_crew.runtime.company import load_company, save_company

    path = tmp_path / "company.yaml"
    monkeypatch.setattr(company_mod, "_COMPANY_PATH", path)
    save_company("Cty", None, 2.0, team_task_concurrency=4, team_task_auto_confirm=True)

    from my_crew.server.routes_company import post_company

    out = post_company(name="Cty mới", coordinator_id=None, team_task_cap_usd=3.0,
                       team_task_auto_confirm=None)
    assert out["team_task_concurrency"] == 4  # NOT reset to the default 2
    assert out["team_task_auto_confirm"] is True  # preserved when body omits it

    saved = load_company(path)
    assert saved.team_task_concurrency == 4
    assert saved.team_task_auto_confirm is True
    assert saved.team_task_cap_usd == 3.0
    assert saved.name == "Cty mới"
