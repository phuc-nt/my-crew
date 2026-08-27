"""Coordinator judgement on a step that finished but failed its own acceptance
criteria (`needs_decision`). Covers the three legal rulings, the hard intervention cap,
the roster gate on reassign, and the degrade-to-give_up paths — all against
`run_one_tick` with an injected judge seam (no real LLM).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from my_crew.agent.coordinator_graph import CoordinatorDeps, in_memory_retry_tracker, run_one_tick
from my_crew.agent.coordinator_nodes.stuck_decision import MAX_INTERVENTIONS
from my_crew.agent.task_decomposition import decomposition_content_hash
from my_crew.runtime.team_task_store import TeamTaskStore


@pytest.fixture(autouse=True)
def _isolated_team_tasks_root(monkeypatch, tmp_path):
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)


def _content_hash(steps: list[dict]) -> str:
    return decomposition_content_hash(SimpleNamespace(steps=[
        SimpleNamespace(
            step_id=s["step_id"], title=s["title"], assigned_to=s["assigned_to"],
            deps=tuple(s.get("deps", ())),
            needs_shell=bool(s.get("needs_shell", False)),
            external_write=bool(s.get("external_write", False)),
            needs_web=bool(s.get("needs_web", False)),
        )
        for s in steps
    ]))


def _stuck_store(tmp_path) -> TeamTaskStore:
    """A one-step task whose only step already came back `needs_decision` — the exact
    state Phase 1's blocked self-check leaves behind."""
    steps = [{"step_id": "s1", "title": "tra cuu", "assigned_to": "agent-a", "deps": []}]
    store = TeamTaskStore(tmp_path / "team_tasks.sqlite3")
    store.create_task(task_id="t1", title="demo task", original_request="lam demo")
    store.set_plan("t1", steps, plan_hash=_content_hash(steps))
    attempt = store.reserve_step("t1", "s1")
    store.mark_needs_decision("t1", "s1", attempt_id=attempt, outcome_ref="ref-1")
    return store


def _deps(store, **overrides) -> CoordinatorDeps:
    base = dict(
        store=store,
        retry_tracker=in_memory_retry_tracker(),
        cost_cap_usd=2.0,
        spawn_step=lambda task, step, attempt_id: 4242,
        pid_alive=lambda pid: True,
        kill_pid=lambda pid, attempt_id: None,
        aggregate=lambda task: ("done summary", 0.01),
        deliver_room=lambda task, summary: None,
        escalate=lambda task, step, kind, msg: None,
        roster_ok=lambda agent_id: agent_id in {"agent-a", "agent-b"},
        now=lambda: datetime.now(UTC),
    )
    base.update(overrides)
    return CoordinatorDeps(**base)


# --- retry_with_guidance -------------------------------------------------------------


def test_retry_with_guidance_sends_step_back_to_pending_carrying_the_direction(tmp_path):
    store = _stuck_store(tmp_path)
    result = run_one_tick(_deps(store, judge_stuck_step=lambda brief, step: {
        "decision": "retry_with_guidance",
        "guidance": "phải trích dẫn nguồn thật, không được nói chung chung",
    }))

    assert result.action == "stuck_retry"
    step = store.get_step("t1", "s1")
    assert step.status == "pending"
    # The guidance must be persisted on the step — that is the only path by which the
    # next attempt's handoff can show it (`_read_handoff` appends it).
    assert "trích dẫn nguồn thật" in step.guidance
    assert step.intervention_count == 1


def test_retry_without_concrete_guidance_is_refused_and_becomes_give_up(tmp_path):
    store = _stuck_store(tmp_path)
    result = run_one_tick(_deps(store, judge_stuck_step=lambda brief, step: {
        "decision": "retry_with_guidance", "guidance": "   ",
    }))

    assert result.action == "gave_up"
    assert store.get("t1").status == "stalled"
    assert store.get_step("t1", "s1").status == "failed"


# --- reassign ------------------------------------------------------------------------


