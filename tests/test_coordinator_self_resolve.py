"""The coordinator's answer to a step nobody else could finish.

The crew's rule: the agent that hands out work decides the next step when a result is
missing or wrong — do it itself, route around it, or conclude — and every task ends
with a delivered conclusion. These tests drive `run_one_tick` with a fake
`self_do_step` and read the store + artifact the way the aggregate and the office
room would.
"""

from __future__ import annotations

import pytest

from my_crew.agent.coordinator_graph import run_one_tick
from my_crew.agent.coordinator_nodes.self_resolve import (
    COORDINATOR_FALLBACK_KEY,
    SELF_DO_VERSION,
)
from my_crew.agent.coordinator_nodes.stall_conclusion import FAILED_MARKER
from my_crew.agent.team_task_artifact import read_step_artifact, write_step_artifact
from my_crew.runtime.team_task_steps import is_dropped_step
from tests.test_coordinator_graph import _deps, _plan, _store


@pytest.fixture(autouse=True)
def _isolated_team_tasks_root(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)


_ONE_STEP = [{"step_id": "s1", "title": "draft", "assigned_to": "agent-a", "deps": []}]


def _dead_single_step(store):
    _plan(store, steps=_ONE_STEP)
    store.reserve_step("t1", "s1")
    store.mark_failed("t1", "s1")


# --- self-do: the coordinator writes the step ----------------------------------------


def test_a_dead_terminal_step_is_done_by_the_coordinator(tmp_path):
    store = _store(tmp_path)
    _dead_single_step(store)
    handoffs = []
    escalated = []

    def _self_do(task, step, handoff):
        handoffs.append((task.id, step.step_id, handoff))
        return "kết quả điều phối viết", 0.02

    deps = _deps(
        store, self_do_step=_self_do,
        escalate=lambda task, step, kind, msg: escalated.append((kind, msg)),
    )
    result = run_one_tick(deps)

    assert result.action == "self_did"
    assert store.get("t1").status == "open"  # the task lives on
    step = store.get_step("t1", "s1")
    assert step.status == "done"
    assert step.needs_review is False
    assert step.attempt_id is not None, "the lease stays: this is real content, not a drop"
    assert step.outcome_ref == "team-tasks/t1/step-1.json"
    assert step.cost_usd == pytest.approx(0.02)
    assert store.get("t1").cost_usd_total == pytest.approx(0.02)

    artifact = read_step_artifact(tmp_path, "t1", 1)
    assert artifact["result_text"] == "kết quả điều phối viết"
    assert artifact["status"] == "done"
    assert artifact["version"] == step.attempt_id
    assert artifact[COORDINATOR_FALLBACK_KEY]
    assert [k for k, _ in escalated] == ["stuck"]
    assert "Điều phối tự làm bước 'draft'" in escalated[0][1]

    # The handoff carried the CEO's brief and the acceptance criteria.
    _, _, handoff = handoffs[0]
    assert "lam demo" in handoff
    assert "VAI TRÒ: bạn là điều phối viên" in handoff


def test_after_self_do_the_next_tick_aggregates_and_delivers(tmp_path):
    store = _store(tmp_path)
    _dead_single_step(store)
    deps = _deps(store, self_do_step=lambda task, step, handoff: ("kết quả", None))

    assert run_one_tick(deps).action == "self_did"
    second = run_one_tick(deps)
    assert second.action == "aggregated"
    task = store.get("t1")
    assert task.status == "done"
    assert task.delivery_status == "delivered"
    assert task.final_summary == "done summary"


def test_self_do_handoff_carries_the_failed_attempts_draft_and_findings(tmp_path):
    """A `needs_decision` row left a real artifact behind: the coordinator starts from
    that draft and is told exactly what it failed on."""
    store = _store(tmp_path)
    _plan(store, steps=_ONE_STEP)
    store.reserve_step("t1", "s1")
    write_step_artifact(tmp_path, "t1", 1, {
        "status": "done", "result_text": "bản nháp cũ của agent-a",
        "failures": ["thiếu nguồn cho bảng giá"],
    })
    store.mark_failed("t1", "s1")
    handoffs = []
    deps = _deps(store, self_do_step=lambda t, s, h: handoffs.append(h) or ("mới", 0.0))

    assert run_one_tick(deps).action == "self_did"
    assert "bản nháp cũ của agent-a" in handoffs[0]
    assert "thiếu nguồn cho bảng giá" in handoffs[0]


def test_a_row_without_a_lease_gets_the_coordinator_version_stamp(tmp_path):
    store = _store(tmp_path)
    _plan(store, steps=_ONE_STEP)
    store.reserve_step("t1", "s1")
    store.mark_failed("t1", "s1")
    store._conn.execute("UPDATE team_steps SET attempt_id = NULL WHERE step_id = 's1'")
    store._conn.commit()
    deps = _deps(store, self_do_step=lambda t, s, h: ("kết quả", None))

    assert run_one_tick(deps).action == "self_did"
    assert read_step_artifact(tmp_path, "t1", 1)["version"] == SELF_DO_VERSION


