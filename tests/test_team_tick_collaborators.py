"""`team_tick_collaborators.make_escalate` (v12 final-review escalation-reachability
redesign): the office-room `milestone` append must happen FIRST and UNCONDITIONALLY,
before any attempt at a direct coordinator Telegram send — the admin agent's
milestone-mirror ops-tick (`milestone_mirror_runner`) polls the room and DMs the CEO
regardless of whether the coordinator has its own Telegram binding, so a coordinator
with no bot of its own (the 1-click bootstrap default) still has a working escalation
path via the mirror.
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

from my_crew.runtime.office_room_store import OFFICE_ROOM_ID, OfficeRoomStore
from my_crew.runtime.team_task_steps import TeamStep
from my_crew.runtime.team_task_store import TeamTask
from my_crew.runtime.team_tick_collaborators import make_escalate


@pytest.fixture(autouse=True)
def _isolated_team_tasks_root(monkeypatch, tmp_path):
    """Every test in this module writes through the shared cross-agent root (store,
    artifacts, office-room appends) — pin it to tmp_path so no test can touch the
    real install's .data (the office room is a real user-visible surface)."""
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)

def _task(task_id="t1"):
    return TeamTask(
        id=task_id, title="Demo task", original_request="lam demo", status="running",
        created_at="2026-07-10T00:00:00", assigned_by="ceo", cost_usd_total=0.0,
        plan_hash="h", decompose_cost_usd=0.0, aggregate_cost_usd=0.0, escalated_at=None,
    )


def _step():
    return TeamStep(
        task_id="t1", step_id="s1", seq=1, title="draft", assigned_to="agent-a", deps=(),
        status="running", outcome_ref=None, cost_usd=None, attempt_id="attempt-1",
        child_pid=None, spawned_at=None, last_seen=None, lease_expires_at=None,
        escalated_at=None, approval_id=None, acceptance="",
        step_type="work", needs_review=False, system_inserted=False,
        parent_step_id=None, review_round=0,
    )


def _loaded_no_telegram():
    return SimpleNamespace(config=SimpleNamespace(telegram=None, slack_external_channels=()))


def test_escalate_appends_the_room_milestone_even_with_no_coordinator_telegram_binding(
    tmp_path, monkeypatch,
):
    """The headline regression this test pins: a coordinator with NO Telegram binding
    of its own must still leave a trace in the office room — the mirror path is the
    ONLY way the CEO ever hears about this escalation, so a silent early-return here
    would make the escalation vanish entirely."""
    from my_crew.runtime import team_task_paths

    monkeypatch.setattr(team_task_paths, "DATA_DIR", tmp_path)

    escalate = make_escalate(_loaded_no_telegram(), settings=SimpleNamespace())
    escalate(_task(), _step(), "step_failed", "bước draft thất bại 3 lần")

    store = OfficeRoomStore(team_task_paths.team_tasks_root() / "office_room.sqlite3")
    try:
        office_rows = store.list(OFFICE_ROOM_ID)
        task_rows = store.list("t1")
    finally:
        store.close()

    assert len(office_rows) == 1
    assert office_rows[0].kind == "milestone"
    assert office_rows[0].body["task_title"] == "Demo task"
    assert office_rows[0].body["milestone"] == "step_failed"
    # also_office=True mirrors the SAME event into both the task room and "office".
    assert len(task_rows) == 1
    assert task_rows[0].kind == "milestone"


def test_escalate_room_append_survives_even_if_the_gateway_import_itself_would_fail(
    tmp_path, monkeypatch,
):
    """The room append is wrapped in its OWN try/except, independent of the Telegram
    send block below it — an exception constructing the gateway (bad settings, missing
    env) must not retroactively un-append the room event that already succeeded."""
    from my_crew.runtime import team_task_paths

    monkeypatch.setattr(team_task_paths, "DATA_DIR", tmp_path)

    telegram = SimpleNamespace(bot_token_env="X", chat_ids=("op-1",), poll_minutes=5,
                               ops_operator_id="op-1")
    loaded = SimpleNamespace(config=SimpleNamespace(telegram=telegram, slack_external_channels=()))

    class _ExplodingGateway:
        def __init__(self, *a, **kw):
            raise RuntimeError("gateway boom")

    monkeypatch.setattr("my_crew.actions.action_gateway.ActionGateway", _ExplodingGateway)

    escalate = make_escalate(loaded, settings=SimpleNamespace())
    escalate(_task(), _step(), "step_failed", "bước draft thất bại")  # must not raise

    store = OfficeRoomStore(team_task_paths.team_tasks_root() / "office_room.sqlite3")
    try:
        office_rows = store.list(OFFICE_ROOM_ID)
    finally:
        store.close()
    assert len(office_rows) == 1


