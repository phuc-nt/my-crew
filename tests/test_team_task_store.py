"""Cross-agent team-task store (v12 M28a): plan round-trip, lease semantics, WAL
concurrency smoke, cost roll-up.

Load-bearing:
- `next_pending_step` respects `deps` (seq order + dependency-done gate).
- `sum_cost` = step costs + decompose + aggregate.
- `reserve_step` issues a fresh attempt_id every call; `verify_attempt` distinguishes
  the CURRENT lease from a stale/forged one (the worker's no-op guard).
- Lease clock: reserved-but-not-heartbeated expires after the TTL; a heartbeat/re-
  reserve resets it. A dead-before-artifact step is re-reservable (a fresh attempt_id
  replaces the old one) once its lease is expired.
- WAL + busy_timeout tolerates two real concurrent writer connections without
  "database is locked".
- worker.py's `team-step` branch (`_run_team_step_kind`) writes an outcome artifact +
  run-event on EVERY exit path (done/error/rejected) and rejects a bad/stale/absent
  attempt_id as a clean no-op without ever running the graph.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from src.agent.task_decomposition import decomposition_content_hash
from src.runtime.team_task_store import TeamTaskStore


def _store(tmp_path, **kw) -> TeamTaskStore:
    return TeamTaskStore(tmp_path / "team_tasks.sqlite3", **kw)


def _content_hash(steps: list[dict]) -> str:
    """The REAL dispatch-time hash for a given step-dict list — the ticker's
    `_verify_plan_hash` (MEDIUM) recomputes this on every tick, so fixtures must
    persist the matching hash, not an arbitrary literal, or every tick would stall."""
    return decomposition_content_hash(SimpleNamespace(steps=[
        SimpleNamespace(
            step_id=s["step_id"], title=s["title"], assigned_to=s["assigned_to"],
            deps=tuple(s.get("deps", ())), needs_shell=bool(s.get("needs_shell", False)),
        )
        for s in steps
    ]))


def _plan(store: TeamTaskStore, task_id="t1") -> None:
    steps = [
        {"step_id": "s1", "title": "draft", "assigned_to": "agent-a", "deps": []},
        {"step_id": "s2", "title": "review", "assigned_to": "agent-b", "deps": ["s1"]},
        {"step_id": "s3", "title": "publish", "assigned_to": "agent-a", "deps": ["s2"]},
    ]
    store.create_task(task_id=task_id, title="demo", original_request="chuẩn bị demo")
    store.set_plan(task_id, steps, plan_hash=_content_hash(steps))


# --- plan round-trip -------------------------------------------------------------


def test_create_task_and_set_plan_round_trip(tmp_path):
    store = _store(tmp_path)
    _plan(store)
    task = store.get("t1")
    assert task is not None
    assert task.status == "open"
    assert task.plan_hash == _content_hash([
        {"step_id": "s1", "title": "draft", "assigned_to": "agent-a", "deps": []},
        {"step_id": "s2", "title": "review", "assigned_to": "agent-b", "deps": ["s1"]},
        {"step_id": "s3", "title": "publish", "assigned_to": "agent-a", "deps": ["s2"]},
    ])
    assert [s.step_id for s in task.steps] == ["s1", "s2", "s3"]
    assert task.steps[2].deps == ("s2",)
    store.close()


def test_needs_shell_round_trips(tmp_path):
    """v45: needs_shell persists + round-trips (default False; True honored)."""
    store = _store(tmp_path)
    steps = [
        {"step_id": "s1", "title": "read", "assigned_to": "agent-a", "deps": []},
        {"step_id": "s2", "title": "run", "assigned_to": "agent-a", "deps": ["s1"],
         "needs_shell": True},
    ]
    store.create_task(task_id="tsh", title="demo", original_request="x")
    store.set_plan("tsh", steps, plan_hash=_content_hash(steps))
    task = store.get("tsh")
    by_id = {s.step_id: s for s in task.steps}
    assert by_id["s1"].needs_shell is False  # default
    assert by_id["s2"].needs_shell is True   # honored
    store.close()


# --- confirm_plan (TOCTOU-proof draft -> open) ------------------------------------


def test_confirm_plan_flips_planning_task_to_open_on_matching_hash(tmp_path):
    store = _store(tmp_path)
    steps = [{"step_id": "s1", "title": "draft", "assigned_to": "agent-a", "deps": []}]
    plan_hash = _content_hash(steps)
    store.create_task(task_id="t1", title="demo", original_request="demo")
    store.set_draft_plan("t1", steps, plan_hash)
    assert store.get("t1").status == "planning"

    confirmed = store.confirm_plan("t1", plan_hash)

    assert confirmed is True
    task = store.get("t1")
    assert task.status == "open"
    assert task.plan_hash == plan_hash
    assert [s.step_id for s in task.steps] == ["s1"]  # steps unchanged, not re-written
    store.close()


def test_confirm_plan_rejects_mismatched_hash_leaves_task_in_planning(tmp_path):
    store = _store(tmp_path)
    steps = [{"step_id": "s1", "title": "draft", "assigned_to": "agent-a", "deps": []}]
    store.create_task(task_id="t1", title="demo", original_request="demo")
    store.set_draft_plan("t1", steps, _content_hash(steps))

    confirmed = store.confirm_plan("t1", "stale-or-tampered-hash")

    assert confirmed is False
    assert store.get("t1").status == "planning"  # untouched
    store.close()


def test_confirm_plan_missing_task_is_a_clean_false(tmp_path):
    store = _store(tmp_path)
    assert store.confirm_plan("no-such-task", "any-hash") is False
    store.close()


def test_confirm_plan_second_call_after_already_confirmed_is_a_clean_false(tmp_path):
    """Confirm is not idempotently re-appliable — once a task is `open`, `confirm_plan`
    only ever flips a `planning` row, so a duplicate confirm call (e.g. a retried chat
    message) is a no-op False, not an error and not a second state transition."""
    store = _store(tmp_path)
    steps = [{"step_id": "s1", "title": "draft", "assigned_to": "agent-a", "deps": []}]
    plan_hash = _content_hash(steps)
    store.create_task(task_id="t1", title="demo", original_request="demo")
    store.set_draft_plan("t1", steps, plan_hash)
    assert store.confirm_plan("t1", plan_hash) is True

    second = store.confirm_plan("t1", plan_hash)

    assert second is False
    assert store.get("t1").status == "open"
    store.close()


def test_next_pending_step_respects_deps_and_seq(tmp_path):
    store = _store(tmp_path)
    _plan(store)
    first = store.next_pending_step("t1")
    assert first is not None and first.step_id == "s1"
    # s2/s3 blocked until s1 is done
    store.mark_done("t1", "s1", outcome_ref="step-1.json")
    second = store.next_pending_step("t1")
    assert second is not None and second.step_id == "s2"
    store.close()


def test_next_pending_step_none_when_nothing_ready(tmp_path):
    store = _store(tmp_path)
    _plan(store)
    store.reserve_step("t1", "s1")  # now running, not pending
    assert store.next_pending_step("t1") is None  # s2/s3 blocked, s1 not pending
    store.close()


def test_list_open_excludes_terminal_statuses(tmp_path):
    store = _store(tmp_path)
    _plan(store)
    store.create_task(task_id="t2", title="done task")
    store.set_task_status("t2", "done")
    open_tasks = store.list_open()
    assert {t.id for t in open_tasks} == {"t1"}
    store.close()


def test_set_task_status_rejects_unknown(tmp_path):
    store = _store(tmp_path)
    _plan(store)
    with pytest.raises(ValueError):
        store.set_task_status("t1", "bogus")
    store.close()


# --- cost roll-up ------------------------------------------------------------------


def test_sum_cost_includes_steps_decompose_and_aggregate(tmp_path):
    store = _store(tmp_path)
    _plan(store)
    store.mark_done("t1", "s1", cost_usd=0.10)
    store.mark_done("t1", "s2", cost_usd=0.20)
    store.record_task_cost("t1", decompose=0.05)
    store.record_task_cost("t1", aggregate=0.03)
    assert store.sum_cost("t1") == pytest.approx(0.10 + 0.20 + 0.05 + 0.03)
    store.close()


def test_mark_done_accumulates_cost_usd_total(tmp_path):
    store = _store(tmp_path)
    _plan(store)
    store.mark_done("t1", "s1", cost_usd=0.10)
    store.mark_done("t1", "s2", cost_usd=0.25)
    task = store.get("t1")
    assert task.cost_usd_total == pytest.approx(0.35)
    store.close()


# --- lease semantics (reserve / verify / expiry) ------------------------------------


def test_reserve_step_issues_fresh_attempt_id_each_call(tmp_path):
    store = _store(tmp_path)
    _plan(store)
    a1 = store.reserve_step("t1", "s1")
    a2 = store.reserve_step("t1", "s1")
    assert a1 != a2
    # only the LATEST attempt verifies — the double-spawn guard's core property
    assert store.verify_attempt("t1", "s1", a2) is True
    assert store.verify_attempt("t1", "s1", a1) is False
    store.close()


def test_verify_attempt_false_for_absent_or_wrong(tmp_path):
    store = _store(tmp_path)
    _plan(store)
    assert store.verify_attempt("t1", "s1", "never-reserved") is False  # still pending
    attempt = store.reserve_step("t1", "s1")
    assert store.verify_attempt("t1", "s1", "wrong-token") is False
    assert store.verify_attempt("t1", "s1", attempt) is True
    store.close()


def test_lease_reserved_not_yet_spawned_not_expired_immediately(tmp_path):
    """Reserved-but-not-spawned: within the TTL, the lease is NOT expired — a second
    reserve must not race the legitimate spawn that's still starting up."""
    store = _store(tmp_path, lease_ttl_s=300)
    _plan(store)
    store.reserve_step("t1", "s1")
    assert store.lease_expired("t1", "s1") is False
    store.close()


