"""v63 one-touch stall recovery (`ops_stalled_task`): accept / retry / drop against a
real on-disk store + artifact layout (no LLM involved — these handlers are pure store/
artifact writes gated on `status == "stalled"`)."""

from __future__ import annotations

import pytest

from my_crew.agent.ops_stalled_task import (
    preview_accept_stalled_result,
    preview_drop_stalled_step,
    preview_retry_stalled_step,
    run_accept_stalled_result,
    run_drop_stalled_step,
    run_retry_stalled_step,
)
from my_crew.agent.team_task_artifact import (
    read_review_verdict_artifact,
    read_step_artifact,
    write_review_verdict_artifact,
    write_step_artifact,
)
from my_crew.runtime.team_task_store import TeamTaskStore


@pytest.fixture(autouse=True)
def _isolated_team_tasks_root(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)
    return tmp_path


def _open_store(tmp_path) -> TeamTaskStore:
    from my_crew.runtime.team_task_paths import team_tasks_db_path

    return TeamTaskStore(team_tasks_db_path())


def _content_hash(steps: list[dict]) -> str:
    """The REAL dispatch-time hash — the ticker re-verifies it every tick, so a fixture
    with an arbitrary literal would stall on plan_hash_mismatch instead of exercising
    the path under test."""
    from types import SimpleNamespace

    from my_crew.agent.task_decomposition import decomposition_content_hash

    return decomposition_content_hash(SimpleNamespace(steps=[
        SimpleNamespace(step_id=s["step_id"], title=s["title"],
                        assigned_to=s["assigned_to"], deps=tuple(s.get("deps", ())))
        for s in steps
    ]))


def _mk_review_stalled_task(tmp_path, task_id="t1", pic_id="", needs_web=False) -> None:
    """One content step (done, needs_review) + one round-2 failed review (done) —
    the exact shape `review_rounds_exhausted` stalls on."""
    store = _open_store(tmp_path)
    try:
        store.create_task(task_id=task_id, title="Demo", original_request="x",
                          assigned_by="ceo", pic_id=pic_id)
        steps = [
            {"step_id": "s1", "title": "draft báo cáo", "assigned_to": "agent-a",
             "deps": [], "needs_review": True, "needs_web": needs_web},
        ]
        store.set_plan(task_id, steps, _content_hash(steps))
        attempt = store.reserve_step(task_id, "s1")
        store.mark_done(task_id, "s1", outcome_ref=f"team-tasks/{task_id}/step-1.json",
                        attempt_id=attempt)
        store.insert_step(task_id, {
            "step_id": "s1-review-2-2", "title": "Soát chéo: draft báo cáo",
            "assigned_to": "agent-b", "deps": ["s1"], "step_type": "review",
            "parent_step_id": "s1", "review_round": 2,
        })
        r_attempt = store.reserve_step(task_id, "s1-review-2-2")
        store.mark_done(task_id, "s1-review-2-2", attempt_id=r_attempt)
        store.set_task_status(task_id, "stalled")
    finally:
        store.close()
    write_step_artifact(tmp_path, task_id, 1,
                        {"result_text": "bản nháp", "version": attempt})
    write_review_verdict_artifact(
        tmp_path, task_id, 1, 2,
        {"passed": False, "failures": ["thiếu số liệu"], "notes": [],
         "reviewed_version": attempt, "round": 2, "result_text": "bản nháp\n\n- thiếu số liệu"},
    )


def _mk_dead_step_stalled_task(tmp_path, task_id="t2", pic_id="") -> None:
    store = _open_store(tmp_path)
    try:
        store.create_task(task_id=task_id, title="Demo dead", original_request="x",
                          assigned_by="ceo", pic_id=pic_id)
        steps = [
            {"step_id": "s1", "title": "thu thập", "assigned_to": "agent-a", "deps": []},
            {"step_id": "s2", "title": "tổng hợp", "assigned_to": "agent-b", "deps": ["s1"]},
        ]
        store.set_plan(task_id, steps, _content_hash(steps))
        attempt = store.reserve_step(task_id, "s1")
        store.mark_failed(task_id, "s1", attempt_id=attempt)
        store.set_task_status(task_id, "stalled")
    finally:
        store.close()