def test_escalate_step_none_omits_step_id_from_dedup_hint_without_crashing(tmp_path, monkeypatch):
    """A task-level escalation (no single step responsible, e.g. `task_stuck`) passes
    `step=None` — must not crash on `step.step_id`."""
    from my_crew.runtime import team_task_paths

    monkeypatch.setattr(team_task_paths, "DATA_DIR", tmp_path)

    escalate = make_escalate(_loaded_no_telegram(), settings=SimpleNamespace())
    escalate(_task(), None, "task_stuck", "việc bị kẹt")  # must not raise

    store = OfficeRoomStore(team_task_paths.team_tasks_root() / "office_room.sqlite3")
    try:
        office_rows = store.list(OFFICE_ROOM_ID)
    finally:
        store.close()
    assert len(office_rows) == 1
    assert office_rows[0].body["milestone"] == "task_stuck"


@pytest.mark.parametrize("event_kind", [
    "task_stalled_dead_step", "plan_hash_mismatch", "review_rounds_exhausted",
    "cost_cap_exceeded",
])
def test_task_level_stall_escalations_append_the_constant_amend_suggestion(
    tmp_path, monkeypatch, event_kind,
):
    """Every event_kind the ticker uses when it just moved the WHOLE task to `stalled`
    gets a CONSTANT-template amend suggestion appended, with the task id interpolated —
    never anything derived from task/step title or other task content (which could
    itself carry text absorbed from a hostile brief/artifact)."""
    from my_crew.runtime import team_task_paths

    monkeypatch.setattr(team_task_paths, "DATA_DIR", tmp_path)

    escalate = make_escalate(_loaded_no_telegram(), settings=SimpleNamespace())
    escalate(_task("stalled-task-1"), None, event_kind, "việc bị dừng — cần CEO xem lại.")

    store = OfficeRoomStore(team_task_paths.team_tasks_root() / "office_room.sqlite3")
    try:
        office_rows = store.list(OFFICE_ROOM_ID)
    finally:
        store.close()
    assert len(office_rows) == 1
    message = office_rows[0].body["message"]
    assert "chỉnh kế hoạch stalled-task-1: <yêu cầu>" in message


def test_step_level_escalation_does_not_get_the_amend_suggestion(tmp_path, monkeypatch):
    """A single-step failure (`step_failed`) does not by itself mean the WHOLE task is
    stalled — a later tick's other-step-completes/retry path may still resolve it, so
    this event_kind must NOT carry the task-replan suggestion."""
    from my_crew.runtime import team_task_paths

    monkeypatch.setattr(team_task_paths, "DATA_DIR", tmp_path)

    escalate = make_escalate(_loaded_no_telegram(), settings=SimpleNamespace())
    escalate(_task(), _step(), "step_failed", "bước draft thất bại 3 lần")

    store = OfficeRoomStore(team_task_paths.team_tasks_root() / "office_room.sqlite3")
    try:
        office_rows = store.list(OFFICE_ROOM_ID)
    finally:
        store.close()
    assert "chỉnh kế hoạch" not in office_rows[0].body["message"]


# --- v63 make_aggregate: passed-with-notes review rows surface their notes ------------