def test_lease_alive_heartbeat_keeps_it_from_expiring(tmp_path):
    store = _store(tmp_path, lease_ttl_s=1)
    _plan(store)
    store.reserve_step("t1", "s1")
    time.sleep(0.5)
    store.heartbeat("t1", "s1")  # pushes lease_expires_at another 1s out
    time.sleep(0.7)  # 1.2s since reserve, but only 0.7s since heartbeat
    assert store.lease_expired("t1", "s1") is False
    store.close()


def test_lease_dead_before_artifact_is_reservable_after_expiry(tmp_path):
    """Dead-pre-artifact: lease TTL elapses with no heartbeat and no outcome (status
    stays 'running', no outcome_ref) — the double-spawn guard permits re-reserve
    (the caller checks lease_expired() AND artifact-absence; this test verifies the
    lease-clock half)."""
    store = _store(tmp_path, lease_ttl_s=1)
    _plan(store)
    first = store.reserve_step("t1", "s1")
    time.sleep(1.2)
    assert store.lease_expired("t1", "s1") is True
    step = store.get_step("t1", "s1")
    assert step.status == "running" and step.outcome_ref is None  # no artifact recorded
    second = store.reserve_step("t1", "s1")  # re-reserve after expiry — legitimate
    assert second != first
    assert store.verify_attempt("t1", "s1", first) is False  # old lease now dead
    assert store.verify_attempt("t1", "s1", second) is True
    store.close()


