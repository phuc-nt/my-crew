"""v34 P4 runtime fan-out — work-node split branch, ticker mint rule, readiness gate,
gather-result copy, review suppression. Mirrors the review-insert rule's guarantees.

Load-bearing:
- a split step never pays run_work/self_check; it delivers the notice directly.
- the ticker mints N subs (deps=[], needs_review=False) + 1 gather (deps=subs,
  inherits needs_review) exactly once; an invalid proposal is refused + consumed.
- a plan step depending on the split parent stays un-ready until every fan-out
  child is done; the gather's merged artifact replaces the parent's notice.
- plan-hash verify still passes with fan-out rows present (system_inserted).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from my_crew.agent.coordinator_graph import CoordinatorDeps, in_memory_retry_tracker, run_one_tick
from my_crew.agent.coordinator_nodes.fanout_insert import (
    MAX_TASK_STEPS,
    maybe_copy_gather_results,
    maybe_insert_fanout,
)
from my_crew.agent.coordinator_nodes.tick_actions import ready_pending_steps
from my_crew.agent.task_decomposition import decomposition_content_hash
from my_crew.agent.team_task_graph import TeamTaskDeps, build_team_task_graph
from my_crew.runtime.team_task_store import TeamTaskStore


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    from my_crew.runtime.team_task_paths import team_tasks_db_path

    s = TeamTaskStore(team_tasks_db_path())
    yield s
    s.close()


def _hash(steps):
    return decomposition_content_hash(SimpleNamespace(steps=[
        SimpleNamespace(step_id=s["step_id"], title=s["title"],
                        assigned_to=s["assigned_to"], deps=tuple(s.get("deps", ())))
        for s in steps
    ]))


_PLAN = [
    {"step_id": "s1", "title": "So sánh 3 nguồn", "assigned_to": "agent-a", "deps": [],
     "needs_review": True},
    {"step_id": "s2", "title": "Chốt báo cáo", "assigned_to": "agent-b", "deps": ["s1"]},
]


def _plan(store, task_id="t1"):
    store.create_task(task_id=task_id, title="demo", original_request="x")
    store.set_plan(task_id, _PLAN, plan_hash=_hash(_PLAN))


def _deps(store, **overrides) -> CoordinatorDeps:
    base = dict(
        store=store, retry_tracker=in_memory_retry_tracker(), cost_cap_usd=2.0,
        spawn_step=lambda task, step, attempt_id: 4242,
        pid_alive=lambda pid: True, kill_pid=lambda pid, attempt_id: None,
        roster_ok=lambda agent_id: agent_id in ("agent-a", "agent-b"),
        aggregate=lambda task: ("ok", 0.01), deliver_room=lambda task, summary: None,
        escalate=lambda task, step, kind, msg: None,
        now=lambda: datetime.now(UTC),
    )
    base.update(overrides)
    return CoordinatorDeps(**base)


_SPLIT = [{"title": "Nguồn A", "assigned_to": "agent-a"},
          {"title": "Nguồn B", "assigned_to": "agent-b"}]


def _finish_s1_with_split(store, split=None):
    store._conn.execute(
        "UPDATE team_steps SET status='done', split_proposal_json=? "
        "WHERE task_id='t1' AND step_id='s1'",
        (json.dumps(split if split is not None else _SPLIT, ensure_ascii=False),),
    )
    store._conn.commit()


# --- work node -----------------------------------------------------------------


def test_work_node_split_skips_work_and_selfcheck():
    work_calls, check_calls, delivered = [], [], []
    deps = TeamTaskDeps(
        read_handoff=lambda: "",
        run_work=lambda t, h, hook: (work_calls.append(t) or ("KQ", 0.01)),
        run_self_check=lambda text, acc: (check_calls.append(text) or (True, [], 1.0)),
        run_rework=lambda b, p, f: ("", None),
        deliver_step=lambda text, version, flag: (delivered.append(text) or (True, "ok")),
        ask_colleague=lambda a, q: ("", 0.0),
        propose_consults=lambda t, h: [],
        take_split=lambda: [{"title": "Phần 1", "assigned_to": "a"},
                            {"title": "Phần 2", "assigned_to": "b"}],
        set_attempt_id=lambda a: None,
    )
    out = build_team_task_graph(deps=deps).invoke(
        {"step_title": "Bước", "acceptance": "- tiêu chí khó"})
    assert work_calls == [] and check_calls == []  # neither work nor self_check paid
    assert out["split_proposal"][0]["title"] == "Phần 1"
    assert delivered and "Đã chia bước thành 2 việc con" in delivered[0]


def test_work_runs_normally_when_split_off_or_empty():
    work_calls = []
    deps = TeamTaskDeps(
        read_handoff=lambda: "",
        run_work=lambda t, h, hook: (work_calls.append(t) or ("KQ", 0.01)),
        run_self_check=lambda text, acc: (True, [], 1.0),
        run_rework=lambda b, p, f: ("", None),
        deliver_step=lambda text, version, flag: (True, "ok"),
        take_split=lambda: [],  # wired but nothing proposed
    )
    out = build_team_task_graph(deps=deps).invoke({"step_title": "Bước"})
    assert work_calls == ["Bước"] and not out.get("split_proposal")


# --- ticker mint rule ------------------------------------------------------------


def test_fanout_mints_subs_and_gather_once(store):
    _plan(store)
    _finish_s1_with_split(store)
    deps = _deps(store)

    result = maybe_insert_fanout(deps, store.get("t1"))
    assert result is not None and result.action == "fanout_inserted"

    task = store.get("t1")
    by_id = {s.step_id: s for s in task.steps}
    subs = [by_id["s1-sub1"], by_id["s1-sub2"]]
    gather = by_id["s1-gather"]
    assert all(s.system_inserted and s.step_type == "work" and s.deps == ()
               and s.parent_step_id == "s1" and not s.needs_review for s in subs)
    assert gather.deps == ("s1-sub1", "s1-sub2")
    assert gather.needs_review is True  # inherited from s1
    assert gather.assigned_to == "agent-a"

    # idempotent: children exist → no second mint
    assert maybe_insert_fanout(deps, store.get("t1")) is None


def test_fanout_rejects_invalid_proposal_and_consumes_it(store):
    _plan(store)
    _finish_s1_with_split(store, split=[{"title": "một mình", "assigned_to": "agent-a"}])
    deps = _deps(store)

    assert maybe_insert_fanout(deps, store.get("t1")) is None  # <2 subs → refused
    task = store.get("t1")
    assert len(task.steps) == 2  # nothing minted
    assert next(s for s in task.steps if s.step_id == "s1").split_proposal_json is None


def test_fanout_assignee_fallback_and_step_cap(store):
    _plan(store)
    # unknown assignee falls back to the parent's
    _finish_s1_with_split(store, split=[
        {"title": "A", "assigned_to": "ai-la-day"}, {"title": "B", "assigned_to": "agent-b"},
    ])
    maybe_insert_fanout(_deps(store), store.get("t1"))
    sub1 = next(s for s in store.get("t1").steps if s.step_id == "s1-sub1")
    assert sub1.assigned_to == "agent-a"

    # step-cap: a proposal that would exceed MAX_TASK_STEPS is refused
    store2_id = "t2"
    store.create_task(task_id=store2_id, title="big", original_request="x")
    many = [{"step_id": f"m{i}", "title": f"b{i}", "assigned_to": "agent-a", "deps": []}
            for i in range(MAX_TASK_STEPS - 2)]
    store.set_plan(store2_id, many, plan_hash=_hash(many))
    store._conn.execute(
        "UPDATE team_steps SET status='done', split_proposal_json=? "
        "WHERE task_id=? AND step_id='m0'",
        (json.dumps(_SPLIT), store2_id))
    store._conn.commit()
    assert maybe_insert_fanout(_deps(store), store.get(store2_id)) is None


# --- readiness gate + gather copy ----------------------------------------------


def test_downstream_blocked_until_fanout_children_done(store):
    _plan(store)
    _finish_s1_with_split(store)
    maybe_insert_fanout(_deps(store), store.get("t1"))

    task = store.get("t1")
    ready_ids = {s.step_id for s in ready_pending_steps(task)}
    assert "s2" not in ready_ids  # dep s1 fanned out — children not done yet
    assert {"s1-sub1", "s1-sub2"} <= ready_ids  # subs themselves dispatch in parallel

    for sid in ("s1-sub1", "s1-sub2", "s1-gather"):
        store._conn.execute(
            "UPDATE team_steps SET status='done' WHERE task_id='t1' AND step_id=?", (sid,))
    store._conn.commit()
    ready_ids = {s.step_id for s in ready_pending_steps(store.get("t1"))}
    assert "s2" in ready_ids  # unblocked once every child is done


def test_gather_result_copied_onto_parent_artifact(store, tmp_path):
    from my_crew.agent.team_task_artifact import read_step_artifact, write_step_artifact
    from my_crew.runtime.team_task_paths import team_tasks_root

    _plan(store)
    _finish_s1_with_split(store)
    maybe_insert_fanout(_deps(store), store.get("t1"))
    task = store.get("t1")
    s1 = next(s for s in task.steps if s.step_id == "s1")
    gather = next(s for s in task.steps if s.step_id == "s1-gather")

    root = team_tasks_root()
    write_step_artifact(root, "t1", s1.seq, {
        "status": "done", "result_text": "Đã chia bước thành 2 việc con", "version": "a1"})
    write_step_artifact(root, "t1", gather.seq, {
        "status": "done", "result_text": "TỔNG HỢP A+B", "version": "g1"})
    store._conn.execute(
        "UPDATE team_steps SET status='done' WHERE task_id='t1' AND step_id='s1-gather'")
    store._conn.commit()

    maybe_copy_gather_results(_deps(store), store.get("t1"))
    parent_artifact = read_step_artifact(root, "t1", s1.seq)
    assert parent_artifact["result_text"] == "TỔNG HỢP A+B"
    assert parent_artifact["gathered_from"] == gather.seq
    assert parent_artifact["step_title"] == s1.title

    # idempotent — a second pass rewrites nothing (same content, marker matches)
    maybe_copy_gather_results(_deps(store), store.get("t1"))
    assert read_step_artifact(root, "t1", s1.seq)["result_text"] == "TỔNG HỢP A+B"


# --- review suppression + hash + tick integration -------------------------------


def test_split_parent_gets_no_review_row(store):
    from my_crew.agent.coordinator_nodes.review_insert import maybe_insert_review

    _plan(store)
    _finish_s1_with_split(store)
    task = store.get("t1")
    s1 = next(s for s in task.steps if s.step_id == "s1")
    assert s1.needs_review is True  # would normally trigger the review rule
    assert maybe_insert_review(_deps(store), task, s1) is False


def test_tick_flow_mints_then_dispatches_subs_in_parallel(store):
    """E2E qua run_one_tick: tick 1 mints fan-out rows (plan hash intact), tick 2
    dispatches BOTH subs in one tick (concurrency 2) — downstream s2 stays put."""
    _plan(store)
    _finish_s1_with_split(store)
    spawned: list[str] = []
    deps = _deps(store, concurrency=2,
                 spawn_step=lambda task, step, attempt_id: spawned.append(step.step_id) or 77)

    r1 = run_one_tick(deps)
    assert r1.action == "fanout_inserted"

    r2 = run_one_tick(deps)
    assert r2.action == "spawned"
    assert set(spawned) == {"s1-sub1", "s1-sub2"}  # parallel, and s2 was NOT dispatched


# --- review-fix regression guards (M1/M2/L4) -------------------------------------


def test_mint_is_atomic_failure_rolls_back_everything(store, monkeypatch):
    """M1: a failure mid-mint must leave ZERO fan-out rows — stranded subs without a
    gather would silently feed downstream the parent's notice as content."""
    _plan(store)
    _finish_s1_with_split(store)

    from my_crew.runtime import team_task_steps as steps_mod

    real_insert = steps_mod.insert_step
    calls = {"n": 0}

    def _boom_on_last(conn, task_id, step, **kwargs):
        calls["n"] += 1
        if calls["n"] == 3:  # the gather insert
            raise RuntimeError("crash giữa mint")
        return real_insert(conn, task_id, step, **kwargs)

    monkeypatch.setattr(steps_mod, "insert_step", _boom_on_last)
    with pytest.raises(RuntimeError):
        maybe_insert_fanout(_deps(store), store.get("t1"))

    task = store.get("t1")
    assert len(task.steps) == 2  # nothing persisted — the whole mint rolled back
    # proposal NOT consumed → the next tick retries the mint
    assert next(s for s in task.steps if s.step_id == "s1").split_proposal_json