# --- guards: when the coordinator must NOT substitute itself -----------------------------


def test_a_task_under_ceo_approval_never_lets_the_coordinator_do_work(tmp_path):
    store = _store(tmp_path)
    _dead_single_step(store)
    store.set_require_ceo_approval("t1", True)
    called = []
    deps = _deps(store, self_do_step=lambda t, s, h: called.append(1) or ("x", None))

    result = run_one_tick(deps)

    assert called == []
    assert result.action == "stalled"
    assert store.get("t1").status == "stalled"


def test_a_review_row_is_never_self_done(tmp_path):
    store = _store(tmp_path)
    _plan(store, steps=_ONE_STEP)
    store.reserve_step("t1", "s1")
    store.mark_done("t1", "s1", outcome_ref="team-tasks/t1/step-1.json", cost_usd=0.01)
    write_step_artifact(tmp_path, "t1", 1, {"status": "done", "result_text": "bài"})
    store.insert_step("t1", {"step_id": "r1", "title": "soát draft", "assigned_to": "agent-b",
                             "deps": ["s1"], "step_type": "review"})
    store.reserve_step("t1", "r1")
    store.mark_failed("t1", "r1")
    called = []
    deps = _deps(store, self_do_step=lambda t, s, h: called.append(s.step_id) or ("x", None))

    run_one_tick(deps)

    assert called == []


# --- the ladder below self-do -----------------------------------------------------------


@pytest.mark.parametrize("outcome", [None, ("", None)], ids=["declined", "blank"])
def test_when_the_coordinator_cannot_write_the_task_concludes_with_a_delivered_summary(
    tmp_path, outcome,
):
    store = _store(tmp_path)
    _dead_single_step(store)
    delivered = []
    deps = _deps(
        store, self_do_step=lambda t, s, h: outcome,
        deliver_room=lambda task, summary: delivered.append(summary),
    )
    result = run_one_tick(deps)

    assert result.action == "stalled"
    task = store.get("t1")
    assert task.status == "stalled"
    assert task.final_summary.startswith(f"Việc 'demo task' {FAILED_MARKER}")
    assert task.delivery_status == "delivered"
    assert delivered == [task.final_summary]


def test_a_self_do_that_raises_is_not_a_crash(tmp_path):
    store = _store(tmp_path)
    _dead_single_step(store)

    def _boom(task, step, handoff):
        raise RuntimeError("model down")

    result = run_one_tick(_deps(store, self_do_step=_boom))
    assert result.action == "stalled"
    assert store.get("t1").final_summary


def test_a_non_terminal_dead_step_is_skipped_with_a_gap_when_self_do_declines(tmp_path):
    store = _store(tmp_path)
    _plan(store)  # s1 draft -> s2 review (work step consuming s1)
    store.reserve_step("t1", "s1")
    store.mark_failed("t1", "s1")

    result = run_one_tick(_deps(store, self_do_step=lambda t, s, h: None))

    assert result.action == "step_skipped"
    assert store.get("t1").status == "open"
    assert is_dropped_step(store.get_step("t1", "s1"))


# --- policy stops still conclude ----------------------------------------------------------


def test_cost_cap_stop_delivers_a_conclusion(tmp_path):
    store = _store(tmp_path)
    _plan(store, steps=_ONE_STEP)
    store.reserve_step("t1", "s1")
    store.mark_done("t1", "s1", cost_usd=5.0)
    delivered = []

    result = run_one_tick(_deps(
        store, cost_cap_usd=2.0, deliver_room=lambda task, summary: delivered.append(summary),
    ))

    assert result.action == "cap_exceeded"
    task = store.get("t1")
    assert task.final_summary and "vượt trần chi phí" in task.final_summary
    assert task.delivery_status == "delivered"
    assert delivered == [task.final_summary]


def test_plan_hash_stop_delivers_a_conclusion(tmp_path):
    store = _store(tmp_path)
    _plan(store)
    store._conn.execute("UPDATE team_tasks SET plan_hash = 'tampered' WHERE id = 't1'")
    store._conn.commit()
    delivered = []

    result = run_one_tick(_deps(store, deliver_room=lambda task, s: delivered.append(s)))

    assert result.action == "stalled"
    task = store.get("t1")
    assert task.final_summary and "không khớp kế hoạch" in task.final_summary
    assert task.delivery_status == "delivered"
    assert len(delivered) == 1


def test_a_failed_room_delivery_leaves_the_summary_retryable(tmp_path):
    store = _store(tmp_path)
    _dead_single_step(store)

    result = run_one_tick(_deps(store, deliver_room=lambda task, s: False))

    assert result.action == "stalled"
    task = store.get("t1")
    assert task.final_summary
    assert task.delivery_status == "failed"