def test_pending_step_has_no_lease_and_counts_as_expired(tmp_path):
    store = _store(tmp_path)
    _plan(store)
    assert store.lease_expired("t1", "s2") is True  # never reserved
    store.close()


def test_record_spawn_and_get_step_pid(tmp_path):
    store = _store(tmp_path)
    _plan(store)
    store.reserve_step("t1", "s1")
    store.record_spawn("t1", "s1", 12345)
    step = store.get_step("t1", "s1")
    assert step.child_pid == 12345
    store.close()


def test_mark_failed_records_outcome_ref(tmp_path):
    store = _store(tmp_path)
    _plan(store)
    store.reserve_step("t1", "s1")
    store.mark_failed("t1", "s1", outcome_ref="step-1.json")
    step = store.get_step("t1", "s1")
    assert step.status == "failed"
    assert step.outcome_ref == "step-1.json"
    store.close()


def test_mark_awaiting_approval_status(tmp_path):
    store = _store(tmp_path)
    _plan(store)
    store.reserve_step("t1", "s1")
    store.mark_awaiting_approval("t1", "s1")
    assert store.get_step("t1", "s1").status == "awaiting_approval"
    store.close()


def test_append_outcome_sets_ref_without_changing_status(tmp_path):
    store = _store(tmp_path)
    _plan(store)
    store.reserve_step("t1", "s1")
    store.append_outcome("t1", "s1", "step-1.json")
    step = store.get_step("t1", "s1")
    assert step.outcome_ref == "step-1.json"
    assert step.status == "running"  # append_outcome alone does not change status
    store.close()


# --- WAL / busy_timeout concurrency smoke -------------------------------------------


def test_wal_mode_is_active(tmp_path):
    store = _store(tmp_path)
    mode = store._conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
    store.close()


def test_concurrent_writers_do_not_lock(tmp_path):
    """Two real connections to the SAME db file (mirrors coordinator-poll + step-writes-
    cost) hammer writes concurrently. Without WAL + busy_timeout this raises
    'database is locked'; with it, both threads complete cleanly."""
    db_path = tmp_path / "team_tasks.sqlite3"
    store = _store(tmp_path)
    _plan(store)
    errors: list[Exception] = []

    def _writer_a():
        try:
            s = TeamTaskStore(db_path)
            for _i in range(20):
                s.record_task_cost("t1", decompose=0.001)
            s.close()
        except sqlite3.OperationalError as exc:  # noqa: BLE001 — captured for assertion
            errors.append(exc)

    def _writer_b():
        try:
            s = TeamTaskStore(db_path)
            for i in range(20):
                s.heartbeat("t1", "s1") if s.get_step("t1", "s1") else None
                s.reserve_step("t1", "s2") if i == 0 else None
            s.close()
        except sqlite3.OperationalError as exc:  # noqa: BLE001 — captured for assertion
            errors.append(exc)

    t1 = threading.Thread(target=_writer_a)
    t2 = threading.Thread(target=_writer_b)
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)
    assert not errors, f"concurrent writers hit a locking error: {errors}"
    store.close()