# --- shared precondition -------------------------------------------------------------


def test_commands_reject_a_task_that_is_not_stalled(tmp_path):
    store = _open_store(tmp_path)
    try:
        store.create_task(task_id="t9", title="ok", assigned_by="ceo")
        t9_steps = [{"step_id": "s1", "title": "a", "assigned_to": "x", "deps": []}]
        store.set_plan("t9", t9_steps, _content_hash(t9_steps))
    finally:
        store.close()
    for run in (run_accept_stalled_result, run_retry_stalled_step, run_drop_stalled_step):
        with pytest.raises(ValueError, match="không phải 'stalled'"):
            run({"task_id": "t9"})


def test_commands_reject_an_unknown_task(tmp_path):
    with pytest.raises(ValueError, match="không tìm thấy"):
        run_accept_stalled_result({"task_id": "ghost"})


def test_previews_reject_an_unknown_task(tmp_path):
    """A preview must never promise action on a task that run would refuse — the
    same existence check fires at preview, so the CEO sees "không tìm thấy" instead
    of an optimistic "Mình sẽ..." that only fails at confirm."""
    for preview in (preview_accept_stalled_result, preview_retry_stalled_step,
                    preview_drop_stalled_step):
        with pytest.raises(ValueError, match="không tìm thấy"):
            preview({"task_id": "ghost"})


def test_previews_reject_a_task_that_is_not_stalled(tmp_path):
    store = _open_store(tmp_path)
    try:
        store.create_task(task_id="t9", title="ok", assigned_by="ceo")
        t9_steps = [{"step_id": "s1", "title": "a", "assigned_to": "x", "deps": []}]
        store.set_plan("t9", t9_steps, _content_hash(t9_steps))
    finally:
        store.close()
    for preview in (preview_accept_stalled_result, preview_retry_stalled_step,
                    preview_drop_stalled_step):
        with pytest.raises(ValueError, match="không phải 'stalled'"):
            preview({"task_id": "t9"})


# --- accept_stalled_result -----------------------------------------------------------


def test_accept_flips_the_failing_verdict_and_reopens(tmp_path):
    _mk_review_stalled_task(tmp_path)

    reply = run_accept_stalled_result({"task_id": "t1"})

    assert "Đã chấp nhận" in reply
    verdict = read_review_verdict_artifact(tmp_path, "t1", 1, 2)
    assert verdict["passed"] is True
    assert verdict["ceo_override"] is True
    assert any("CEO chấp nhận" in n for n in verdict["notes"])
    assert verdict["failures"] == ["thiếu số liệu"]  # kept for the record
    store = _open_store(tmp_path)
    try:
        assert store.get("t1").status == "open"
    finally:
        store.close()


def test_accept_rejects_a_dead_step_stall(tmp_path):
    _mk_dead_step_stalled_task(tmp_path)
    with pytest.raises(ValueError, match="không dừng vì soát chéo"):
        run_accept_stalled_result({"task_id": "t2"})


# --- retry_stalled_step --------------------------------------------------------------


def test_retry_mints_one_extra_rework_round_with_ceo_note(tmp_path):
    _mk_review_stalled_task(tmp_path)

    reply = run_retry_stalled_step({"task_id": "t1", "note": "tập trung phần số liệu quý 2"})

    assert "MỘT vòng sửa" in reply
    store = _open_store(tmp_path)
    try:
        task = store.get("t1")
        assert task.status == "open"
        rework = next(s for s in task.steps if s.step_id == "s1-rework-2")
        assert rework.step_type == "rework"
        assert rework.status == "pending"
        assert rework.assigned_to == "agent-a"  # same original author
        assert rework.deps == ("s1-review-2-2",)  # brief rides the verdict artifact
        assert rework.review_round == 2
        assert rework.system_inserted is True
    finally:
        store.close()
    verdict = read_review_verdict_artifact(tmp_path, "t1", 1, 2)
    assert "tập trung phần số liệu quý 2" in verdict["result_text"]
    assert verdict["passed"] is False  # retry does NOT accept — the verdict stands


