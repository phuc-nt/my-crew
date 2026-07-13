"""v31 P5 wake-gate watcher: normalize idempotency on REAL-parser payloads, the
record_check/advance_hash split (lost-wake safety), exactly-one-wake, fail backoff →
operator alert, stale → alert-not-wake, byte-identical schedule without watchers,
and the fail-closed sources.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from src.config.config_builders import build_settings_from_dict
from src.profile.loader import LoadedProfile, _parse_watchers
from src.runtime.watcher_normalize import (
    NotSupportedError,
    normalize_and_hash,
)
from src.runtime.watcher_runner import run_watchers
from src.runtime.watcher_store import WatcherStore

# --- normalize idempotency, through the REAL parsers (not hand-built dicts) ---


_RAW_ISSUE = {
    "key": "SCRUM-1",
    "fields": {
        "summary": "Fix login", "status": {"name": "In Progress"},
        "assignee": {"displayName": "An"}, "duedate": "2026-07-20",
        "labels": ["backend", "auth"], "flagged": False,
    },
}

_RAW_PR = {
    "number": 7, "title": "Add cache", "author": {"login": "binh"},
    "updatedAt": "2026-07-01T08:00:00Z", "reviewDecision": "REVIEW_REQUIRED",
    "statusCheckRollup": [{"status": "COMPLETED", "conclusion": "SUCCESS"}],
}


def test_jira_label_reorder_same_hash():
    from src.tools.jira_read import parse_issue

    a = parse_issue(_RAW_ISSUE)
    swapped = {**_RAW_ISSUE, "fields": {**_RAW_ISSUE["fields"], "labels": ["auth", "backend"]}}
    b = parse_issue(swapped)
    assert normalize_and_hash("jira", [a]) == normalize_and_hash("jira", [b])


def test_jira_status_change_new_hash():
    from src.tools.jira_read import parse_issue

    a = parse_issue(_RAW_ISSUE)
    changed = {**_RAW_ISSUE, "fields": {**_RAW_ISSUE["fields"], "status": {"name": "Done"}}}
    b = parse_issue(changed)
    assert normalize_and_hash("jira", [a]) != normalize_and_hash("jira", [b])


def test_github_age_days_drift_same_hash():
    """The critical false-diff: a day passing changes age_days/stale but NOT the source."""
    from src.tools.github_read import parse_pr

    a = parse_pr(_RAW_PR, today=date(2026, 7, 10), stale_days=7)
    b = parse_pr(_RAW_PR, today=date(2026, 7, 11), stale_days=7)  # +1 day → stale flips
    assert (a.age_days, a.stale) != (b.age_days, b.stale)  # parser DID change these
    assert normalize_and_hash("github", [a]) == normalize_and_hash("github", [b])


def test_sheets_row_insert_only_adds_that_row():
    from src.packs.registry import _load_pack_module

    tools = _load_pack_module("hr", "tools")
    rows = [["name", "status", "email"], ["An", "active", "an@x.vn"],
            ["Binh", "active", "binh@x.vn"]]
    inserted = [rows[0], ["Chi", "active", "chi@x.vn"], *rows[1:]]  # insert at TOP
    base = tools._rows_to_tasks(rows, source="sheet")
    shifted = tools._rows_to_tasks(inserted, source="sheet")
    # Row-index ids shifted for every row, but identity-keyed normalize only sees the
    # genuinely-new row: removing it restores the original hash.
    without_new = [t for t in shifted if "chi@x.vn" not in dict(t.extra or ()).values()]
    assert normalize_and_hash("sheets", base) == normalize_and_hash("sheets", without_new)
    assert normalize_and_hash("sheets", base) != normalize_and_hash("sheets", shifted)


@pytest.mark.parametrize("source", ["confluence", "linear"])
def test_unsupported_sources_fail_closed(source):
    with pytest.raises(NotSupportedError):
        normalize_and_hash(source, [])


# --- WatcherStore: the record_check / advance_hash split ---


def test_store_split_and_fail_bookkeeping(tmp_path):
    store = WatcherStore(tmp_path / "watcher.db")
    try:
        is_new, old = store.record_check("a:w1", "jira", "h1")
        assert is_new and old is None
        # NOT advanced yet: the same hash is STILL new (wake has not succeeded).
        assert store.record_check("a:w1", "jira", "h1")[0] is True
        store.advance_hash("a:w1", "h1")
        assert store.record_check("a:w1", "jira", "h1")[0] is False
        # a poll failure increments fails, keeps the committed hash + checked_at
        store.record_check("a:w1", "jira", None, error="401")
        state = store.get_state("a:w1")
        assert state["fail_count"] == 1 and state["last_hash"] == "h1"
        assert state["last_checked_at"]  # kept from the last SUCCESS
        # recovery resets the streak
        store.record_check("a:w1", "jira", "h1")
        assert store.get_state("a:w1")["fail_count"] == 0
    finally:
        store.close()


def test_store_is_stale_fake_clock(tmp_path):
    store = WatcherStore(tmp_path / "watcher.db")
    try:
        store.record_check("a:w1", "jira", "h1")
        now = datetime.now(UTC)
        # Staleness measures time since the last committed CHANGE (advance_hash) —
        # a fresh poll alone never makes a watcher stale, and neither does a watcher
        # that has never advanced.
        assert store.is_stale("a:w1", now=now + timedelta(hours=25)) is False
        store.advance_hash("a:w1", "h1")
        assert store.is_stale("a:w1", now=now) is False
        assert store.is_stale("a:w1", now=now + timedelta(hours=25)) is True
        assert store.is_stale("a:w1", now=now + timedelta(hours=25),
                              max_age_hours=48) is False
        # a later poll that finds NO change must not reset the staleness clock
        store.record_check("a:w1", "jira", "h1")
        assert store.is_stale("a:w1", now=now + timedelta(hours=25)) is True
        assert store.is_stale("missing", now=now) is False  # never polled ≠ stale
    finally:
        store.close()


# --- run_watchers: wake contract with injected boundaries ---


def _loaded(tmp_path, watchers):
    settings = build_settings_from_dict(
        {"openrouter_api_key": "k", "data_dir": tmp_path / "agent", "dry_run": True}
    )
    from tests.test_ask_agent_inbox import _config

    return LoadedProfile(
        profile_id="acme", name="Acme", enabled=True, settings=settings, config=_config(),
        soul="", project="", memory="", schedule={}, reports=(),
        domain="office", watchers=tuple(watchers),
    )


_W = {"id": "w1", "source": "jira", "target": "SCRUM", "prompt": "rà soát"}


def test_diff_wakes_exactly_once_then_quiet(tmp_path):
    loaded = _loaded(tmp_path, [_W])
    wakes = []
    poll = lambda w, lo, s: []  # noqa: E731 — constant source
    out = run_watchers(loaded, loaded.settings, poll_fn=poll,
                       wake_fn=lambda lo, w: wakes.append(w) or True)
    assert out["woke"] == 1 and len(wakes) == 1  # first sight IS a diff
    out = run_watchers(loaded, loaded.settings, poll_fn=poll,
                       wake_fn=lambda lo, w: wakes.append(w) or True)
    assert out["status"] == "no_change" and len(wakes) == 1  # hash advanced → quiet


def test_lost_wake_refires_next_tick(tmp_path):
    loaded = _loaded(tmp_path, [_W])
    poll = lambda w, lo, s: []  # noqa: E731
    out = run_watchers(loaded, loaded.settings, poll_fn=poll, wake_fn=lambda lo, w: False)
    assert out["status"] == "diff_wake_failed" and out["woke"] == 0
    # hash NOT advanced → the SAME diff re-fires and a now-working wake lands it
    out = run_watchers(loaded, loaded.settings, poll_fn=poll, wake_fn=lambda lo, w: True)
    assert out["woke"] == 1


def test_poll_fail_three_times_alerts_once(tmp_path, monkeypatch):
    alerts = []
    monkeypatch.setattr("src.runtime.watcher_runner._alert",
                        lambda text, wid, kind: alerts.append((wid, kind)))

    def boom(w, lo, s):
        raise RuntimeError("MCP 401")

    loaded = _loaded(tmp_path, [_W])
    for _ in range(4):
        out = run_watchers(loaded, loaded.settings, poll_fn=boom,
                           wake_fn=lambda lo, w: True)
        assert out["checked"] == 0 and out["woke"] == 0
    assert alerts == [("acme:w1", "fail")]  # exactly once, at the threshold


def test_stale_alerts_but_never_wakes(tmp_path, monkeypatch):
    alerts = []
    monkeypatch.setattr("src.runtime.watcher_runner._alert",
                        lambda text, wid, kind: alerts.append(kind))
    monkeypatch.setattr(WatcherStore, "is_stale", lambda self, wid, **kw: True)
    loaded = _loaded(tmp_path, [_W])
    wakes = []
    poll = lambda w, lo, s: []  # noqa: E731
    run_watchers(loaded, loaded.settings, poll_fn=poll,
                 wake_fn=lambda lo, w: wakes.append(w) or True)  # first tick: diff→wake
    out = run_watchers(loaded, loaded.settings, poll_fn=poll,
                       wake_fn=lambda lo, w: wakes.append(w) or True)
    assert out["status"] == "no_change"
    assert alerts == ["stale"] and len(wakes) == 1  # alerted, NOT woken again


def test_run_event_carries_no_cost(tmp_path):
    loaded = _loaded(tmp_path, [_W])
    out = run_watchers(loaded, loaded.settings, poll_fn=lambda w, lo, s: [],
                       wake_fn=lambda lo, w: True)
    assert out["cost_usd"] is None  # the NO-LLM contract


# --- wake vehicle: one pre-planned single-step team task ---


def test_wake_enqueues_single_step_task(tmp_path, monkeypatch):
    from src.runtime.watcher_runner import _wake_via_team_task

    monkeypatch.setattr("src.runtime.team_task_paths.DATA_DIR", tmp_path / ".data")
    (tmp_path / ".data").mkdir()
    monkeypatch.setattr("src.agent.team_task_roster.is_assignable", lambda a: a == "acme")
    events = []
    monkeypatch.setattr(
        "src.runtime.office_room_append.append_office_event",
        lambda room, *, author, kind, body, also_office=False: events.append(kind),
    )
    loaded = _loaded(tmp_path, [_W])
    assert _wake_via_team_task(loaded, _W) is True
    from src.runtime.team_task_paths import team_tasks_db_path
    from src.runtime.team_task_store import TeamTaskStore

    store = TeamTaskStore(team_tasks_db_path())
    try:
        tasks = store.list_dispatchable()
        assert len(tasks) == 1
        task = tasks[0]
        assert task.status == "open" and task.pic_id == "acme"
        assert task.assigned_by == "watcher:w1"
        assert len(task.steps) == 1 and task.steps[0].assigned_to == "acme"
        assert task.steps[0].title == _W["prompt"]  # agent-owned prompt, no source text
        # v34 live-UAT fix: the stored plan_hash must equal what the ticker recomputes
        # (over system_inserted=0 rows) — a random "watch-…" token stalled the wake on
        # tick one and it never dispatched.
        assert not task.plan_hash.startswith("watch-")
        from types import SimpleNamespace

        from src.agent.task_decomposition import decomposition_content_hash

        recomputed = decomposition_content_hash(SimpleNamespace(steps=[
            SimpleNamespace(step_id=s.step_id, title=s.title,
                            assigned_to=s.assigned_to, deps=s.deps)
            for s in task.steps if not s.system_inserted
        ]))
        assert recomputed == task.plan_hash
    finally:
        store.close()
    assert events == ["assignment"]


def test_wake_refuses_non_assignable_agent(tmp_path, monkeypatch):
    from src.runtime.watcher_runner import _wake_via_team_task

    monkeypatch.setattr("src.runtime.team_task_paths.DATA_DIR", tmp_path / ".data")
    (tmp_path / ".data").mkdir()
    monkeypatch.setattr("src.agent.team_task_roster.is_assignable", lambda a: False)
    loaded = _loaded(tmp_path, [_W])
    assert _wake_via_team_task(loaded, _W) is False  # → hash not advanced upstream


def test_wake_task_passes_ticker_hash_gate(tmp_path, monkeypatch):
    """End-to-end guard for the live-UAT finding: a wake task run through the REAL
    ticker must dispatch (spawn), NOT stall on the plan-hash gate."""
    from datetime import UTC, datetime

    from src.agent.coordinator_graph import (
        CoordinatorDeps,
        in_memory_retry_tracker,
        run_one_tick,
    )
    from src.runtime.watcher_runner import _wake_via_team_task

    monkeypatch.setattr("src.runtime.team_task_paths.DATA_DIR", tmp_path / ".data")
    (tmp_path / ".data").mkdir()
    monkeypatch.setattr("src.agent.team_task_roster.is_assignable", lambda a: a == "acme")
    monkeypatch.setattr(
        "src.runtime.office_room_append.append_office_event",
        lambda *a, **k: None,
    )
    assert _wake_via_team_task(_loaded(tmp_path, [_W]), _W) is True

    from src.runtime.team_task_paths import team_tasks_db_path
    from src.runtime.team_task_store import TeamTaskStore

    store = TeamTaskStore(team_tasks_db_path())
    spawned = []
    deps = CoordinatorDeps(
        store=store, retry_tracker=in_memory_retry_tracker(), cost_cap_usd=2.0,
        spawn_step=lambda task, step, attempt_id: spawned.append(step.step_id) or 999,
        pid_alive=lambda pid: True, kill_pid=lambda pid, attempt_id: None,
        roster_ok=lambda a: a == "acme",
        aggregate=lambda task: ("ok", 0.0), deliver_room=lambda task, summary: None,
        escalate=lambda task, step, kind, msg: spawned.append(f"STALL:{kind}"),
        now=lambda: datetime.now(UTC),
    )
    try:
        result = run_one_tick(deps)
    finally:
        store.close()
    assert result.action == "spawned"  # NOT "stalled" — the hash gate passed
    assert spawned == ["s1"] and not any(str(x).startswith("STALL") for x in spawned)


# --- loader + scheduler wiring ---


def test_parse_watchers_shapes():
    assert _parse_watchers(None) == ()
    parsed = _parse_watchers([{"id": "w1", "source": "JIRA", "target": "SCRUM",
                               "prompt": "rà"}])
    assert parsed[0]["source"] == "jira"
    for bad in (
        "notalist",
        [{"id": "", "source": "jira", "target": "X", "prompt": "p"}],
        [{"id": "a", "source": "ftp", "target": "X", "prompt": "p"}],
        [{"id": "a", "source": "jira", "target": "", "prompt": "p"}],
        [{"id": "a", "source": "jira", "target": "X", "prompt": ""}],
        [{"id": "a", "source": "jira", "target": "X", "prompt": "p"},
         {"id": "a", "source": "jira", "target": "Y", "prompt": "p"}],
    ):
        with pytest.raises(RuntimeError):
            _parse_watchers(bad)


def test_effective_schedule_byte_identical_without_watchers(tmp_path):
    from src.runtime.service import _effective_schedule

    loaded = _loaded(tmp_path, [])
    schedule, reports = _effective_schedule(loaded)
    assert schedule is loaded.schedule and reports is loaded.reports  # tuple identity


def test_effective_schedule_synthesizes_watch(tmp_path):
    from src.runtime.service import _effective_schedule

    loaded = _loaded(tmp_path, [_W])
    schedule, reports = _effective_schedule(loaded)
    assert schedule["watch"] == "*/5 * * * *"
    assert "watch" in reports