def test_lease_expired_now_kwarg_is_honored(tmp_path):
    store = _store(tmp_path, lease_ttl_s=300)
    _plan(store)
    store.reserve_step("t1", "s1")
    far_future = datetime.now(UTC) + timedelta(seconds=301)
    assert store.lease_expired("t1", "s1", now=far_future) is True
    store.close()


def test_default_lease_ttl_is_600s(tmp_path):
    from src.runtime.team_task_store import DEFAULT_LEASE_TTL_S

    assert DEFAULT_LEASE_TTL_S == 600
    store = _store(tmp_path)  # no lease_ttl_s override -> uses the module default
    _plan(store)
    store.reserve_step("t1", "s1")
    # 599s in: still alive (under the 600s default). 601s in: expired.
    still_alive = datetime.now(UTC) + timedelta(seconds=599)
    assert store.lease_expired("t1", "s1", now=still_alive) is False
    now_expired = datetime.now(UTC) + timedelta(seconds=601)
    assert store.lease_expired("t1", "s1", now=now_expired) is True
    store.close()


# --- double-spawn guard: attempt_id-scoped terminal writes ---------------------------
#
# The two scenarios `write_handlers.py`'s / the store module's own docstrings describe
# as the actual double-spawn prevention (distinct from the lease-clock tests above,
# which only prove WHEN a re-reserve is permitted, not what happens to a stale
# worker's write once one occurs):


def test_stale_worker_terminal_write_after_a_legitimate_re_reserve_is_a_no_op(tmp_path):
    """Scenario 1: lease expires, the ticker re-reserves (a NEW attempt_id), and the
    ORIGINAL (now-stale) worker then finally gets around to writing its terminal
    status using its OLD attempt_id. That write must be a silent no-op — it must
    never clobber the new attempt's row nor double-count cost."""
    store = _store(tmp_path, lease_ttl_s=1)
    _plan(store)
    original_attempt = store.reserve_step("t1", "s1")
    store.record_spawn("t1", "s1", pid=111)

    # lease dies, ticker (or the caller acting as the ticker) re-reserves a fresh attempt
    import time

    time.sleep(1.2)
    assert store.lease_expired("t1", "s1") is True
    new_attempt = store.reserve_step("t1", "s1")
    assert new_attempt != original_attempt

    # the STALE worker (still holding original_attempt) now finally writes its
    # terminal status + cost — this must be rejected as a no-op.
    updated = store.mark_done(
        "t1", "s1", outcome_ref="stale-outcome.json", cost_usd=99.0,
        attempt_id=original_attempt,
    )
    assert updated is False

    # the row still reflects the NEW attempt, untouched by the stale write.
    step = store.get_step("t1", "s1")
    assert step.status == "running"
    assert step.attempt_id == new_attempt
    assert step.outcome_ref is None
    assert step.cost_usd is None
    # cost was never double-counted onto the task total either.
    task = store.get("t1")
    assert task.cost_usd_total == 0.0
    store.close()


def test_mark_timeout_with_stale_attempt_id_after_re_reserve_is_a_no_op(tmp_path):
    """`mark_timeout` (MEDIUM: ticker-side terminal writes attempt-guarded) must reject
    a stale attempt_id exactly like `mark_done`/`mark_failed` — a ticker that read a
    step's row, then raced a re-reservation before writing `timeout`, must not clobber
    the newer attempt's row."""
    store = _store(tmp_path, lease_ttl_s=1)
    _plan(store)
    original_attempt = store.reserve_step("t1", "s1")
    store.record_spawn("t1", "s1", pid=111)

    import time

    time.sleep(1.2)
    new_attempt = store.reserve_step("t1", "s1")
    assert new_attempt != original_attempt

    updated = store.mark_timeout("t1", "s1", attempt_id=original_attempt)
    assert updated is False

    step = store.get_step("t1", "s1")
    assert step.status == "running"
    assert step.attempt_id == new_attempt
    store.close()


def test_mark_timeout_with_matching_attempt_id_applies(tmp_path):
    store = _store(tmp_path)
    _plan(store)
    attempt_id = store.reserve_step("t1", "s1")
    updated = store.mark_timeout("t1", "s1", attempt_id=attempt_id)
    assert updated is True
    assert store.get_step("t1", "s1").status == "timeout"
    store.close()