def _step_row(step_id, seq, *, step_type="work", parent=None, review_round=0, title=None):
    return TeamStep(
        task_id="t1", step_id=step_id, seq=seq, title=title or step_id,
        assigned_to="agent-a", deps=(), status="done", outcome_ref=None, cost_usd=None,
        attempt_id=f"attempt-{seq}", child_pid=None, spawned_at=None, last_seen=None,
        lease_expires_at=None, escalated_at=None, approval_id=None, acceptance="",
        step_type=step_type, needs_review=False, system_inserted=step_type != "work",
        parent_step_id=parent, review_round=review_round,
    )


def _aggregate_fallback(tmp_path, monkeypatch, task):
    """Run make_aggregate's no-LLM path (no openrouter key → deterministic join)."""
    from my_crew.runtime import team_task_paths
    from my_crew.runtime.team_tick_collaborators import make_aggregate

    monkeypatch.setattr(team_task_paths, "DATA_DIR", tmp_path)
    aggregate = make_aggregate(
        _loaded_no_telegram(), settings=SimpleNamespace(openrouter_api_key=""),
    )
    summary, cost = aggregate(task)
    assert cost is None
    return summary


def test_aggregate_includes_notes_of_a_passed_with_notes_review(tmp_path, monkeypatch):
    from my_crew.agent.team_task_artifact import (
        write_review_verdict_artifact,
        write_step_artifact,
    )

    content = _step_row("s1", 1, title="draft báo cáo")
    review = _step_row("s1-review-0-0", 2, step_type="review", parent="s1",
                       title="Soát chéo: draft báo cáo")
    task = _task()
    task = type(task)(**{**task.__dict__, "steps": (content, review)})

    write_step_artifact(tmp_path, "t1", 1, {"result_text": "nội dung", "version": "attempt-1"})
    write_review_verdict_artifact(
        tmp_path, "t1", 1, 0,
        {"passed": True, "failures": [], "notes": ["nên thêm biểu đồ"],
         "reviewed_version": "attempt-1", "round": 0, "result_text": "nội dung"},
    )

    summary = _aggregate_fallback(tmp_path, monkeypatch, task)
    assert "góp ý thêm: nên thêm biểu đồ" in summary
    assert "nội dung" in summary  # the content step's own line is still there


def test_aggregate_omits_review_rows_without_notes(tmp_path, monkeypatch):
    from my_crew.agent.team_task_artifact import (
        write_review_verdict_artifact,
        write_step_artifact,
    )

    content = _step_row("s1", 1, title="draft báo cáo")
    review = _step_row("s1-review-0-0", 2, step_type="review", parent="s1",
                       title="Soát chéo: draft báo cáo")
    task = _task()
    task = type(task)(**{**task.__dict__, "steps": (content, review)})

    write_step_artifact(tmp_path, "t1", 1, {"result_text": "nội dung", "version": "attempt-1"})
    write_review_verdict_artifact(
        tmp_path, "t1", 1, 0,
        {"passed": True, "failures": [], "notes": [],
         "reviewed_version": "attempt-1", "round": 0, "result_text": "nội dung"},
    )

    summary = _aggregate_fallback(tmp_path, monkeypatch, task)
    # A clean pass adds no line of its own — the summary lists only real content steps.
    assert "Soát chéo" not in summary


# --- v63 stall escalation: evidence pack + one-touch suggestions ----------------------


def test_review_exhausted_escalation_carries_evidence_and_one_touch_commands(
    tmp_path, monkeypatch,
):
    from my_crew.agent.team_task_artifact import write_review_verdict_artifact
    from my_crew.runtime import team_task_paths

    monkeypatch.setattr(team_task_paths, "DATA_DIR", tmp_path)

    content = _step_row("s1", 1, title="draft báo cáo")
    review = _step_row("s1-review-2-2", 2, step_type="review", parent="s1", review_round=2)
    task = _task("stalled-task-9")
    task = type(task)(**{**task.__dict__, "steps": (content, review)})
    write_review_verdict_artifact(
        tmp_path, "stalled-task-9", 1, 2,
        {"passed": False, "failures": ["thiếu số liệu quý 2"], "notes": [],
         "reviewed_version": "attempt-1", "round": 2, "result_text": "x"},
    )

    escalate = make_escalate(_loaded_no_telegram(), settings=SimpleNamespace())
    escalate(task, content, "review_rounds_exhausted", "việc bị dừng — cần CEO xem lại.")

    store = OfficeRoomStore(team_task_paths.team_tasks_root() / "office_room.sqlite3")
    try:
        message = store.list(OFFICE_ROOM_ID)[0].body["message"]
    finally:
        store.close()
    assert "Lý do vòng soát cuối không đạt" in message
    assert "thiếu số liệu quý 2" in message
    assert "accept_stalled_result stalled-task-9" in message
    assert "retry_stalled_step stalled-task-9" in message
    assert "drop_stalled_step stalled-task-9" in message
    # The amend suggestion (pre-v63 behavior) must still be there too.
    assert "chỉnh kế hoạch stalled-task-9" in message