def test_amend_refused_while_fanout_children_undone(store):
    """M2: an amend swaps pending rows — pending subs/gather included — which would
    orphan the split parent on its notice forever. Drafting must refuse."""
    _plan(store)
    _finish_s1_with_split(store)
    maybe_insert_fanout(_deps(store), store.get("t1"))

    with pytest.raises(ValueError, match="chia nhỏ"):
        store.set_amendment_draft(
            "t1", base_plan_hash="h", new_plan_hash="h2",
            new_pending_steps=[{"step_id": "x", "title": "x", "assigned_to": "agent-a",
                                "deps": []}],
            old_pending_step_ids=["s2"],
        )

    # once every child is done, amend drafting works again
    for sid in ("s1-sub1", "s1-sub2", "s1-gather"):
        store._conn.execute(
            "UPDATE team_steps SET status='done' WHERE task_id='t1' AND step_id=?", (sid,))
    store._conn.commit()
    amendment_id = store.set_amendment_draft(
        "t1", base_plan_hash="h", new_plan_hash="h2",
        new_pending_steps=[{"step_id": "x", "title": "x", "assigned_to": "agent-a",
                            "deps": []}],
        old_pending_step_ids=["s2"],
    )
    assert amendment_id


def test_id_collision_with_plan_step_reads_as_invalid(store):
    """L4: a confirmed plan already containing '<parent>-sub1' must not wedge the
    tick in a UNIQUE-violation loop — the proposal is refused + consumed instead."""
    plan = [
        {"step_id": "s1", "title": "So sánh", "assigned_to": "agent-a", "deps": []},
        {"step_id": "s1-sub1", "title": "trùng tên", "assigned_to": "agent-b",
         "deps": ["s1"]},
    ]
    store.create_task(task_id="t9", title="demo", original_request="x")
    store.set_plan("t9", plan, plan_hash=_hash(plan))
    store._conn.execute(
        "UPDATE team_steps SET status='done', split_proposal_json=? "
        "WHERE task_id='t9' AND step_id='s1'", (json.dumps(_SPLIT),))
    store._conn.commit()

    assert maybe_insert_fanout(_deps(store), store.get("t9")) is None
    task = store.get("t9")
    assert len(task.steps) == 2  # nothing minted
    assert next(s for s in task.steps if s.step_id == "s1").split_proposal_json is None