def test_mark_timeout_with_no_attempt_id_always_applies(tmp_path):
    """Backward-compatible default: no `attempt_id` -> unconditional write, matching
    pre-existing behavior for any caller that doesn't hold a lease to guard with."""
    store = _store(tmp_path)
    _plan(store)
    store.reserve_step("t1", "s1")
    updated = store.mark_timeout("t1", "s1")
    assert updated is True
    assert store.get_step("t1", "s1").status == "timeout"
    store.close()


def test_expired_but_still_alive_pid_is_killed_by_ticker_and_write_not_lost(
    tmp_path,
):
    """Scenario 2: the ticker kills a lease-expired pid regardless of whether the
    process is still alive (per C1's fix), marking the step `timeout` directly
    (attempt-guarded with the step's own lease, matching `poll_running_step`'s real
    call). The step must land in a definite terminal state, never silently stuck
    `running` forever after the kill."""
    from src.agent.coordinator_graph import CoordinatorDeps, in_memory_retry_tracker, run_one_tick

    store = _store(tmp_path, lease_ttl_s=1)
    _plan(store)
    store.reserve_step("t1", "s1")
    store.record_spawn("t1", "s1", pid=222)

    import time

    time.sleep(1.2)  # lease now expired, but the (fake) pid is reported ALIVE below

    killed: list[int] = []
    escalated: list[str] = []
    deps = CoordinatorDeps(
        store=store,
        retry_tracker=in_memory_retry_tracker(),
        cost_cap_usd=2.0,
        pid_alive=lambda pid: True,  # still alive — this is the "expired+alive" branch
        kill_pid=lambda pid, attempt_id: killed.append(pid),
        escalate=lambda task, step, kind, msg: escalated.append(kind),
    )
    result = run_one_tick(deps)

    assert result.action == "timeout_escalated"
    assert killed == [222]  # killed regardless of "alive" — timeout is not silently reserved
    assert escalated == ["step_timeout"]
    step = store.get_step("t1", "s1")
    assert step.status == "timeout"  # a definite terminal state, not left "running"
    store.close()


# --- worker.py `team-step` branch integration (run_event + outcome artifact) --------


def _patch_team_tasks_root(monkeypatch, tmp_path):
    """Point the shared cross-agent root at tmp_path so the worker branch/store/
    artifact helper all agree on an isolated location for this test."""
    monkeypatch.setattr("src.runtime.team_task_paths.DATA_DIR", tmp_path)


def _fake_loaded():
    """A minimal duck-typed stand-in for LoadedProfile — `_run_graph` reads
    .soul/.project/.memory/.company_docs/.skills/.domain/.web_search, so a real
    LoadedProfile (with its many required ReportingConfig fields) is unnecessary
    ceremony for this test; `skills=()` keeps `build_skill_context` on its cheap
    no-LlmClient path (see skill_pool.build_skill_context)."""
    return SimpleNamespace(
        soul="", project="", memory="", company_docs=(), skills=(), domain="pm",
        web_search=False,
    )


def _fake_llm(monkeypatch, *, content="step output", cost=0.01):
    class _FakeResult:
        pass

    result = _FakeResult()
    result.content = content
    result.cost_usd = cost

    class _FakeLlm:
        def __init__(self, _settings):
            pass

        def complete(self, _messages):
            return result

    import src.llm.client as llm_client_mod

    monkeypatch.setattr(llm_client_mod, "LlmClient", _FakeLlm)