def test_dead_step_stall_gets_one_touch_but_no_review_evidence(tmp_path, monkeypatch):
    from my_crew.runtime import team_task_paths

    monkeypatch.setattr(team_task_paths, "DATA_DIR", tmp_path)

    escalate = make_escalate(_loaded_no_telegram(), settings=SimpleNamespace())
    escalate(_task("stalled-task-8"), None, "task_stalled_dead_step",
             "việc bị dừng: bước chết.")

    store = OfficeRoomStore(team_task_paths.team_tasks_root() / "office_room.sqlite3")
    try:
        message = store.list(OFFICE_ROOM_ID)[0].body["message"]
    finally:
        store.close()
    assert "retry_stalled_step stalled-task-8" in message
    assert "Lý do vòng soát cuối" not in message


# --- v77 sprint: the one content step's artifact IS the deliverable -------------------


def _sprint_task(tmp_path, monkeypatch, *, result_text, steps=None):
    from my_crew.agent.team_task_artifact import write_step_artifact
    from my_crew.runtime import team_task_paths

    monkeypatch.setattr(team_task_paths, "DATA_DIR", tmp_path)
    task = _task()
    rows = steps if steps is not None else (_step_row("sprint", 1, step_type="sprint"),)
    task = type(task)(**{**task.__dict__, "steps": rows})
    write_step_artifact(tmp_path, "t1", 1, {"result_text": result_text,
                                            "version": "attempt-1"})
    return task


def test_a_sprint_task_delivers_its_full_result_without_an_llm_call(tmp_path, monkeypatch):
    """The sprint artifact was already written to be read by the CEO. Summarizing it
    would pay a second call to compress it — and the aggregate's `parts` snippets are
    cut at 500 chars, so the summary would be built from a truncated copy."""
    from my_crew.runtime.team_tick_collaborators import make_aggregate

    long_report = "Báo cáo đầy đủ. " + ("chi tiết " * 200)
    task = _sprint_task(tmp_path, monkeypatch, result_text=long_report)

    def _boom(_settings):
        raise AssertionError("a sprint task must not reach the aggregate LLM call")

    monkeypatch.setattr("my_crew.llm.client.LlmClient", _boom)
    aggregate = make_aggregate(
        _loaded_no_telegram(), settings=SimpleNamespace(openrouter_api_key="sk-test"),
    )
    summary, cost = aggregate(task)

    assert summary == long_report.strip()
    assert cost is None


def test_a_sprint_task_with_a_review_row_still_delivers_directly(tmp_path, monkeypatch):
    """A supervised band mints one review row next to the sprint step. That does not
    make the task multi-step — the sprint artifact is still the whole deliverable."""
    from my_crew.runtime.team_tick_collaborators import make_aggregate

    rows = (_step_row("sprint", 1, step_type="sprint"),
            _step_row("sprint-review-0-0", 2, step_type="review", parent="sprint"))
    task = _sprint_task(tmp_path, monkeypatch, result_text="nội dung sprint", steps=rows)

    aggregate = make_aggregate(
        _loaded_no_telegram(), settings=SimpleNamespace(openrouter_api_key=""),
    )
    summary, _cost = aggregate(task)
    assert summary == "nội dung sprint"