def test_reassign_to_a_roster_member_repoints_the_step_and_requeues_it(tmp_path):
    store = _stuck_store(tmp_path)
    store.bump_intervention("t1", "s1")  # 2nd ruling — past the retry-first coercion
    result = run_one_tick(_deps(store, judge_stuck_step=lambda brief, step: {
        "decision": "reassign", "assign_to": "agent-b",
    }))

    assert result.action == "stuck_reassigned"
    step = store.get_step("t1", "s1")
    assert step.assigned_to == "agent-b"
    assert step.status == "pending"


def test_reassign_restamps_the_plan_hash_so_the_next_tick_does_not_stall(tmp_path):
    """`assigned_to` is one of the four fields the plan hash covers. Without a re-stamp
    the very next tick recomputes a different digest, stalls the task, and escalates a
    tampering alarm about a change the coordinator itself made — so reassign would break
    every task it touched."""
    store = _stuck_store(tmp_path)
    store.bump_intervention("t1", "s1")  # 2nd ruling — past the retry-first coercion
    run_one_tick(_deps(store, judge_stuck_step=lambda brief, step: {
        "decision": "reassign", "assign_to": "agent-b",
    }))

    # The task survives a subsequent tick: the stored hash matches the reassigned DAG.
    result = run_one_tick(_deps(store, judge_stuck_step=lambda brief, step: None))

    assert result.action != "plan_hash_mismatch"
    task = store.get("t1")
    assert task.status != "stalled"
    assert task.plan_hash == _content_hash(
        [{"step_id": "s1", "title": "tra cuu", "assigned_to": "agent-b", "deps": []}]
    )


def test_reassign_restamp_only_covers_the_ceo_confirmed_rows(tmp_path):
    """The re-stamp must recompute over `system_inserted = 0` rows ONLY — the same
    subset `_verify_plan_hash` compares against. Folding an auto-inserted review/rework
    row into the digest would stall the task the moment one exists."""
    store = _stuck_store(tmp_path)
    # `insert_step` is the ticker-minted path — it forces `system_inserted = 1`.
    store.insert_step(
        "t1", {"step_id": "sys1", "title": "soat cheo", "assigned_to": "agent-b",
               "deps": ["s1"]},
    )

    store.reassign_step("t1", "s1", "agent-b")

    assert store.get("t1").plan_hash == _content_hash(
        [{"step_id": "s1", "title": "tra cuu", "assigned_to": "agent-b", "deps": []}]
    )


def test_reassign_on_a_web_flagged_plan_still_passes_the_next_ticks_hash_check(tmp_path):
    """The live stall this reproduces: a research plan (needs_web=True at confirm) got a
    stuck-reassign, the re-stamp reconstructed rows WITHOUT the conditional flags, and
    the very next tick — hashing the real rows, flags included — could never match the
    freshly stamped digest again. The task stalled permanently with a tampering alarm
    about a write the coordinator itself made. The hash treats every flagged plan this
    way, so this covers `needs_shell`/`external_write` through the same seam."""
    steps = [
        {"step_id": "s1", "title": "tra cuu web", "assigned_to": "agent-a", "deps": [],
         "needs_web": True},
        {"step_id": "s2", "title": "chay script", "assigned_to": "agent-a",
         "deps": ["s1"], "needs_shell": True, "external_write": True},
    ]
    store = TeamTaskStore(tmp_path / "team_tasks.sqlite3")
    store.create_task(task_id="t1", title="demo task", original_request="lam demo")
    store.set_plan("t1", steps, plan_hash=_content_hash(steps))
    attempt = store.reserve_step("t1", "s1")
    store.mark_needs_decision("t1", "s1", attempt_id=attempt, outcome_ref="ref-1")
    store.bump_intervention("t1", "s1")  # 2nd ruling — past the retry-first coercion

    reassigned = run_one_tick(_deps(store, judge_stuck_step=lambda brief, step: {
        "decision": "reassign", "assign_to": "agent-b",
    }))
    assert reassigned.action == "stuck_reassigned"

    result = run_one_tick(_deps(store, judge_stuck_step=lambda brief, step: None))

    assert result.detail != "plan_hash mismatch"
    task = store.get("t1")
    assert task.status != "stalled"
    # The stored digest is the one the tick recompute (flags included) produces.
    assert task.plan_hash == _content_hash([
        {**steps[0], "assigned_to": "agent-b"}, steps[1],
    ])


