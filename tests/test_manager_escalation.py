"""`manager_escalation.escalate_to_manager` (v94 P3, decision D7): mints a single-step
team task for the company's Manager agent, with 3 brakes — roster-assignable check,
daily cap, and an `origin=escalation` recursion guard on `route_json`.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import my_crew.agent.team_task_roster as roster_mod
import my_crew.runtime.manager_escalation as escalation_mod
from my_crew.runtime.manager_escalation import (
    escalate_to_manager,
    is_escalation_origin,
    resolve_manager_id,
)
from my_crew.runtime.team_task_store import TeamTaskStore


@pytest.fixture(autouse=True)
def _isolated_team_tasks_root(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)


def _store():
    from my_crew.runtime.team_task_paths import team_tasks_db_path

    return TeamTaskStore(team_tasks_db_path())


def _company(**overrides):
    defaults = dict(manager_id=None, coordinator_id=None, escalation_daily_cap=20)
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _allow_manager(monkeypatch, manager_id: str) -> None:
    """Make `is_assignable(manager_id)` True — real roster wiring is
    `test_team_task_roster.py`'s concern; here we only need the boolean."""
    monkeypatch.setattr(roster_mod, "is_assignable", lambda agent_id: agent_id == manager_id)


# --- resolve_manager_id -------------------------------------------------------------


def test_resolve_manager_id_prefers_manager_id():
    assert resolve_manager_id(_company(manager_id="mgr-1", coordinator_id="coord-1")) == "mgr-1"


def test_resolve_manager_id_falls_back_to_coordinator():
    assert resolve_manager_id(_company(manager_id=None, coordinator_id="coord-1")) == "coord-1"


def test_resolve_manager_id_falls_back_to_admin():
    assert resolve_manager_id(_company(manager_id=None, coordinator_id=None)) == "admin"


def test_resolve_manager_id_ignores_blank_strings():
    assert resolve_manager_id(_company(manager_id="  ", coordinator_id="coord-1")) == "coord-1"


# --- is_escalation_origin -------------------------------------------------------------


def test_is_escalation_origin_true_only_for_the_marker():
    assert is_escalation_origin({"origin": "escalation", "source": "x"}) is True
    assert is_escalation_origin({"origin": "team_router"}) is False
    assert is_escalation_origin(None) is False
    assert is_escalation_origin({}) is False


# --- escalate_to_manager: happy path --------------------------------------------------


def test_mints_a_single_step_task_pic_manager(monkeypatch):
    _allow_manager(monkeypatch, "mgr-1")
    company = _company(manager_id="mgr-1")

    task_id = escalate_to_manager(
        source="customer_assistant", summary="khách hỏi giá gói cao cấp",
        context_ref="cust-42", company=company,
    )

    assert task_id is not None
    store = _store()
    try:
        task = store.get(task_id)
    finally:
        store.close()
    assert task is not None
    assert task.pic_id == "mgr-1"
    assert len(task.steps) == 1
    assert task.steps[0].assigned_to == "mgr-1"
    assert task.steps[0].deps == ()
    assert task.status == "open"  # set_plan moves it out of `planning`


def test_mint_stamps_origin_and_source_on_route_json(monkeypatch):
    _allow_manager(monkeypatch, "mgr-1")
    company = _company(manager_id="mgr-1")

    task_id = escalate_to_manager(
        source="customer_assistant", summary="test", context_ref="ref-1", company=company,
    )

    store = _store()
    try:
        route = store.get_route(task_id)
    finally:
        store.close()
    assert route == {"origin": "escalation", "source": "customer_assistant",
                      "context_ref": "ref-1"}


def test_mint_uses_a_real_content_hash_matching_the_ticker_recompute(monkeypatch):
    """A random token here would stall the task on tick one — same failure class
    `watcher_runner._wake_via_team_task`'s docstring calls out."""
    _allow_manager(monkeypatch, "mgr-1")
    company = _company(manager_id="mgr-1")

    task_id = escalate_to_manager(source="x", summary="y", company=company)

    from my_crew.agent.task_decomposition import decomposition_content_hash

    store = _store()
    try:
        task = store.get(task_id)
    finally:
        store.close()
    recomputed = decomposition_content_hash(
        SimpleNamespace(steps=[
            SimpleNamespace(step_id=s.step_id, title=s.title, assigned_to=s.assigned_to,
                            deps=s.deps, needs_shell=False, external_write=False,
                            needs_web=False)
            for s in task.steps
        ])
    )
    assert task.plan_hash == recomputed


# --- brake 1: roster-assignable ------------------------------------------------------


def test_falls_back_when_resolved_manager_is_not_roster_assignable(monkeypatch):
    monkeypatch.setattr(roster_mod, "is_assignable", lambda _agent_id: False)
    company = _company(manager_id=None, coordinator_id=None)  # resolves to "admin"

    result = escalate_to_manager(source="customer_assistant", summary="x", company=company)

    assert result is None


