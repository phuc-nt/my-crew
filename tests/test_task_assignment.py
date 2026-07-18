"""v6 M15: assigned watch-tasks (multi-day). Offline (gh + gateway stubbed).

Load-bearing:
- Lifecycle: create → check → done (stop condition) / stalled (N content errors) /
  cancelled; open-task cap bounds the blast radius.
- Stop condition is CODE (PR merged/closed/deadline), never the LLM.
- Runner discipline mirrors the inbox: INFRA error holds (no status/streak change);
  content error bumps the streak → stalled past STALL_AFTER; each notice through the
  gateway (dedup per-day for reminders).
- No open tasks ⇒ schedule byte-identical to pre-M15.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from my_crew.config.config_builders import (
    build_reporting_config_from_dict,
    build_settings_from_dict,
)
from my_crew.profile.loader import LoadedProfile
from my_crew.runtime.task_store import MAX_OPEN_TASKS, STALL_AFTER, HistoryEntry, TaskStore
from my_crew.runtime.watch_task import DEFAULT_DEADLINE_DAYS, check_pr_watch


def _store(tmp_path):
    return TaskStore(tmp_path / "tasks.sqlite3")


# --- TaskStore lifecycle ---


def test_create_and_list_open(tmp_path):
    s = _store(tmp_path)
    try:
        tid = s.create(kind="watch", params={"target": "pr", "number": 45}, schedule="0 8 * * *")
        assert tid == 1
        opens = s.list_open()
        assert len(opens) == 1 and opens[0].params["number"] == 45
        assert opens[0].status == "open"
    finally:
        s.close()


def test_open_task_cap_enforced(tmp_path):
    s = _store(tmp_path)
    try:
        for i in range(MAX_OPEN_TASKS):
            s.create(kind="watch", params={"number": i}, schedule="0 8 * * *")
        with pytest.raises(RuntimeError, match="giới hạn"):
            s.create(kind="watch", params={"number": 99}, schedule="0 8 * * *")
        # cancelling one frees a slot
        s.set_status(1, "cancelled")
        assert s.create(kind="watch", params={"number": 99}, schedule="0 8 * * *") > 0
    finally:
        s.close()


def test_history_and_status_transitions(tmp_path):
    s = _store(tmp_path)
    try:
        tid = s.create(kind="watch", params={"number": 1}, schedule="0 8 * * *")
        s.append_history(tid, HistoryEntry("t1", "nhắc lần 1"))
        s.append_history(tid, HistoryEntry("t2", "đã merge", 0.0))
        s.set_status(tid, "done")
        t = s.get(tid)
        assert t.status == "done" and len(t.history) == 2
        assert t.history[0].summary == "nhắc lần 1"
    finally:
        s.close()


def test_persists_across_reopen(tmp_path):
    s1 = _store(tmp_path)
    tid = s1.create(kind="watch", params={"number": 7}, schedule="0 8 * * *")
    s1.close()
    s2 = _store(tmp_path)  # simulate a service restart
    try:
        assert s2.get(tid).params["number"] == 7 and s2.open_count() == 1
    finally:
        s2.close()


# --- watch stop condition (CODE, not LLM) ---


def _created_now():
    return datetime.now(UTC).isoformat()


def test_watch_done_when_merged():
    r = check_pr_watch({"number": 45}, repo="o/r", created_at=_created_now(),
                       run_gh=lambda a: {"state": "MERGED", "title": "Feat X"})
    assert r.done and "MERGE" in r.reason and not r.remind


def test_watch_done_when_closed():
    r = check_pr_watch({"number": 45}, repo="o/r", created_at=_created_now(),
                       run_gh=lambda a: {"state": "CLOSED", "title": "X"})
    assert r.done and "ĐÓNG" in r.reason


def test_watch_reminds_while_open():
    r = check_pr_watch({"number": 45, "note": "gấp"}, repo="o/r", created_at=_created_now(),
                       run_gh=lambda a: {"state": "OPEN", "title": "X"})
    assert not r.done and r.remind and "gấp" in r.reason


def test_watch_deadline_stops_even_if_open():
    old = (datetime.now(UTC) - timedelta(days=DEFAULT_DEADLINE_DAYS + 1)).isoformat()
    r = check_pr_watch({"number": 45}, repo="o/r", created_at=old,
                       run_gh=lambda a: {"state": "OPEN", "title": "X"})
    assert r.done and "hết hạn" in r.reason


def test_watch_bad_number_raises():
    with pytest.raises(ValueError, match="number"):
        check_pr_watch({}, repo="o/r", created_at=_created_now(), run_gh=lambda a: {})


def test_watch_empty_gh_response_is_content_error_not_reminder():
    """An empty gh state (auth expired but exit 0) must raise (→ stall streak), not be read
    as 'still open → remind' which would spam a bogus daily reminder (review L3)."""
    with pytest.raises(ValueError, match="rỗng|trạng thái"):
        check_pr_watch({"number": 45}, repo="o/r", created_at=_created_now(),
                       run_gh=lambda a: {"title": "X"})  # no 'state' key


# --- runner ---


def _loaded(tmp_path, *, write_disabled=False):
    config = build_reporting_config_from_dict(
        {"jira_project_key": "SCRUM", "github_repo": "acme/web", "slack_report_channel": "C_REP",
         "slack_stakeholder_channel": "", "slack_external_channels": ""}
    )
    settings = build_settings_from_dict(
        {"openrouter_api_key": "k", "data_dir": tmp_path, "dry_run": False,
         "write_disabled": write_disabled}
    )
    return LoadedProfile(
        profile_id="pm", name="PM", enabled=True, settings=settings, config=config,
        soul="", project="", memory="", schedule={}, reports=("daily",), domain="pm",
    )


def _seed_watch(tmp_path, params=None):
    s = _store(tmp_path)
    tid = s.create(kind="watch", params=params or {"target": "pr", "number": 45},
                   schedule="0 8 * * *")
    s.close()
    return tid


def test_runner_marks_done_and_posts(tmp_path, monkeypatch):
    from my_crew.runtime import task_runner

    tid = _seed_watch(tmp_path)
    posts = []
    monkeypatch.setattr("my_crew.adapters.cli_adapter.run_gh",
                        lambda a: {"state": "MERGED", "title": "Feat X"})
    monkeypatch.setattr(task_runner, "_post",
                        lambda gw, ld, text, *, dedup: posts.append(text) or True)

    class _StubGateway:
        def close(self): pass

    monkeypatch.setattr(
        "my_crew.actions.action_gateway.ActionGateway", lambda *a, **k: _StubGateway()
    )
    loaded = _loaded(tmp_path)
    out = task_runner.run_tasks(loaded, loaded.settings)
    assert out["checked"] == 1 and out["delivered"]
    assert any("MERGE" in p for p in posts)
    s = _store(tmp_path)
    try:
        assert s.get(tid).status == "done"
    finally:
        s.close()


def test_runner_reminds_while_open(tmp_path, monkeypatch):
    from my_crew.runtime import task_runner

    tid = _seed_watch(tmp_path)
    posts = []
    monkeypatch.setattr("my_crew.adapters.cli_adapter.run_gh",
                        lambda a: {"state": "OPEN", "title": "X"})
    monkeypatch.setattr(task_runner, "_post",
                        lambda gw, ld, text, *, dedup: posts.append((text, dedup)) or True)
    monkeypatch.setattr("my_crew.actions.action_gateway.ActionGateway",
                        lambda *a, **k: type("G", (), {"close": lambda self: None})())
    loaded = _loaded(tmp_path)
    task_runner.run_tasks(loaded, loaded.settings)
    assert any("Nhắc" in p[0] for p in posts)
    assert any("watch-task-remind" in p[1] for p in posts)  # per-day dedup key
    s = _store(tmp_path)
    try:
        assert s.get(tid).status in ("open", "running")  # stays open
    finally:
        s.close()


def test_runner_stalls_after_repeated_content_errors(tmp_path, monkeypatch):
    from my_crew.runtime import task_runner

    tid = _seed_watch(tmp_path)
    monkeypatch.setattr("my_crew.adapters.cli_adapter.run_gh",
                        lambda a: (_ for _ in ()).throw(RuntimeError("gh: PR not found")))
    monkeypatch.setattr(task_runner, "_post", lambda gw, ld, text, *, dedup: True)
    monkeypatch.setattr("my_crew.actions.action_gateway.ActionGateway",
                        lambda *a, **k: type("G", (), {"close": lambda self: None})())
    loaded = _loaded(tmp_path)
    for _ in range(STALL_AFTER):
        task_runner.run_tasks(loaded, loaded.settings)
    s = _store(tmp_path)
    try:
        assert s.get(tid).status == "stalled"
    finally:
        s.close()


def test_runner_infra_error_holds_no_status_change(tmp_path, monkeypatch):
    from my_crew.llm.fallback_policy import ProviderCallError
    from my_crew.runtime import task_runner

    tid = _seed_watch(tmp_path)
    monkeypatch.setattr("my_crew.adapters.cli_adapter.run_gh",
                        lambda a: (_ for _ in ()).throw(ProviderCallError("net down")))
    monkeypatch.setattr(task_runner, "_post", lambda gw, ld, text, *, dedup: True)
    monkeypatch.setattr("my_crew.actions.action_gateway.ActionGateway",
                        lambda *a, **k: type("G", (), {"close": lambda self: None})())
    loaded = _loaded(tmp_path)
    task_runner.run_tasks(loaded, loaded.settings)
    s = _store(tmp_path)
    try:
        t = s.get(tid)
        assert t.status in ("open", "running") and t.fail_streak == 0  # untouched
    finally:
        s.close()


def test_runner_no_tasks_is_noop(tmp_path):
    from my_crew.runtime.task_runner import run_tasks

    loaded = _loaded(tmp_path)
    out = run_tasks(loaded, loaded.settings)
    assert out["status"] == "no_tasks" and out["checked"] == 0


def test_runner_write_disabled_skips(tmp_path):
    from my_crew.runtime.task_runner import run_tasks

    _seed_watch(tmp_path)
    loaded = _loaded(tmp_path, write_disabled=True)
    out = run_tasks(loaded, loaded.settings)
    assert out["status"] == "writes_disabled"


# --- schedule integration ---


def test_schedule_adds_tasks_kind_via_service_load_path(tmp_path, monkeypatch):
    """Drive _effective_schedule the way the SERVICE does: the profile is loaded WITHOUT a
    per-agent data_dir, so has_open_tasks must find the store under agent_data_dir(id), NOT
    settings.data_dir (which is the global DATA_DIR in the service). This is the exact path
    that regressed as C1 — the old test injected data_dir and never exercised it."""
    monkeypatch.setattr("my_crew.runtime.agent_paths.DATA_DIR", tmp_path)
    from my_crew.runtime.agent_paths import agent_data_dir
    from my_crew.runtime.service import _effective_schedule

    # A profile loaded WITHOUT data_dir → settings.data_dir is NOT the agent's store dir.
    loaded = _loaded(tmp_path / "global-not-store")
    sched, reports = _effective_schedule(loaded)
    assert "tasks" not in reports  # no store yet ⇒ byte-identical

    # Seed the store where the worker/ops-catalog actually write it: agent_data_dir(id).
    s = TaskStore(agent_data_dir(loaded.profile_id) / "tasks.sqlite3")
    s.create(kind="watch", params={"target": "pr", "number": 45}, schedule="0 8 * * *")
    s.close()
    sched2, reports2 = _effective_schedule(loaded)
    assert "tasks" in reports2 and sched2["tasks"] == "0 * * * *"


# --- assign via ops chat (M14 engine) ---


def _patch_agent_paths(monkeypatch, tmp_path, loaded):
    """Point the ops catalog's agent lookups at the test's tmp store + loaded profile."""
    monkeypatch.setattr("my_crew.profile.loader.load_profile", lambda aid, **k: loaded)
    monkeypatch.setattr("my_crew.runtime.agent_paths.agent_data_dir", lambda aid: tmp_path)


def test_watch_pr_assigned_via_ops_chat_confirm_flow(tmp_path, monkeypatch):
    from my_crew.agent.ops_chat import handle_ops_message
    from my_crew.agent.ops_conversation_store import OpsConversationStore

    loaded = _loaded(tmp_path)
    _patch_agent_paths(monkeypatch, tmp_path, loaded)
    store = OpsConversationStore(tmp_path / "ops.sqlite3")

    class _Llm:
        def __init__(self, *c):
            self.q = list(c)

        def complete(self, m):
            return type("R", (), {"content": self.q.pop(0), "cost_usd": 0.0001})()

    try:
        # Intent with all slots → preview + confirm ask.
        r1, _ = handle_ops_message(
            message="theo dõi PR 45 giúp agent pm", conversation_key="ceo", store=store,
            llm=_Llm('{"intent":"command","command_id":"watch_pr",'
                     '"slots":{"agent_id":"pm","pr_number":"45"}}'), now=1.0,
        )
        assert "xác nhận" in r1.lower() and "PR #45" in r1
        # Nothing assigned yet — only a preview.
        assert TaskStore(tmp_path / "tasks.sqlite3").open_count() == 0
        # Confirm → the watch-task is created for real.
        r2, _ = handle_ops_message(message="xác nhận", conversation_key="ceo", store=store,
                                   llm=_Llm(), now=2.0)
        assert "đã giao việc" in r2.lower()
        s = TaskStore(tmp_path / "tasks.sqlite3")
        try:
            opens = s.list_open()
            assert len(opens) == 1 and opens[0].params["number"] == 45
            assert opens[0].kind == "watch"
        finally:
            s.close()
    finally:
        store.close()


def test_list_tasks_is_readonly_no_confirm(tmp_path, monkeypatch):
    from my_crew.agent.ops_chat import handle_ops_message
    from my_crew.agent.ops_conversation_store import OpsConversationStore

    loaded = _loaded(tmp_path)
    _patch_agent_paths(monkeypatch, tmp_path, loaded)
    _seed_watch(tmp_path)
    store = OpsConversationStore(tmp_path / "ops.sqlite3")

    class _Llm:
        def __init__(self, c):
            self.c = c

        def complete(self, m):
            return type("R", (), {"content": self.c, "cost_usd": 0.0001})()

    try:
        reply, _ = handle_ops_message(
            message="agent pm đang làm việc gì", conversation_key="ceo", store=store,
            llm=_Llm('{"intent":"command","command_id":"list_tasks","slots":{"agent_id":"pm"}}'),
            now=1.0,
        )
        assert "PR #45" in reply and "đang mở" in reply
        # readonly ⇒ no draft left behind
        assert store.load("ceo", now=1.0) is None
    finally:
        store.close()