def test_a_refused_reassign_leaves_the_plan_hash_untouched(tmp_path):
    """No row changed means nothing to re-stamp — a no-op write must not mint a new
    digest (which on a task with drifted rows would silently bless the drift)."""
    store = _stuck_store(tmp_path)
    before = store.get("t1").plan_hash

    assert store.reassign_step("t1", "nosuchstep", "agent-b") is False
    assert store.get("t1").plan_hash == before


def test_reassign_to_an_unknown_agent_is_refused_and_leaves_the_assignee_alone(tmp_path):
    store = _stuck_store(tmp_path)
    store.bump_intervention("t1", "s1")  # 2nd ruling — past the retry-first coercion
    result = run_one_tick(_deps(store, judge_stuck_step=lambda brief, step: {
        "decision": "reassign", "assign_to": "agent-ma",
    }))

    assert result.action == "gave_up"
    # The refusal must not half-apply: the invented assignee never reaches the store.
    assert store.get_step("t1", "s1").assigned_to == "agent-a"


# --- the hard cap --------------------------------------------------------------------


def test_at_the_intervention_cap_it_concludes_without_consulting_the_model(tmp_path):
    store = _stuck_store(tmp_path)
    for _ in range(MAX_INTERVENTIONS):
        store.bump_intervention("t1", "s1")
    calls = []

    def _judge(brief, step):
        calls.append(step.step_id)
        return {"decision": "retry_with_guidance", "guidance": "cứ thử lại đi"}

    result = run_one_tick(_deps(store, judge_stuck_step=_judge))

    assert result.action == "gave_up"
    assert calls == []  # the cap is deterministic — no money spent re-learning


# --- give_up + degradation -----------------------------------------------------------


def test_give_up_ends_the_task_with_an_honest_reason_and_runs_delivery(tmp_path):
    store = _stuck_store(tmp_path)
    delivered = []
    result = run_one_tick(_deps(
        store,
        judge_stuck_step=lambda brief, step: {
            "decision": "give_up", "reason": "không có công cụ tra cứu nào dùng được",
        },
        deliver_room=lambda task, summary: delivered.append(summary) or True,
    ))

    assert result.action == "gave_up"
    task = store.get("t1")
    assert task.status == "stalled"
    assert "không có công cụ tra cứu" in (task.final_summary or "")
    assert task.delivery_status == "delivered"
    assert delivered and "KHÔNG LÀM ĐƯỢC" in delivered[0]


def test_a_judge_that_raises_degrades_to_give_up_instead_of_hanging_the_task(tmp_path):
    store = _stuck_store(tmp_path)

    def _boom(brief, step):
        raise RuntimeError("model down")

    result = run_one_tick(_deps(store, judge_stuck_step=_boom))

    assert result.action == "gave_up"
    assert store.get("t1").status == "stalled"
    assert "không phán đoán được" in (store.get("t1").final_summary or "")


def test_an_unparseable_ruling_degrades_to_give_up(tmp_path):
    store = _stuck_store(tmp_path)
    result = run_one_tick(_deps(store, judge_stuck_step=lambda brief, step: None))

    assert result.action == "gave_up"
    assert "không phán đoán được" in (store.get("t1").final_summary or "")


# --- the untouched path --------------------------------------------------------------


def test_a_task_with_no_stuck_step_never_consults_the_judge(tmp_path):
    steps = [{"step_id": "s1", "title": "draft", "assigned_to": "agent-a", "deps": []}]
    store = TeamTaskStore(tmp_path / "team_tasks.sqlite3")
    store.create_task(task_id="t1", title="demo task", original_request="lam demo")
    store.set_plan("t1", steps, plan_hash=_content_hash(steps))
    calls = []

    result = run_one_tick(_deps(store, judge_stuck_step=lambda brief, step: calls.append(1)))

    assert result.action == "spawned"
    assert calls == []