def test_falls_back_when_no_manager_id_configured_default_admin_excluded(monkeypatch):
    """Rollback contract: an unconfigured fleet (no `manager_id`) must degrade to the
    pre-P3 human-notify path — `is_assignable("admin")` is False by roster design."""
    monkeypatch.setattr(roster_mod, "is_assignable", lambda agent_id: agent_id != "admin")
    company = _company(manager_id=None, coordinator_id=None)

    result = escalate_to_manager(source="customer_assistant", summary="x", company=company)

    assert result is None


# --- brake 2: daily cap ---------------------------------------------------------------


def test_cap_refuses_the_mint_past_the_configured_limit(monkeypatch, tmp_path):
    _allow_manager(monkeypatch, "mgr-1")
    company = _company(manager_id="mgr-1", escalation_daily_cap=2)
    sidecar = tmp_path / "cap.json"

    ids = [
        escalate_to_manager(source="s", summary=f"m{i}", company=company,
                            sidecar_path=sidecar)
        for i in range(3)
    ]

    assert ids[0] is not None
    assert ids[1] is not None
    assert ids[2] is None  # the 3rd (over a cap of 2) falls back


def test_cap_of_zero_refuses_every_mint(monkeypatch, tmp_path):
    """`escalation_daily_cap: 0` is the operator's "stop the storm" knob — it must mean
    REFUSE EVERY mint today, not "unlimited" (the inverted, pre-fix behavior)."""
    _allow_manager(monkeypatch, "mgr-1")
    company = _company(manager_id="mgr-1", escalation_daily_cap=0)
    sidecar = tmp_path / "cap.json"

    ids = [
        escalate_to_manager(source="s", summary=f"m{i}", company=company,
                            sidecar_path=sidecar)
        for i in range(3)
    ]

    assert all(i is None for i in ids)


def test_cap_of_none_falls_back_to_the_default_cap(monkeypatch, tmp_path):
    """No `escalation_daily_cap` configured (None) uses the documented default, not
    unlimited — matches `load_company`'s own default-on-missing behavior."""
    from my_crew.runtime.company import DEFAULT_ESCALATION_DAILY_CAP

    _allow_manager(monkeypatch, "mgr-1")
    company = _company(manager_id="mgr-1", escalation_daily_cap=None)
    sidecar = tmp_path / "cap.json"

    ids = [
        escalate_to_manager(source="s", summary=f"m{i}", company=company,
                            sidecar_path=sidecar)
        for i in range(DEFAULT_ESCALATION_DAILY_CAP + 1)
    ]

    assert all(i is not None for i in ids[:DEFAULT_ESCALATION_DAILY_CAP])
    assert ids[DEFAULT_ESCALATION_DAILY_CAP] is None


def test_cap_counter_survives_a_corrupt_sidecar_file(monkeypatch, tmp_path):
    _allow_manager(monkeypatch, "mgr-1")
    company = _company(manager_id="mgr-1", escalation_daily_cap=5)
    sidecar = tmp_path / "cap.json"
    sidecar.write_text("{not json", encoding="utf-8")

    result = escalate_to_manager(source="s", summary="m", company=company,
                                 sidecar_path=sidecar)

    assert result is not None


# --- brake 3: recursion guard ---------------------------------------------------------


def test_refuses_to_mint_from_an_already_escalated_origin(monkeypatch):
    _allow_manager(monkeypatch, "mgr-1")
    company = _company(manager_id="mgr-1")

    result = escalate_to_manager(
        source="customer_assistant", summary="x", company=company,
        origin_route={"origin": "escalation", "source": "customer_assistant"},
    )

    assert result is None


def test_a_non_escalation_origin_route_does_not_block_the_mint(monkeypatch):
    _allow_manager(monkeypatch, "mgr-1")
    company = _company(manager_id="mgr-1")

    result = escalate_to_manager(
        source="customer_assistant", summary="x", company=company,
        origin_route={"origin": "team_router", "mode": "sprint"},
    )

    assert result is not None


# --- degrade-not-raise -----------------------------------------------------------------


def test_store_failure_degrades_to_none_instead_of_raising(monkeypatch):
    _allow_manager(monkeypatch, "mgr-1")
    company = _company(manager_id="mgr-1")

    class _BoomStore:
        def __init__(self, *_a, **_kw):
            raise RuntimeError("db locked")

    monkeypatch.setattr(escalation_mod, "TeamTaskStore", _BoomStore, raising=False)
    import my_crew.runtime.team_task_store as store_mod

    monkeypatch.setattr(store_mod, "TeamTaskStore", _BoomStore)

    result = escalate_to_manager(source="s", summary="m", company=company)

    assert result is None


def test_roster_check_exception_degrades_to_none(monkeypatch):
    def _boom(_agent_id):
        raise RuntimeError("registry unreadable")

    monkeypatch.setattr(roster_mod, "is_assignable", _boom)
    company = _company(manager_id="mgr-1")

    result = escalate_to_manager(source="s", summary="m", company=company)

    assert result is None


def test_loads_company_when_none_is_passed(monkeypatch):
    _allow_manager(monkeypatch, "mgr-1")
    monkeypatch.setattr(
        "my_crew.runtime.company.load_company", lambda: _company(manager_id="mgr-1"),
    )

    result = escalate_to_manager(source="s", summary="m")

    assert result is not None