def test_retry_rework_inherits_the_parents_web_declaration(tmp_path):
    """The minted redo of a live data-collection step must stay marked as one: the
    `needs_web` declaration is what keeps a later reassign from handing the redo to
    an agent with no search tool (`_can_do_step` trusts the flag alone)."""
    _mk_review_stalled_task(tmp_path, needs_web=True)

    run_retry_stalled_step({"task_id": "t1"})

    store = _open_store(tmp_path)
    try:
        rework = next(s for s in store.get("t1").steps if s.step_id == "s1-rework-2")
        assert rework.needs_web is True
    finally:
        store.close()


def test_retry_refuses_a_double_retry_before_the_round_ran(tmp_path):
    _mk_review_stalled_task(tmp_path)
    run_retry_stalled_step({"task_id": "t1"})
    store = _open_store(tmp_path)
    try:
        store.set_task_status("t1", "stalled")  # simulate: still stalled, retry again
    finally:
        store.close()
    with pytest.raises(ValueError, match="đã.*tồn tại"):
        run_retry_stalled_step({"task_id": "t1"})


def test_retry_resets_dead_steps_to_pending(tmp_path):
    _mk_dead_step_stalled_task(tmp_path)

    reply = run_retry_stalled_step({"task_id": "t2"})

    assert "đặt lại 1 bước" in reply.lower()
    store = _open_store(tmp_path)
    try:
        task = store.get("t2")
        assert task.status == "open"
        s1 = next(s for s in task.steps if s.step_id == "s1")
        assert s1.status == "pending"
        assert s1.attempt_id is None  # fresh dispatch, no stale lease
    finally:
        store.close()


# --- drop_stalled_step ---------------------------------------------------------------


def test_drop_marks_dead_step_done_with_placeholder_and_clears_review(tmp_path):
    _mk_dead_step_stalled_task(tmp_path)

    reply = run_drop_stalled_step({"task_id": "t2"})

    assert "Đã bỏ 1 bước" in reply
    store = _open_store(tmp_path)
    try:
        task = store.get("t2")
        assert task.status == "open"
        s1 = next(s for s in task.steps if s.step_id == "s1")
        assert s1.status == "done"
        assert s1.needs_review is False  # a placeholder must never enter peer review
        artifact = read_step_artifact(tmp_path, "t2", s1.seq)
        assert "bỏ qua" in artifact["result_text"]
    finally:
        store.close()


def test_drop_refuses_the_pic_terminal_step(tmp_path):
    store = _open_store(tmp_path)
    try:
        store.create_task(task_id="t3", title="PIC", assigned_by="ceo", pic_id="agent-b")
        t3_steps = [
            {"step_id": "s1", "title": "thu thập", "assigned_to": "agent-a", "deps": []},
            {"step_id": "s2", "title": "chốt", "assigned_to": "agent-b", "deps": ["s1"]},
        ]
        store.set_plan("t3", t3_steps, _content_hash(t3_steps))
        a1 = store.reserve_step("t3", "s1")
        store.mark_done("t3", "s1", attempt_id=a1)
        a2 = store.reserve_step("t3", "s2")
        store.mark_failed("t3", "s2", attempt_id=a2)
        store.set_task_status("t3", "stalled")
    finally:
        store.close()
    with pytest.raises(ValueError, match="bước chốt cuối của PIC"):
        run_drop_stalled_step({"task_id": "t3"})