def test_worker_team_step_missing_flags_is_clean_no_op(tmp_path, monkeypatch):
    from src.runtime.worker import _run_team_step_kind

    _patch_team_tasks_root(monkeypatch, tmp_path)
    agent_data_dir = tmp_path / "agents" / "a1"
    rc = _run_team_step_kind(
        ["--report", "team-step"], agent_id="a1", loaded=_fake_loaded(),
        settings=None, data_dir=agent_data_dir,
    )
    assert rc == 1
    events = (agent_data_dir / "runs.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(events) == 1
    assert json.loads(events[0])["status"] == "error"
    # no valid task/step ⇒ no artifact dir created at all
    assert not (tmp_path / "artifacts" / "team-tasks").exists()


def test_worker_team_step_rejects_wrong_attempt_id_no_artifact(tmp_path, monkeypatch):
    from src.agent.team_task_artifact import read_step_artifact
    from src.runtime.worker import _run_team_step_kind

    _patch_team_tasks_root(monkeypatch, tmp_path)
    store = _store(tmp_path)
    _plan(store)
    store.reserve_step("t1", "s1")  # issues the CURRENT lease — we deliberately use a wrong one
    store.close()

    agent_data_dir = tmp_path / "agents" / "a1"
    rc = _run_team_step_kind(
        ["--report", "team-step", "--task-id", "t1", "--step-id", "s1",
         "--attempt-id", "forged-token"],
        agent_id="a1", loaded=_fake_loaded(), settings=None, data_dir=agent_data_dir,
    )
    assert rc == 1
    events = (agent_data_dir / "runs.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(events[-1])["status"] == "rejected"
    # rejected ⇒ the step never ran ⇒ no outcome artifact for it
    assert read_step_artifact(tmp_path, "t1", 1) is None


def test_worker_team_step_absent_attempt_id_on_never_reserved_step_rejected(tmp_path, monkeypatch):
    from src.runtime.worker import _run_team_step_kind

    _patch_team_tasks_root(monkeypatch, tmp_path)
    store = _store(tmp_path)
    _plan(store)  # s1 is pending, never reserved — no lease exists yet
    store.close()

    agent_data_dir = tmp_path / "agents" / "a1"
    rc = _run_team_step_kind(
        ["--report", "team-step", "--task-id", "t1", "--step-id", "s1",
         "--attempt-id", "anything"],
        agent_id="a1", loaded=_fake_loaded(), settings=None, data_dir=agent_data_dir,
    )
    assert rc == 1
    events = (agent_data_dir / "runs.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(events[-1])["status"] == "rejected"


def test_worker_team_step_done_writes_artifact_and_run_event(tmp_path, monkeypatch):
    from src.agent.team_task_artifact import read_step_artifact
    from src.config.config_builders import build_settings_from_dict
    from src.runtime.worker import _run_team_step_kind

    _patch_team_tasks_root(monkeypatch, tmp_path)
    _fake_llm(monkeypatch, content="draft output", cost=0.03)

    store = _store(tmp_path)
    _plan(store)
    attempt = store.reserve_step("t1", "s1")
    store.close()

    settings = build_settings_from_dict({"data_dir": tmp_path, "trust_mode": "guarded"})
    agent_data_dir = tmp_path / "agents" / "a1"
    rc = _run_team_step_kind(
        ["--report", "team-step", "--task-id", "t1", "--step-id", "s1",
         "--attempt-id", attempt],
        agent_id="a1", loaded=_fake_loaded(), settings=settings, data_dir=agent_data_dir,
    )
    assert rc == 0

    events = (agent_data_dir / "runs.jsonl").read_text(encoding="utf-8").strip().splitlines()
    event = json.loads(events[-1])
    assert event["status"] == "done" and event["kind"] == "team-step"
    assert event["cost_usd"] == pytest.approx(0.03)
    assert event["delivered"] is True

    store2 = _store(tmp_path)
    step = store2.get_step("t1", "s1")
    assert step.status == "done"
    assert step.cost_usd == pytest.approx(0.03)
    store2.close()

    artifact = read_step_artifact(tmp_path, "t1", 1)
    assert artifact is not None
    assert artifact["status"] == "done"
    assert artifact["result_text"] == "draft output"


def test_worker_team_step_graph_exception_writes_failed_outcome_and_error_event(
    tmp_path, monkeypatch
):
    from src.agent.team_task_artifact import read_step_artifact
    from src.config.config_builders import build_settings_from_dict
    from src.runtime.worker import _run_team_step_kind

    _patch_team_tasks_root(monkeypatch, tmp_path)

    class _BoomLlm:
        def __init__(self, _settings):
            pass

        def complete(self, _messages):
            raise RuntimeError("llm exploded")

    import src.llm.client as llm_client_mod

    monkeypatch.setattr(llm_client_mod, "LlmClient", _BoomLlm)

    store = _store(tmp_path)
    _plan(store)
    attempt = store.reserve_step("t1", "s1")
    store.close()

    settings = build_settings_from_dict({"data_dir": tmp_path, "trust_mode": "guarded"})
    agent_data_dir = tmp_path / "agents" / "a1"
    rc = _run_team_step_kind(
        ["--report", "team-step", "--task-id", "t1", "--step-id", "s1",
         "--attempt-id", attempt],
        agent_id="a1", loaded=_fake_loaded(), settings=settings, data_dir=agent_data_dir,
    )
    assert rc == 1

    events = (agent_data_dir / "runs.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(events[-1])["status"] == "error"

    store2 = _store(tmp_path)
    step = store2.get_step("t1", "s1")
    assert step.status == "failed"  # run_team_step's except-block marked it before re-raise
    store2.close()

    artifact = read_step_artifact(tmp_path, "t1", 1)
    assert artifact is not None
    assert artifact["status"] == "failed"
    assert "llm exploded" in artifact["error"]


# --- exit-3 approval-gate end to end (step -> pending_approval -> worker exit 3 ------
# -> tick leaves it alone -> approval resolved -> tick resumes) -----------------------


def test_step_paused_at_approval_gate_worker_exits_3_tick_ignores_then_resumes_after_approval(
    tmp_path, monkeypatch,
):
    """End to end for the M1 architectural substitution (`TeamTaskDeps.external_write`
    + `status` field, no LangGraph checkpointer on this graph): a step whose external
    write hits `pending_approval` must (1) make `run_team_step` return `STATUS_PAUSED`,
    (2) make the worker's `team-step` branch exit 3 and write an `awaiting_approval`
    outcome artifact + `interrupted` run-event, (3) leave the store row
    `awaiting_approval` with the lease clock paused (the ticker must not poll or
    time it out — proven directly against `run_one_tick`, same invariant
    `test_lease_clock_paused_for_awaiting_approval_step` in test_coordinator_graph.py
    proves for a manually-set row), and (4) once the CEO's approval is resolved
    out-of-band and the coordinator re-reserves the SAME step (per the module's own
    documented "no checkpointer -> re-run from scratch" design), the step re-runs
    perceive/work/deliver and completes normally this time.
    """
    import src.agent.team_task_graph as team_task_graph_mod
    from src.agent.coordinator_graph import CoordinatorDeps, in_memory_retry_tracker, run_one_tick
    from src.agent.team_task_artifact import read_step_artifact
    from src.config.config_builders import build_settings_from_dict
    from src.runtime.worker import _run_team_step_kind

    _patch_team_tasks_root(monkeypatch, tmp_path)
    _fake_llm(monkeypatch, content="draft output", cost=0.01)

    # First attempt: the step's external write is gated pending_approval (simulates a
    # Lớp B write awaiting a human decision) — wrap the REAL default_team_task_deps so
    # perceive/work/deliver's internals stay real, only external_write is injected.
    gate_open = {"approved": False}
    real_default_deps = team_task_graph_mod.default_team_task_deps

    def _patched_default_deps(**kwargs):
        deps = real_default_deps(**kwargs)
        deps.external_write = lambda _result_text: gate_open["approved"]
        return deps

    monkeypatch.setattr(team_task_graph_mod, "default_team_task_deps", _patched_default_deps)

    store = _store(tmp_path)
    _plan(store, task_id="t1")
    attempt = store.reserve_step("t1", "s1")
    store.close()

    settings = build_settings_from_dict({"data_dir": tmp_path, "trust_mode": "guarded"})
    agent_data_dir = tmp_path / "agents" / "a1"

    rc = _run_team_step_kind(
        ["--report", "team-step", "--task-id", "t1", "--step-id", "s1",
         "--attempt-id", attempt],
        agent_id="a1", loaded=_fake_loaded(), settings=settings, data_dir=agent_data_dir,
    )
    assert rc == 3  # worker exit 3: paused at the approval gate

    events = (agent_data_dir / "runs.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(events[-1])["status"] == "interrupted"

    store2 = _store(tmp_path)
    step = store2.get_step("t1", "s1")
    assert step.status == "awaiting_approval"
    # no real handoff artifact yet — deliver stopped short, only the fallback
    # awaiting_approval marker was written by the worker's _write_outcome.
    artifact = read_step_artifact(tmp_path, "t1", 1)
    assert artifact is not None and artifact["status"] == "awaiting_approval"

    # The ticker must leave an awaiting_approval step alone — no poll, no timeout, no
    # respawn, even with the clock pushed far past any lease TTL.
    from datetime import UTC, datetime, timedelta

    far_future = datetime.now(UTC) + timedelta(hours=999)
    tick_deps = CoordinatorDeps(
        store=store2, retry_tracker=in_memory_retry_tracker(), cost_cap_usd=2.0,
        now=lambda: far_future,
    )
    tick_result = run_one_tick(tick_deps)
    assert tick_result.action == "none"
    assert store2.get_step("t1", "s1").status == "awaiting_approval"  # untouched

    # CEO resolves the approval out-of-band; the coordinator re-reserves the SAME step
    # (no checkpointer -> re-run from scratch is the documented recovery path).
    gate_open["approved"] = True
    new_attempt = store2.reserve_step("t1", "s1")
    store2.close()
    assert new_attempt != attempt

    rc2 = _run_team_step_kind(
        ["--report", "team-step", "--task-id", "t1", "--step-id", "s1",
         "--attempt-id", new_attempt],
        agent_id="a1", loaded=_fake_loaded(), settings=settings, data_dir=agent_data_dir,
    )
    assert rc2 == 0

    events2 = (agent_data_dir / "runs.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(events2[-1])["status"] == "done"

    store3 = _store(tmp_path)
    resumed_step = store3.get_step("t1", "s1")
    assert resumed_step.status == "done"
    store3.close()

    final_artifact = read_step_artifact(tmp_path, "t1", 1)
    assert final_artifact is not None
    assert final_artifact["status"] == "done"
    assert final_artifact["result_text"] == "draft output"


# --- MAJOR-5: ticker auto-resume through a REAL ApprovalStore (approval_id set) -----


def test_ticker_polls_real_approval_store_pending_then_approved_respawns(tmp_path):
    """`poll_awaiting_approval_step` (wired via `CoordinatorDeps.approval_status`) reads
    a REAL `ApprovalStore` — not a manual `reserve_step` call like the exit-3 e2e test
    above. Pending -> tick leaves the step alone (lease clock stays paused, matching
    the no-`approval_id` invariant tests). Approved -> the very next tick re-reserves +
    re-spawns the SAME step with a fresh `attempt_id`, and the step's `approval_id`
    column is cleared (a fresh attempt must not inherit a stale approval id, see
    `TeamTaskStore.reserve_step`)."""
    from datetime import UTC, datetime, timedelta

    from src.actions.approval_store import ApprovalStore
    from src.agent.coordinator_graph import CoordinatorDeps, in_memory_retry_tracker, run_one_tick

    store = _store(tmp_path)
    _plan(store, task_id="t1")
    store.reserve_step("t1", "s1")

    approvals = ApprovalStore(tmp_path / "agent-a" / "approvals.db")
    approval_id = approvals.enqueue({"kind": "post_message"}, reason="external write on s1")
    store.mark_awaiting_approval("t1", "s1", approval_id=approval_id)

    spawned: list[tuple[str, str]] = []

    def _spawn(task, step, attempt_id):
        spawned.append((step.step_id, attempt_id))
        return 555

    far_future = datetime.now(UTC) + timedelta(hours=999)
    deps = CoordinatorDeps(
        store=store,
        retry_tracker=in_memory_retry_tracker(),
        cost_cap_usd=2.0,
        spawn_step=_spawn,
        approval_status=lambda aid: approvals.get(aid).status if approvals.get(aid) else None,
        now=lambda: far_future,
    )

    # Still pending: tick leaves the step untouched, no spawn, lease clock paused.
    pending_result = run_one_tick(deps)
    assert pending_result.action == "none"
    step = store.get_step("t1", "s1")
    assert step.status == "awaiting_approval"
    assert spawned == []

    # CEO approves out-of-band via the real store's CAS transition.
    assert approvals.transition_if_pending(approval_id, "approved") is True

    approved_result = run_one_tick(deps)
    assert approved_result.action == "spawned"
    assert len(spawned) == 1
    assert spawned[0][0] == "s1"

    resumed_step = store.get_step("t1", "s1")
    assert resumed_step.status == "running"
    assert resumed_step.approval_id is None  # cleared on the fresh reserve
    assert spawned[0][1] != ""  # a real fresh attempt_id was issued

    approvals.close()
    store.close()


def test_ticker_polls_real_approval_store_rejected_marks_step_failed_and_escalates(tmp_path):
    """Rejected via the real store -> terminal: step `failed`, one escalation, no
    respawn — the CEO explicitly said no, so this must never retry."""
    from datetime import UTC, datetime, timedelta

    from src.actions.approval_store import ApprovalStore
    from src.agent.coordinator_graph import CoordinatorDeps, in_memory_retry_tracker, run_one_tick

    store = _store(tmp_path)
    _plan(store, task_id="t1")
    store.reserve_step("t1", "s1")

    approvals = ApprovalStore(tmp_path / "agent-a" / "approvals.db")
    approval_id = approvals.enqueue({"kind": "post_message"}, reason="external write on s1")
    store.mark_awaiting_approval("t1", "s1", approval_id=approval_id)
    assert approvals.transition_if_pending(approval_id, "rejected") is True

    escalated: list[str] = []
    far_future = datetime.now(UTC) + timedelta(hours=999)
    deps = CoordinatorDeps(
        store=store,
        retry_tracker=in_memory_retry_tracker(),
        cost_cap_usd=2.0,
        approval_status=lambda aid: approvals.get(aid).status if approvals.get(aid) else None,
        escalate=lambda task, step, kind, msg: escalated.append(kind),
        now=lambda: far_future,
    )

    result = run_one_tick(deps)
    assert result.action == "failed"
    assert escalated == ["step_approval_rejected"]

    step = store.get_step("t1", "s1")
    assert step.status == "failed"

    approvals.close()
    store.close()