def test_a_sprint_task_whose_artifact_vanished_falls_back_to_the_normal_aggregate(
    tmp_path, monkeypatch,
):
    """Missing artifact must degrade to the usual summary, never deliver an empty message."""
    from my_crew.runtime import team_task_paths
    from my_crew.runtime.team_tick_collaborators import make_aggregate

    monkeypatch.setattr(team_task_paths, "DATA_DIR", tmp_path)
    task = _task()
    task = type(task)(**{**task.__dict__,
                         "steps": (_step_row("sprint", 1, step_type="sprint"),)})

    aggregate = make_aggregate(
        _loaded_no_telegram(), settings=SimpleNamespace(openrouter_api_key=""),
    )
    summary, _cost = aggregate(task)
    assert "đã hoàn tất" in summary


def test_a_multi_step_task_is_untouched_by_the_sprint_shortcut(tmp_path, monkeypatch):
    from my_crew.runtime.team_tick_collaborators import make_aggregate

    rows = (_step_row("s1", 1), _step_row("s2", 2))
    task = _sprint_task(tmp_path, monkeypatch, result_text="nội dung một", steps=rows)

    aggregate = make_aggregate(
        _loaded_no_telegram(), settings=SimpleNamespace(openrouter_api_key=""),
    )
    summary, _cost = aggregate(task)
    assert "đã hoàn tất" in summary
    assert "s2" in summary


def test_the_workroom_link_survives_a_report_too_long_to_send():
    """Truncation cuts from the END, so a long sprint report used to lose both its tail
    AND the link that was the CEO's only way to reach the full text."""
    from my_crew.actions import telegram_write

    tail = "\n\n🔎 Chi tiết đầy đủ: http://localhost:8765/room/abc"
    text = telegram_write.with_tail("x" * 9000, tail)
    assert text.endswith(tail)
    assert len(text) <= telegram_write._MAX_TEXT_CHARS
    assert "cắt bớt" in text


def test_a_short_report_keeps_its_body_intact():
    from my_crew.actions import telegram_write

    assert telegram_write.with_tail("ngắn", "\n\nlink") == "ngắn\n\nlink"


def test_a_sprint_dead_end_escalation_carries_the_upgrade_hint(tmp_path, monkeypatch):
    """End-to-end through the room append (the path that always runs): the CEO reading
    a `gave_up` milestone for a sprint task must see the `team:` remedy in the SAME
    message body, not only in a Telegram fast path that may have no binding at all."""
    from my_crew.runtime import team_task_paths
    from my_crew.runtime.team_tick_collaborators import _SPRINT_UPGRADE_SUGGESTION

    monkeypatch.setattr(team_task_paths, "DATA_DIR", tmp_path)

    sprint_step = dataclasses.replace(_step(), step_type="sprint")
    task = dataclasses.replace(_task(), steps=(sprint_step,))
    escalate = make_escalate(_loaded_no_telegram(), settings=SimpleNamespace())
    escalate(task, sprint_step, "gave_up", "Việc 'Demo task' KHÔNG LÀM ĐƯỢC.")

    store = OfficeRoomStore(team_task_paths.team_tasks_root() / "office_room.sqlite3")
    try:
        rows = store.list("t1")
    finally:
        store.close()

    assert rows[0].body["message"].endswith(_SPRINT_UPGRADE_SUGGESTION)
    assert "KHÔNG LÀM ĐƯỢC" in rows[0].body["message"]


def test_a_team_task_dead_end_escalation_is_byte_identical_to_before(tmp_path, monkeypatch):
    """The hint must not leak into normal team tasks — `gave_up` there already carries
    its own honest summary and has no mode to switch to."""
    from my_crew.runtime import team_task_paths

    monkeypatch.setattr(team_task_paths, "DATA_DIR", tmp_path)

    task = dataclasses.replace(_task(), steps=(_step(),))
    escalate = make_escalate(_loaded_no_telegram(), settings=SimpleNamespace())
    escalate(task, _step(), "gave_up", "không làm được")

    store = OfficeRoomStore(team_task_paths.team_tasks_root() / "office_room.sqlite3")
    try:
        rows = store.list("t1")
    finally:
        store.close()

    assert rows[0].body["message"] == "không làm được"