def test_drop_on_a_review_stall_points_to_accept(tmp_path):
    _mk_review_stalled_task(tmp_path)
    with pytest.raises(ValueError, match="accept_stalled_result"):
        run_drop_stalled_step({"task_id": "t1"})


# --- end-to-end: accept → next tick aggregates and completes the task -----------------


def test_accepted_task_completes_on_the_next_tick(tmp_path):
    from my_crew.agent.coordinator_graph import (
        CoordinatorDeps,
        in_memory_retry_tracker,
        run_one_tick,
    )

    _mk_review_stalled_task(tmp_path)
    run_accept_stalled_result({"task_id": "t1"})

    store = _open_store(tmp_path)
    delivered: list[str] = []
    try:
        deps = CoordinatorDeps(
            store=store,
            retry_tracker=in_memory_retry_tracker(),
            cost_cap_usd=2.0,
            spawn_step=lambda task, step, attempt_id: 4242,
            pid_alive=lambda pid: True,
            kill_pid=lambda pid, attempt_id: None,
            aggregate=lambda task: ("tổng kết cuối", 0.01),
            deliver_room=lambda task, summary: delivered.append(summary),
            escalate=lambda task, step, kind, msg: None,
        )
        result = run_one_tick(deps)
        assert result.action == "aggregated"
        assert delivered == ["tổng kết cuối"]
        assert store.get("t1").status == "done"
    finally:
        store.close()


# --- v63 list_team_tasks: board + retro numbers ---------------------------------------


def test_list_team_tasks_shows_retro_and_flags_waiting_decisions(tmp_path):
    from my_crew.agent.ops_list_team_tasks import run_list_team_tasks

    _mk_review_stalled_task(tmp_path)  # stalled: 1 work + 1 review row, both done

    reply = run_list_team_tasks({})

    assert "t1" in reply
    assert "BỊ DỪNG" in reply
    assert "1 lượt soát" in reply
    assert "chờ quyết định" in reply


def test_list_team_tasks_empty_store(tmp_path):
    from my_crew.agent.ops_list_team_tasks import run_list_team_tasks

    assert run_list_team_tasks({}) == "Chưa có thẻ việc nhóm nào."


def test_list_team_tasks_flags_done_but_undelivered(tmp_path):
    from my_crew.agent.ops_list_team_tasks import run_list_team_tasks

    store = _open_store(tmp_path)
    try:
        store.create_task(task_id="t1", title="Demo xong nhung mat tin")
        store.set_task_status("t1", "done")
        store.set_delivery("t1", status="failed", summary="tong ket")
    finally:
        store.close()

    reply = run_list_team_tasks({})
    assert "CHƯA BÁO ĐƯỢC" in reply


def test_list_team_tasks_says_how_many_times_a_task_came_back_to_life(tmp_path):
    """A revived task reports the same step counts as one that ran straight through, so
    without this the CEO cannot tell "went fine" from "I had to retry it twice"."""
    from my_crew.agent.ops_list_team_tasks import run_list_team_tasks

    store = _open_store(tmp_path)
    try:
        store.create_task(task_id="t1", title="Viec phai retry")
        store.set_task_status("t1", "stalled")
        assert store.reopen_stalled("t1") is True
        store.set_task_status("t1", "stalled")
        assert store.reopen_stalled("t1") is True
    finally:
        store.close()

    assert "hồi sinh 2 lần" in run_list_team_tasks({})


def test_a_task_that_never_stalled_says_nothing_about_revival(tmp_path):
    from my_crew.agent.ops_list_team_tasks import run_list_team_tasks

    store = _open_store(tmp_path)
    try:
        store.create_task(task_id="t1", title="Viec chay mot mach")
    finally:
        store.close()

    assert "hồi sinh" not in run_list_team_tasks({})


# --- C1 regression: the tick AFTER a retry must dispatch the rework, not re-stall -----