def test_give_up_is_attempt_guarded_so_it_cannot_clobber_a_newer_attempt(tmp_path):
    """Review M1: `step` is a snapshot read at the top of the tick. If the step has been
    re-reserved since (a CEO's manual retry, a second ticker), the give_up write must be
    a clean no-op rather than marking the LIVE attempt's row failed."""
    store = _stuck_store(tmp_path)
    task = store.get("t1")
    stale_step = next(s for s in task.steps if s.step_id == "s1")
    # Somebody re-queues and re-reserves the step between the tick's read and its write.
    store.reset_step_to_pending("t1", "s1")
    store.reserve_step("t1", "s1")

    from my_crew.agent.coordinator_nodes.stuck_decision import _give_up

    _give_up(_deps(store), task, stale_step, "hết cách")

    # The newer attempt is still running — the stale ruling did not kill it.
    assert store.get_step("t1", "s1").status == "running"


def test_give_up_still_terminates_a_step_whose_lease_was_released_by_an_earlier_retry(
    tmp_path, caplog,
):
    """A `stalled` task must never keep a `pending` step.

    `_retry` clears attempt_id via `reset_step_to_pending`, so a later `_give_up` in the
    same decision sequence guards on a lease the row no longer carries and its write
    matches nothing. That silent miss is what produced live tasks stuck `stalled` with a
    dispatchable `pending` step that `retry_stalled_step` could not rescue.
    """
    store = _stuck_store(tmp_path)
    task = store.get("t1")
    stale_step = next(s for s in task.steps if s.step_id == "s1")
    assert stale_step.attempt_id  # the snapshot names a lease...
    store.reset_step_to_pending("t1", "s1")  # ...which this releases.

    from my_crew.agent.coordinator_nodes.stuck_decision import _give_up

    with caplog.at_level(logging.WARNING):
        _give_up(_deps(store), task, stale_step, "hết cách")

    assert store.get_step("t1", "s1").status == "failed"
    # The recovery worked, so nothing is escalated to the operator.
    assert "could not terminate step" not in caplog.text
    assert "matched no row" not in caplog.text


def test_a_terminal_write_that_matches_no_row_is_logged(tmp_path, caplog):
    """A dropped terminal write leaves a step alive under a task that moved on. The
    boolean was ignored at every call site, so the store itself says so."""
    store = _stuck_store(tmp_path)
    store.reset_step_to_pending("t1", "s1")

    with caplog.at_level(logging.WARNING):
        assert store.mark_failed("t1", "s1", attempt_id="an-attempt-nobody-holds") is False

    assert "matched no row" in caplog.text
    assert "s1" in caplog.text
    assert store.get_step("t1", "s1").status == "pending"


def test_the_pending_only_repair_cannot_kill_a_step_that_got_re_reserved(tmp_path):
    """`mark_failed_if_pending` drops the attempt guard, so `only_if_status` is the only
    thing keeping it off a live worker's row."""
    store = _stuck_store(tmp_path)
    store.reset_step_to_pending("t1", "s1")
    store.reserve_step("t1", "s1")

    assert store.mark_failed_if_pending("t1", "s1") is False
    assert store.get_step("t1", "s1").status == "running"


def test_a_step_awaiting_a_ruling_does_not_let_a_sibling_stall_the_task(tmp_path):
    """Review M3: `needs_decision` is in-flight — the ticker owes it a ruling, so a
    sibling's terminal failure must not stall the task out of dispatch first."""
    from my_crew.agent.coordinator_graph import _dead_end_result

    steps = [
        {"step_id": "s1", "title": "a", "assigned_to": "agent-a", "deps": []},
        {"step_id": "s2", "title": "b", "assigned_to": "agent-b", "deps": []},
    ]
    store = TeamTaskStore(tmp_path / "team_tasks.sqlite3")
    store.create_task(task_id="t1", title="demo task", original_request="lam demo")
    store.set_plan("t1", steps, plan_hash=_content_hash(steps))
    a1 = store.reserve_step("t1", "s1")
    store.mark_failed("t1", "s1", attempt_id=a1)
    a2 = store.reserve_step("t1", "s2")
    store.mark_needs_decision("t1", "s2", attempt_id=a2, outcome_ref="ref")

    assert _dead_end_result(_deps(store), store.get("t1")) is None
    assert store.get("t1").status != "stalled"


