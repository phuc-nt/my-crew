"""Coordinator judgement on a step that finished but failed its own acceptance
criteria (`needs_decision`). Covers the four legal rulings, the hard intervention cap,
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


# --- accept ------------------------------------------------------------------------


def test_accept_takes_the_failed_self_check_result_as_is_without_another_attempt(tmp_path):
    from my_crew.agent.team_task_artifact import read_step_artifact, write_step_artifact
    from my_crew.runtime.team_task_paths import team_tasks_root

    store = _stuck_store(tmp_path)
    write_step_artifact(team_tasks_root(), "t1", 1, {
        "status": "needs_decision", "result_text": "T1 62/48/41, T2 58/44",
        "self_check_failed": True, "self_check_failures": ["không nhắc tỷ lệ T1"],
    })
    spawned, alerts = [], []
    deps = _deps(
        store,
        judge_stuck_step=lambda brief, step: {
            "decision": "accept", "reason": "bốn tỷ lệ cohort đều có mặt, người chấm đọc sót",
        },
        spawn_step=lambda task, step, attempt_id: spawned.append(step.step_id) or 4242,
        escalate=lambda task, step, kind, msg: alerts.append((kind, msg)),
    )

    result = run_one_tick(deps)

    assert result.action == "stuck_accepted"
    step = store.get("t1").steps[0]
    assert step.status == "done"
    assert step.needs_review is False
    assert spawned == []
    artifact = read_step_artifact(team_tasks_root(), "t1", 1)
    assert artifact["result_text"] == "T1 62/48/41, T2 58/44"
    assert artifact["status"] == "done"
    assert "người chấm đọc sót" in artifact["accepted_by_coordinator"]
    assert [k for k, _ in alerts] == ["stuck"]
    assert "nhận kết quả như đang có" in alerts[0][1]
    # The accepted step is finished work: the next tick aggregates and the task is done.
    follow = run_one_tick(deps)
    assert follow.action == "aggregated"
    assert store.get("t1").status == "done"


def test_the_judge_is_shown_the_ceo_full_request_not_only_the_120_char_title(tmp_path):
    request = (
        "So sánh 3 công cụ họp trực tuyến (Zoom, Google Meet, Microsoft Teams) theo đúng 3 "
        "tiêu chí: giá gói trả phí thấp nhất, giới hạn thời gian họp của bản miễn phí, số "
        "người tham gia tối đa của bản miễn phí."
    )
    steps = [{"step_id": "s1", "title": "tra cuu", "assigned_to": "agent-a", "deps": []}]
    store = TeamTaskStore(tmp_path / "team_tasks.sqlite3")
    store.create_task(task_id="t1", title=request[:120], original_request=request)
    store.set_plan("t1", steps, plan_hash=_content_hash(steps))
    store.mark_needs_decision("t1", "s1", attempt_id=store.reserve_step("t1", "s1"))
    seen = []

    def _judge(brief, step):
        seen.append(brief)
        return {"decision": "give_up", "reason": "x"}

    run_one_tick(_deps(store, judge_stuck_step=_judge))

    assert "số người tham gia tối đa của bản miễn phí" in seen[0]
    assert "Yêu cầu gốc của CEO" in seen[0]


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


def test_the_judge_is_shown_its_own_prior_guidance(tmp_path):
    """Measured live (lanes6, both music cases): attempt-2 and attempt-3 work orders
    carried near-verbatim identical guidance, because the brief never showed the judge
    what it had already ordered — it re-derived the same direction from the same
    inputs and burned the intervention cap on a repeat. The accumulated
    `step.guidance` has to be in the brief, labeled as a FAILED order."""
    from my_crew.agent.team_task_artifact import write_step_artifact

    store = _stuck_store(tmp_path)
    step = store.get_step("t1", "s1")
    write_step_artifact(tmp_path, "t1", step.seq, {
        "status": "needs_decision", "result_text": "ket qua lan hai",
    })
    store.append_step_guidance("t1", "s1", "Thêm URL cho từng nguồn đã nêu.")
    seen: list[str] = []

    def _judge(brief, step):
        seen.append(brief)
        return {"decision": "give_up", "reason": "x"}

    run_one_tick(_deps(store, judge_stuck_step=_judge))

    assert seen
    assert "Chỉ dẫn ĐÃ RA" in seen[0]
    assert "Thêm URL cho từng nguồn đã nêu." in seen[0]


def test_a_brief_with_no_prior_guidance_omits_the_failed_orders_section(tmp_path):
    """First ruling on a step: nothing was ordered yet, so the section must be absent
    — an empty 'đã ra chỉ dẫn' block would tell the judge a failure happened that
    never did."""
    brief = _brief_for(tmp_path, {
        "status": "needs_decision", "result_text": "ket qua lan dau",
    })

    assert "Chỉ dẫn ĐÃ RA" not in brief


def test_the_judge_carries_a_convergence_rule_against_repeating_failed_guidance():
    """The structural fix (showing prior guidance) only helps if the prompt says what
    to do with it: a repeated order already failed once, so the only legal moves are
    lowering the demand to the acceptance's literal text, reassigning, or an honest
    give_up. Also locks the lanes6 escalation flavor the source-metadata rule did not
    cover: upgrading an accepted site name into a demand for 'real URLs'."""
    from my_crew.llm.stuck_judgement_prompt import STUCK_JUDGE_SYSTEM

    assert "QUY TẮC HỘI TỤ" in STUCK_JUDGE_SYSTEM
    assert "không lặp lại" in STUCK_JUDGE_SYSTEM
    assert "HẠ đòi hỏi" in STUCK_JUDGE_SYSTEM
    assert "thêm URL thực tế" in STUCK_JUDGE_SYSTEM


def test_the_judge_may_not_freeze_found_sources_into_a_mandatory_list():
    """Measured live (lanes7, team/ecommerce): guidance enumerated the five domains the
    worker had already cited and ordered full URLs "cho từng nguồn được trích dẫn" —
    the next grading round then failed the worker for citing other legitimate sources.
    A source list the worker discovered is evidence, not a closed spec: any source
    meeting the acceptance stays acceptable."""
    from my_crew.llm.stuck_judgement_prompt import STUCK_JUDGE_SYSTEM

    assert "KHÔNG phải danh sách" in STUCK_JUDGE_SYSTEM
    assert "danh sách nguồn BẮT BUỘC" in STUCK_JUDGE_SYSTEM
    assert "nguồn hợp lệ khác" in STUCK_JUDGE_SYSTEM


# --- salvage delivery on give_up -----------------------------------------------------


def _two_step_stuck_store(tmp_path) -> TeamTaskStore:
    """A task whose first step finished (`done`) and whose second came back
    `needs_decision` — the lanes6 team/ecommerce shape: a finished report stranded
    behind a stuck QA step."""
    steps = [
        {"step_id": "s0", "title": "soan bao cao", "assigned_to": "agent-a", "deps": []},
        {"step_id": "s1", "title": "tham dinh", "assigned_to": "agent-a", "deps": ["s0"]},
    ]
    store = TeamTaskStore(tmp_path / "team_tasks.sqlite3")
    store.create_task(task_id="t1", title="demo task", original_request="lam demo")
    store.set_plan("t1", steps, plan_hash=_content_hash(steps))
    a0 = store.reserve_step("t1", "s0")
    store.mark_done("t1", "s0", attempt_id=a0, outcome_ref="ref-0")
    a1 = store.reserve_step("t1", "s1")
    store.mark_needs_decision("t1", "s1", attempt_id=a1, outcome_ref="ref-1")
    return store


def _give_up_summary(store) -> str:
    """Run one tick with a judge that gives up; return the delivered summary."""
    delivered: list[str] = []
    result = run_one_tick(_deps(
        store,
        judge_stuck_step=lambda brief, step: {"decision": "give_up", "reason": "bế tắc"},
        deliver_room=lambda task, summary: delivered.append(summary),
    ))
    assert result.action == "gave_up"
    assert delivered
    return delivered[0]


def test_give_up_delivers_the_best_done_result_after_the_failure_line(tmp_path):
    """Measured live (lanes6, team/ecommerce): a finished report sat in the step-3
    artifact while give_up delivered only the abandonment note — the CEO never saw
    work that already existed. The salvage rides BEHIND the failure line, which must
    stay first (humans and the lane judge classify the outcome by that line)."""
    from my_crew.agent.team_task_artifact import write_step_artifact

    store = _two_step_stuck_store(tmp_path)
    report = "Báo cáo thị trường hoàn chỉnh.\n" + ("Dòng dữ liệu có nguồn.\n" * 30)
    write_step_artifact(
        tmp_path, "t1", store.get_step("t1", "s0").seq,
        {"status": "done", "result_text": report},
    )
    write_step_artifact(
        tmp_path, "t1", store.get_step("t1", "s1").seq,
        {"status": "needs_decision", "result_text": "bản thẩm định trượt"},
    )

    summary = _give_up_summary(store)

    assert summary.startswith("Việc 'demo task' KHÔNG LÀM ĐƯỢC")
    assert "Phần đã làm được trước khi kẹt (bước 'soan bao cao'):" in summary
    assert "Báo cáo thị trường hoàn chỉnh." in summary


def test_give_up_without_a_substantive_done_step_delivers_the_plain_note(tmp_path):
    """A done step whose artifact is thin (below the salvage bar) must not be dressed
    up as a deliverable — the summary stays exactly the honest abandonment note."""
    from my_crew.agent.team_task_artifact import write_step_artifact

    store = _two_step_stuck_store(tmp_path)
    write_step_artifact(
        tmp_path, "t1", store.get_step("t1", "s0").seq,
        {"status": "done", "result_text": "vài dòng ngắn"},
    )

    summary = _give_up_summary(store)

    assert "Phần đã làm được" not in summary
    assert summary.startswith("Việc 'demo task' KHÔNG LÀM ĐƯỢC")


def test_salvage_is_capped_at_a_line_boundary(tmp_path):
    from my_crew.agent.coordinator_nodes.stall_conclusion import _MAX_SALVAGE_CHARS
    from my_crew.agent.team_task_artifact import write_step_artifact

    store = _two_step_stuck_store(tmp_path)
    long_report = "\n".join(f"dòng {i}: nội dung có nguồn kèm theo" for i in range(500))
    write_step_artifact(
        tmp_path, "t1", store.get_step("t1", "s0").seq,
        {"status": "done", "result_text": long_report},
    )

    summary = _give_up_summary(store)
    salvage = summary.split("Phần đã làm được trước khi kẹt", 1)[1]

    assert "[... đã cắt bớt cho vừa bản tin]" in salvage
    assert len(salvage) <= _MAX_SALVAGE_CHARS + 200  # header + marker allowance
    # cut landed on a line boundary: the line right before the marker is intact
    body = salvage.split("\n[... đã cắt bớt cho vừa bản tin]", 1)[0]
    assert body.endswith("nội dung có nguồn kèm theo")


# --- degrade-and-continue: a non-terminal give_up becomes a skip-with-gap -------------


def _three_step_stuck_store(tmp_path) -> TeamTaskStore:
    """A linear 3-step chain whose FIRST step came back `needs_decision` — the
    lanes5-8 team shape: every bench stall died at the opening research step while
    two runnable steps sat behind it."""
    steps = [
        {"step_id": "s1", "title": "tra cuu", "assigned_to": "agent-a", "deps": []},
        {"step_id": "s2", "title": "phan tich", "assigned_to": "agent-a", "deps": ["s1"]},
        {"step_id": "s3", "title": "soan bao cao", "assigned_to": "agent-a", "deps": ["s2"]},
    ]
    store = TeamTaskStore(tmp_path / "team_tasks.sqlite3")
    store.create_task(task_id="t1", title="demo task", original_request="lam demo")
    store.set_plan("t1", steps, plan_hash=_content_hash(steps))
    attempt = store.reserve_step("t1", "s1")
    store.mark_needs_decision("t1", "s1", attempt_id=attempt, outcome_ref="ref-1")
    return store


def test_give_up_on_a_non_terminal_step_skips_it_and_the_task_keeps_running(tmp_path):
    from my_crew.agent.team_task_artifact import read_step_artifact

    store = _three_step_stuck_store(tmp_path)
    notes = []
    result = run_one_tick(_deps(
        store,
        judge_stuck_step=lambda brief, step: {
            "decision": "give_up", "reason": "nguồn cần thiết không công khai",
        },
        escalate=lambda task, step, kind, msg: notes.append((kind, msg)),
    ))

    assert result.action == "step_skipped"
    assert store.get_step("t1", "s1").status == "done"  # dropped counts as done
    task = store.get("t1")
    assert task.status != "stalled"
    assert not task.final_summary  # no abandonment delivery was minted
    artifact = read_step_artifact(tmp_path, "t1", 1) or {}
    text = artifact.get("result_text") or ""
    assert text.startswith("KHÔNG CÓ KẾT QUẢ")
    assert "Lý do bỏ qua (phán quyết điều phối): nguồn cần thiết không công khai" in text
    assert any("bỏ qua vì" in msg for _kind, msg in notes)


def test_after_a_skip_the_dependent_step_dispatches_on_the_next_tick(tmp_path):
    store = _three_step_stuck_store(tmp_path)
    run_one_tick(_deps(store, judge_stuck_step=lambda brief, step: {
        "decision": "give_up", "reason": "bế tắc",
    }))

    result = run_one_tick(_deps(store))

    assert result.action == "spawned"
    assert store.get_step("t1", "s2").status == "running"


def test_give_up_on_the_terminal_step_still_ends_the_task_honestly(tmp_path):
    """The terminal step IS the deliverable — skipping it would deliver nothing, so
    the original give_up (failed step, stalled task, abandonment note) stands."""
    store = _two_step_stuck_store(tmp_path)  # stuck step s1 is the chain's last
    delivered = []
    result = run_one_tick(_deps(
        store,
        judge_stuck_step=lambda brief, step: {"decision": "give_up", "reason": "bế tắc"},
        deliver_room=lambda task, summary: delivered.append(summary) or True,
    ))

    assert result.action == "gave_up"
    assert store.get("t1").status == "stalled"
    assert delivered and "KHÔNG LÀM ĐƯỢC" in delivered[0]


def test_a_skip_refused_by_the_attempt_guard_falls_back_to_the_legacy_give_up(tmp_path):
    """The snapshot's lease is stale (step re-reserved since the tick's read): the
    drop write must be a no-op — never clobber the live attempt's row to `done` —
    and the ruling degrades to the legacy give_up path, whose own guards already
    know how to leave a re-reserved step alone."""
    store = _three_step_stuck_store(tmp_path)
    task = store.get("t1")
    stale_step = next(s for s in task.steps if s.step_id == "s1")
    store.reset_step_to_pending("t1", "s1")
    store.reserve_step("t1", "s1")

    from my_crew.agent.coordinator_nodes.stuck_decision import _give_up

    _give_up(_deps(store), task, stale_step, "hết cách")

    assert store.get_step("t1", "s1").status == "running"


def test_a_concurrent_deciders_give_up_cannot_reverse_a_completed_skip(tmp_path):
    """Two coordinator ticks can overlap on the same stuck step (the window spans the
    judge LLM call). The first one's skip lands: row `done`, attempt retired. The
    loser's give_up — still holding a snapshot with the ORIGINAL attempt lease — must
    acknowledge the sibling's skip, not flip the dropped row back to `failed` and
    stall a task whose dependents are already dispatching."""
    store = _three_step_stuck_store(tmp_path)
    stale_task = store.get("t1")
    stale_step = next(s for s in stale_task.steps if s.step_id == "s1")

    from my_crew.agent.coordinator_nodes.stuck_decision import _give_up

    winner = _give_up(_deps(store), stale_task, stale_step, "nguồn không công khai")
    assert winner.action == "step_skipped"
    assert store.get_step("t1", "s1").attempt_id is None  # lease retired by the drop

    loser = _give_up(_deps(store), stale_task, stale_step, "nguồn không công khai")

    assert loser.action == "step_skipped"
    assert store.get_step("t1", "s1").status == "done"
    refreshed = store.get("t1")
    assert refreshed.status != "stalled"
    assert not refreshed.final_summary


def test_a_sibling_stuck_step_still_counts_as_live_for_skippability(tmp_path):
    """Two steps stuck at once must not talk each other into killing the task: a
    `needs_decision` sibling is still live — its own tick may skip or resume it —
    so the first ruling skips instead of falling into the terminal give_up."""
    steps = [
        {"step_id": "s1", "title": "tra cuu A", "assigned_to": "agent-a", "deps": []},
        {"step_id": "s2", "title": "tra cuu B", "assigned_to": "agent-a", "deps": []},
        {"step_id": "s3", "title": "tong hop", "assigned_to": "agent-a",
         "deps": ["s1", "s2"]},
    ]
    store = TeamTaskStore(tmp_path / "team_tasks.sqlite3")
    store.create_task(task_id="t1", title="demo task", original_request="lam demo")
    store.set_plan("t1", steps, plan_hash=_content_hash(steps))
    for sid in ("s1", "s2"):
        attempt = store.reserve_step("t1", sid)
        store.mark_needs_decision("t1", sid, attempt_id=attempt, outcome_ref=f"ref-{sid}")
    task = store.get("t1")
    step = next(s for s in task.steps if s.step_id == "s1")

    from my_crew.agent.coordinator_nodes.stuck_decision import _give_up

    result = _give_up(_deps(store), task, step, "hết cách")

    assert result.action == "step_skipped"
    assert store.get_step("t1", "s1").status == "done"
    assert store.get("t1").status != "stalled"