def test_retried_task_dispatches_the_rework_on_the_next_tick(tmp_path):
    """Review-found C1: the exhausted-round rule used to re-read the same failed
    verdict on the next tick and re-stall BEFORE the override rework ever dispatched
    (review rules run ahead of dispatch) — making retry_stalled_step futile. The
    rework row AT the exhausted round is the override signal the rule must honor."""
    from my_crew.agent.coordinator_graph import (
        CoordinatorDeps,
        in_memory_retry_tracker,
        run_one_tick,
    )

    _mk_review_stalled_task(tmp_path)
    run_retry_stalled_step({"task_id": "t1", "note": "chốt số liệu quý 2"})

    store = _open_store(tmp_path)
    escalated: list[str] = []
    try:
        deps = CoordinatorDeps(
            store=store,
            retry_tracker=in_memory_retry_tracker(),
            cost_cap_usd=2.0,
            spawn_step=lambda task, step, attempt_id: 4242,
            pid_alive=lambda pid: True,
            kill_pid=lambda pid, attempt_id: None,
            aggregate=lambda task: ("tổng kết", None),
            deliver_room=lambda task, summary: None,
            escalate=lambda task, step, kind, msg: escalated.append(kind),
        )
        result = run_one_tick(deps)
        assert result.action == "spawned"
        assert "s1-rework-2" in result.detail
        assert escalated == []  # no duplicate review_rounds_exhausted escalation
        task = store.get("t1")
        assert task.status in ("open", "running")
        rework = next(s for s in task.steps if s.step_id == "s1-rework-2")
        assert rework.status == "running"
    finally:
        store.close()


# --- H2 regression: superseded failed verdicts must not misclassify the stall --------


def test_superseded_failed_review_does_not_count_as_review_stall(tmp_path):
    """History "round 0 failed → rework → round 1 PASSED", task later stalled by a
    dead sibling step: accept must refuse (nothing review-failed to accept) instead of
    flipping the long-superseded round-0 verdict (review-found H2)."""
    store = _open_store(tmp_path)
    try:
        store.create_task(task_id="t4", title="Mixed", original_request="x",
                          assigned_by="ceo")
        steps = [
            {"step_id": "s1", "title": "draft", "assigned_to": "agent-a", "deps": [],
             "needs_review": True},
            {"step_id": "s2", "title": "thu thập", "assigned_to": "agent-b", "deps": []},
        ]
        store.set_plan("t4", steps, _content_hash(steps))
        a1 = store.reserve_step("t4", "s1")
        store.mark_done("t4", "s1", attempt_id=a1)
        # Round-0 review (failed verdict) then round-1 review (passed) of the same step.
        for step_id, round_no in (("s1-review-0-0", 0), ("s1-review-1-1", 1)):
            store.insert_step("t4", {
                "step_id": step_id, "title": "Soát chéo: draft", "assigned_to": "agent-c",
                "deps": ["s1"], "step_type": "review", "parent_step_id": "s1",
                "review_round": round_no,
            })
            att = store.reserve_step("t4", step_id)
            store.mark_done("t4", step_id, attempt_id=att)
        a2 = store.reserve_step("t4", "s2")
        store.mark_failed("t4", "s2", attempt_id=a2)  # the REAL stall cause
        store.set_task_status("t4", "stalled")
    finally:
        store.close()
    write_step_artifact(tmp_path, "t4", 1, {"result_text": "nháp", "version": a1})
    write_review_verdict_artifact(
        tmp_path, "t4", 1, 0,
        {"passed": False, "failures": ["cũ"], "notes": [], "reviewed_version": a1,
         "round": 0, "result_text": "nháp"},
    )
    write_review_verdict_artifact(
        tmp_path, "t4", 1, 1,
        {"passed": True, "failures": [], "notes": [], "reviewed_version": a1,
         "round": 1, "result_text": "nháp"},
    )

    with pytest.raises(ValueError, match="không dừng vì soát chéo"):
        run_accept_stalled_result({"task_id": "t4"})
    # And drop correctly treats it as a dead-step stall.
    reply = run_drop_stalled_step({"task_id": "t4"})
    assert "Đã bỏ 1 bước" in reply


