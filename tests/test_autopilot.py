"""v63 autopilot — the secretary decides in the CEO's place (explicit CEO decision
2026-08-04, "Toàn quyền thật"). Pins the four load-bearing behaviors:

- the `company.yaml` flag round-trips and defaults OFF;
- the ticker auto-approves a PENDING Lớp B row ONLY when autopilot is on AND the task
  did not opt out (`require_ceo_approval`);
- the stall sweep walks the bounded retry → accept/drop ladder and stops at its cap;
- Lớp A hard-denies are UNAFFECTED by the flag (autopilot never reaches them).
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from my_crew.agent.coordinator_graph import CoordinatorDeps, in_memory_retry_tracker, run_one_tick
from my_crew.runtime.company import Company, load_company, save_company
from my_crew.runtime.team_task_store import TeamTaskStore


@pytest.fixture(autouse=True)
def _isolated_team_tasks_root(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    return tmp_path


def _open_store(tmp_path) -> TeamTaskStore:
    from my_crew.runtime.team_task_paths import team_tasks_db_path

    return TeamTaskStore(team_tasks_db_path())


def _content_hash(steps: list[dict]) -> str:
    from my_crew.agent.task_decomposition import decomposition_content_hash

    return decomposition_content_hash(SimpleNamespace(steps=[
        SimpleNamespace(step_id=s["step_id"], title=s["title"],
                        assigned_to=s["assigned_to"], deps=tuple(s.get("deps", ())))
        for s in steps
    ]))


# --- company flag ---------------------------------------------------------------------


def test_company_autopilot_defaults_false_and_round_trips(tmp_path):
    path = tmp_path / "company.yaml"
    save_company("Cty", "coordinator", 2.0, path=path)
    assert load_company(path).autopilot is False
    save_company("Cty", "coordinator", 2.0, autopilot=True, path=path)
    assert load_company(path).autopilot is True


def test_missing_company_file_means_autopilot_off(tmp_path):
    assert load_company(tmp_path / "ghost.yaml").autopilot is False


# --- ticker Lớp B auto-approve --------------------------------------------------------


def _awaiting_approval_fixture(tmp_path, *, require_ceo_approval=False):
    store = _open_store(tmp_path)
    steps = [{"step_id": "s1", "title": "gửi email", "assigned_to": "agent-a", "deps": []}]
    store.create_task(task_id="t1", title="demo", original_request="x", assigned_by="ceo")
    store.set_plan("t1", steps, _content_hash(steps))
    if require_ceo_approval:
        store.set_require_ceo_approval("t1", True)
    attempt = store.reserve_step("t1", "s1")
    store.mark_awaiting_approval("t1", "s1", attempt_id=attempt, approval_id=77)
    return store


def _deps(store, **overrides) -> CoordinatorDeps:
    base = dict(
        store=store, retry_tracker=in_memory_retry_tracker(), cost_cap_usd=2.0,
        spawn_step=lambda task, step, attempt_id: 4242,
        pid_alive=lambda pid: True, kill_pid=lambda pid, attempt_id: None,
        aggregate=lambda task: ("ok", None), deliver_room=lambda task, summary: None,
        escalate=lambda task, step, kind, msg: None,
        now=lambda: datetime.now(UTC),
    )
    base.update(overrides)
    return CoordinatorDeps(**base)


def test_autopilot_approves_a_pending_lop_b_gate_and_respawns(tmp_path):
    store = _awaiting_approval_fixture(tmp_path)
    approved: list[int] = []
    statuses = {77: "pending"}

    def _approve(approval_id: int, agent_id: str) -> bool:
        approved.append((approval_id, agent_id))
        statuses[approval_id] = "approved"
        return True

    try:
        result = run_one_tick(_deps(
            store,
            approval_status=lambda aid, agent: statuses.get(aid),
            approval_approve=_approve,
            autopilot_enabled=lambda: True,
        ))
        assert approved == [(77, "agent-a")]  # scoped to the step's own agent store
        assert result.action == "spawned"
    finally:
        store.close()


def test_opted_out_task_is_never_auto_approved(tmp_path):
    store = _awaiting_approval_fixture(tmp_path, require_ceo_approval=True)
    approved: list[int] = []
    try:
        result = run_one_tick(_deps(
            store,
            approval_status=lambda aid, agent: "pending",
            approval_approve=lambda aid, agent: approved.append(aid) or True,
            autopilot_enabled=lambda: True,
        ))
        assert approved == []
        assert result.action == "none"
        assert store.get_step("t1", "s1").status == "awaiting_approval"
    finally:
        store.close()


def test_autopilot_off_leaves_pending_gate_alone(tmp_path):
    store = _awaiting_approval_fixture(tmp_path)
    approved: list[int] = []
    try:
        result = run_one_tick(_deps(
            store,
            approval_status=lambda aid, agent: "pending",
            approval_approve=lambda aid, agent: approved.append(aid) or True,
        ))
        assert approved == []
        assert result.action == "none"
    finally:
        store.close()


# --- stall sweep ladder ---------------------------------------------------------------


def _autopilot_company(monkeypatch, enabled=True):
    company = Company(name="Cty", coordinator_id="coordinator", team_task_cap_usd=2.0,
                      autopilot=enabled)
    import my_crew.runtime.company as company_mod

    monkeypatch.setattr(company_mod, "load_company", lambda path=None: company)


def _mk_review_stalled(tmp_path, task_id="t1"):
    from my_crew.agent.team_task_artifact import (
        write_review_verdict_artifact,
        write_step_artifact,
    )

    store = _open_store(tmp_path)
    try:
        store.create_task(task_id=task_id, title="Demo", original_request="x",
                          assigned_by="ceo")
        steps = [{"step_id": "s1", "title": "draft", "assigned_to": "agent-a",
                  "deps": [], "needs_review": True}]
        store.set_plan(task_id, steps, _content_hash(steps))
        attempt = store.reserve_step(task_id, "s1")
        store.mark_done(task_id, "s1", attempt_id=attempt)
        store.insert_step(task_id, {
            "step_id": "s1-review-2-2", "title": "Soát chéo: draft", "assigned_to": "agent-b",
            "deps": ["s1"], "step_type": "review", "parent_step_id": "s1", "review_round": 2,
        })
        r_attempt = store.reserve_step(task_id, "s1-review-2-2")
        store.mark_done(task_id, "s1-review-2-2", attempt_id=r_attempt)
        store.set_task_status(task_id, "stalled")
    finally:
        store.close()
    write_step_artifact(tmp_path, task_id, 1, {"result_text": "nháp", "version": attempt})
    write_review_verdict_artifact(
        tmp_path, task_id, 1, 2,
        {"passed": False, "failures": ["thiếu số liệu"], "notes": [],
         "reviewed_version": attempt, "round": 2, "result_text": "nháp"},
    )


def test_sweep_rung1_retries_then_rung2_accepts_then_stops(tmp_path, monkeypatch):
    from my_crew.agent.team_task_artifact import read_review_verdict_artifact
    from my_crew.runtime.autopilot_sweep import run_autopilot_sweep

    _autopilot_company(monkeypatch)
    _mk_review_stalled(tmp_path)
    store = _open_store(tmp_path)
    try:
        # Rung 1: retry — one extra rework round, task reopened.
        assert run_autopilot_sweep(store) == 1
        task = store.get("t1")
        assert task.status == "open"
        assert task.autopilot_attempts == 1
        assert any(s.step_id == "s1-rework-2" for s in task.steps)

        # Task stalls again (simulated) — rung 2: accept the deliverable.
        store.set_task_status("t1", "stalled")
        assert run_autopilot_sweep(store) == 1
        task = store.get("t1")
        assert task.status == "open"
        assert task.autopilot_attempts == 2
        assert read_review_verdict_artifact(tmp_path, "t1", 1, 2)["passed"] is True

        # Ladder exhausted: a third stall stays with the CEO.
        store.set_task_status("t1", "stalled")
        assert run_autopilot_sweep(store) == 0
        assert store.get("t1").status == "stalled"
    finally:
        store.close()


def test_sweep_skips_opted_out_tasks_and_is_noop_when_off(tmp_path, monkeypatch):
    from my_crew.runtime.autopilot_sweep import run_autopilot_sweep

    _mk_review_stalled(tmp_path)
    store = _open_store(tmp_path)
    try:
        _autopilot_company(monkeypatch, enabled=False)
        assert run_autopilot_sweep(store) == 0

        _autopilot_company(monkeypatch, enabled=True)
        store.set_require_ceo_approval("t1", True)
        assert run_autopilot_sweep(store) == 0
        assert store.get("t1").status == "stalled"
    finally:
        store.close()


# --- per-task opt-out phrase + Lớp A invariant ----------------------------------------


def test_brief_opt_out_phrases_detected():
    from my_crew.agent.ops_autopilot import brief_opts_out

    assert brief_opts_out("Soạn báo cáo quý, vụ này để anh duyệt nhé")
    assert brief_opts_out("lam ke hoach, can ceo duyet")
    assert not brief_opts_out("Soạn báo cáo quý cho đội sales")


def test_lop_a_hard_deny_ignores_the_autopilot_flag(monkeypatch):
    """Autopilot must never reach Lớp A: `hard_block.classify` takes no company/flag
    input at all — a DATA_LOSS argv is denied identically with the flag on. This test
    pins the invariant the CEO's full-delegation decision was accepted under."""
    import my_crew.runtime.company as company_mod
    from my_crew.actions.hard_block import classify

    monkeypatch.setattr(
        company_mod, "load_company",
        lambda path=None: Company(name="", coordinator_id=None, team_task_cap_usd=2.0,
                                  autopilot=True),
    )
    action = {"type": "gws_write",
              "argv": ["gmail", "users", "messages", "delete", "--params", "{}"],
              "dedup_hint": "x"}
    assert classify(action).blocked