# --- what the judge is actually shown ------------------------------------------------


def _brief_for(tmp_path, artifact_payload: dict) -> str:
    """Run one tick over a `needs_decision` step and return the brief the judge saw."""
    from my_crew.agent.team_task_artifact import write_step_artifact

    store = _stuck_store(tmp_path)
    step = store.get_step("t1", "s1")
    write_step_artifact(tmp_path, "t1", step.seq, artifact_payload)
    seen: list[str] = []

    def _judge(brief, step):
        seen.append(brief)
        return {"decision": "give_up", "reason": "x"}

    run_one_tick(_deps(store, judge_stuck_step=_judge))
    assert seen, "judge was never consulted"
    return seen[0]


def test_the_judge_is_shown_the_failures_the_step_graded_itself_on(tmp_path):
    """The grader already named what was missing and wrote it to the artifact the judge
    opens. Re-deriving that from the raw output is impossible — absent data leaves no
    trace in the text — so the list has to be in the brief."""
    brief = _brief_for(tmp_path, {
        "status": "needs_decision",
        "result_text": "Bang so sanh gia cac dich vu.",
        "self_check_failed": True,
        "self_check_failures": [
            "thiếu giá gói cá nhân của Zing MP3",
            "thiếu link nguồn cho chất lượng âm thanh",
        ],
    })

    assert "thiếu giá gói cá nhân của Zing MP3" in brief
    assert "thiếu link nguồn cho chất lượng âm thanh" in brief
    # The submitted output still has to be there — the failures supplement it.
    assert "Bang so sanh gia cac dich vu." in brief


def test_a_brief_stays_well_formed_when_the_artifact_has_no_failure_list(tmp_path):
    """Older artifacts (and any step whose grader returned no reasons) carry no
    `self_check_failures`; the brief must simply omit the section."""
    brief = _brief_for(tmp_path, {
        "status": "needs_decision",
        "result_text": "ket qua cu",
        "self_check_failed": True,
    })

    assert "Bước tự chấm trượt" not in brief
    assert "ket qua cu" in brief
    assert "Số lần đã can thiệp:" in brief


# --- the judge's own prompt: anchored to today, forbidden to raise the bar ------------


def test_the_judge_is_told_todays_date_like_every_grader():
    """Measured live (lanes5, team/music, run on 27/08/2026): an un-anchored judge
    ruled from its training cutoff and wrote guidance ordering the worker to change a
    CORRECT access date to "27/08/2024 hoặc trước đó" — manufacturing the very defect
    the next grading round then failed. Same anchor producer as both graders, so the
    three prompts cannot drift apart."""
    from my_crew.llm.stuck_judgement_prompt import build_stuck_judge_messages
    from my_crew.llm.team_task_prompt import grader_today_line

    system = build_stuck_judge_messages("brief", ["ana"])[0]["content"]

    assert grader_today_line() in system


def test_the_judge_may_not_demand_source_metadata_beyond_the_acceptance():
    """Provenance trace over lanes5: every metadata demand that killed a sprint task
    ("báo cáo uy tín như Statista", "tác giả", "URL kiểm chứng độc lập") entered via
    this judge's `guidance` — acceptance criteria were clean in both cases — and the
    next round's grader graded against the guidance verbatim. The prompt must carry
    the same snippet-reality rule intake and decompose have: workers only see search
    excerpts, so "nêu rõ nguồn" stops at a site name or link."""
    from my_crew.llm.stuck_judgement_prompt import STUCK_JUDGE_SYSTEM

    assert "KHÔNG được nâng chuẩn" in STUCK_JUDGE_SYSTEM
    assert "ngày truy cập" in STUCK_JUDGE_SYSTEM
    assert "tên trang hoặc link" in STUCK_JUDGE_SYSTEM
    assert "Statista" in STUCK_JUDGE_SYSTEM