# --- v64 honest-drop handoff ---------------------------------------------------------


def test_dropped_placeholder_forbids_downstream_fabrication(tmp_path):
    """UAT-found: the old bland placeholder let a summarizing step FABRICATE plausible
    measurements. The placeholder is now a hard directive, and the work-step SYSTEM
    prompt + aggregate prompt carry the same data-honesty rule."""
    from my_crew.agent.ops_stalled_task import _DROPPED_RESULT_TEXT
    from my_crew.llm.team_task_prompt import _SYSTEM

    assert "KHÔNG CÓ KẾT QUẢ" in _DROPPED_RESULT_TEXT
    assert "không được suy diễn" in _DROPPED_RESULT_TEXT.lower() \
        or "không được" in _DROPPED_RESULT_TEXT
    assert "bịa" in _SYSTEM  # work-step system prompt carries the honesty rule


# --- v74.1: a dead needs_web step leaves a searchless assignee on reset ----------------


def _mk_dead_web_step_stalled_task(tmp_path, task_id="t8") -> None:
    store = _open_store(tmp_path)
    try:
        store.create_task(task_id=task_id, title="Demo dead web", original_request="x",
                          assigned_by="ceo")
        steps = [
            {"step_id": "s1", "title": "khảo giá", "assigned_to": "agent-a", "deps": [],
             "needs_web": True},
            {"step_id": "s2", "title": "tổng hợp", "assigned_to": "agent-b", "deps": ["s1"]},
        ]
        store.set_plan(task_id, steps, _content_hash(steps))
        attempt = store.reserve_step(task_id, "s1")
        store.mark_failed(task_id, "s1", attempt_id=attempt)
        store.set_task_status(task_id, "stalled")
    finally:
        store.close()


def test_retry_reassigns_dead_web_step_away_from_searchless_agent(tmp_path, monkeypatch):
    """Resetting a needs_web step to an assignee who cannot search dies identically on
    the next attempt — the reset must move it to a web-capable colleague."""
    import my_crew.agent.team_task_roster as roster
    import my_crew.runtime.team_tick_runner as ttr

    _mk_dead_web_step_stalled_task(tmp_path)
    monkeypatch.setattr(roster, "assignable_staff",
                        lambda: [("agent-b", "office"), ("researcher-x", "office")])
    monkeypatch.setattr(ttr, "agent_web_capable", lambda a: a == "researcher-x")
    reply = run_retry_stalled_step({"task_id": "t8"})
    assert "researcher-x" in reply
    store = _open_store(tmp_path)
    try:
        s1 = store.get_step("t8", "s1")
        assert s1.assigned_to == "researcher-x"
        assert s1.status == "pending"
    finally:
        store.close()


def test_retry_keeps_assignee_when_no_capable_replacement(tmp_path, monkeypatch):
    """No web-capable colleague ⇒ keep the current assignee (an honest same-agent
    retry beats an equally-doomed swap) — the reset itself still happens."""
    import my_crew.agent.team_task_roster as roster
    import my_crew.runtime.team_tick_runner as ttr

    _mk_dead_web_step_stalled_task(tmp_path)
    monkeypatch.setattr(roster, "assignable_staff", lambda: [("agent-b", "office")])
    monkeypatch.setattr(ttr, "agent_web_capable", lambda a: False)
    reply = run_retry_stalled_step({"task_id": "t8"})
    assert "đổi người" not in reply
    store = _open_store(tmp_path)
    try:
        s1 = store.get_step("t8", "s1")
        assert s1.assigned_to == "agent-a"
        assert s1.status == "pending"
    finally:
        store.close()
