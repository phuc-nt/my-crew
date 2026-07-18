"""`ops_adjust_team_task` command-layer gates (v13 M34 full replan): the store-level
TOCTOU/swap mechanics are covered end-to-end by `test_adjust_team_task_toctou.py` — this
file instead pins the command surface's OWN gates that never reach the store's
transaction at all: `preview_adjust_team_task`'s task-not-found / no-pending-steps-left /
missing-slot checks, `run_adjust_team_task`'s `reason` -> Vietnamese-message mapping, and
`cancel_adjust_team_task`'s best-effort draft cleanup.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import my_crew.agent.ops_adjust_team_task as mod


@pytest.fixture(autouse=True)
def _isolated_team_tasks_root(monkeypatch, tmp_path):
    """Every test in this module writes through the shared cross-agent root (store,
    office-room appends) — pin it to tmp_path so no test can touch the real install's
    .data (the office room is a real user-visible surface)."""
    monkeypatch.setattr("my_crew.runtime.team_task_paths.DATA_DIR", tmp_path)


def _task(*, steps):
    return SimpleNamespace(id="t1", title="Demo task", steps=steps)


def _step(step_id, status, assigned_to="agent-a", title="A"):
    return SimpleNamespace(step_id=step_id, title=title, status=status, assigned_to=assigned_to)


class _FakeStore:
    """Stand-in for `TeamTaskStore` scoped to exactly what each test needs — avoids
    standing up a real sqlite file for gates that never reach persistence."""

    def __init__(self, *, task=None, confirm_result=None, post_confirm_task=None):
        self._task = task
        self._confirm_result = confirm_result
        self._post_confirm_task = post_confirm_task
        self.closed = False
        self.cancelled_amendment_id = None

    def get(self, task_id):
        if task_id != "t1":
            return None
        return self._post_confirm_task if self._confirm_result is not None and \
            self._confirm_result.ok else self._task

    def confirm_amendment(self, task_id, amendment_id):
        return self._confirm_result

    def cancel_amendment_draft(self, amendment_id):
        self.cancelled_amendment_id = amendment_id

    def close(self):
        self.closed = True


# --- preview_adjust_team_task: gates before any LLM/store write --------------------


def test_preview_raises_when_task_id_or_request_missing():
    with pytest.raises(ValueError, match="mã việc"):
        mod.preview_adjust_team_task({"task_id": "", "yêu cầu": "làm lại"})
    with pytest.raises(ValueError, match="mã việc"):
        mod.preview_adjust_team_task({"task_id": "t1", "yêu cầu": ""})


def test_preview_raises_when_task_not_found(monkeypatch):
    monkeypatch.setattr(mod, "_staff_roster", lambda: [("agent-a", "pm")])
    fake_store = _FakeStore(task=None)
    monkeypatch.setattr(
        "my_crew.runtime.team_task_store.TeamTaskStore", lambda *a, **kw: fake_store
    )
    with pytest.raises(ValueError, match="không tìm thấy việc"):
        mod.preview_adjust_team_task({"task_id": "t1", "yêu cầu": "làm lại"})
    assert fake_store.closed is True


def test_preview_raises_when_no_pending_steps_left(monkeypatch):
    task = _task(steps=[_step("s1", "done"), _step("s2", "running")])
    fake_store = _FakeStore(task=task)
    monkeypatch.setattr(
        "my_crew.runtime.team_task_store.TeamTaskStore", lambda *a, **kw: fake_store
    )
    with pytest.raises(ValueError, match="không còn bước nào đang chờ"):
        mod.preview_adjust_team_task({"task_id": "t1", "yêu cầu": "làm lại"})
    assert fake_store.closed is True


def test_preview_wraps_decomposition_error_from_amend_as_value_error(monkeypatch):
    from my_crew.agent.task_decomposition import DecompositionError

    task = _task(steps=[_step("s1", "pending")])
    fake_store = _FakeStore(task=task)
    monkeypatch.setattr(
        "my_crew.runtime.team_task_store.TeamTaskStore", lambda *a, **kw: fake_store
    )

    def _raise(*a, **kw):
        raise DecompositionError("không chỉnh được kế hoạch hợp lệ sau 3 lần thử: xx")

    monkeypatch.setattr(mod, "amend_with_retries", _raise)
    with pytest.raises(ValueError, match="không chỉnh được kế hoạch hợp lệ"):
        mod.preview_adjust_team_task({"task_id": "t1", "yêu cầu": "làm lại"})
    assert fake_store.closed is True


# --- run_adjust_team_task: reason -> message mapping + task-not-found guard --------


def test_run_raises_when_amendment_id_missing():
    with pytest.raises(ValueError, match="thiếu thông tin bản chỉnh"):
        mod.run_adjust_team_task({"task_id": "t1", "amendment_id": ""})


@pytest.mark.parametrize("reason,expected_snippet", [
    ("amendment_not_found", "không tìm thấy bản chỉnh"),
    ("amendment_not_live", "đã dùng/huỷ/hết hạn"),
    ("plan_changed_since_draft", "kế hoạch đã đổi"),
    ("pending_step_just_reserved", "có bước vừa bắt đầu chạy"),
])
def test_run_maps_every_known_confirm_rejection_reason_to_a_vietnamese_message(
    monkeypatch, reason, expected_snippet,
):
    confirm_result = SimpleNamespace(ok=False, reason=reason)
    fake_store = _FakeStore(confirm_result=confirm_result)
    monkeypatch.setattr(
        "my_crew.runtime.team_task_store.TeamTaskStore", lambda *a, **kw: fake_store
    )
    with pytest.raises(ValueError, match=expected_snippet):
        mod.run_adjust_team_task({"task_id": "t1", "amendment_id": "amend-1"})
    assert fake_store.closed is True


def test_run_falls_back_to_a_generic_message_for_an_unmapped_reason(monkeypatch):
    confirm_result = SimpleNamespace(ok=False, reason="some_future_reason_not_yet_mapped")
    fake_store = _FakeStore(confirm_result=confirm_result)
    monkeypatch.setattr(
        "my_crew.runtime.team_task_store.TeamTaskStore", lambda *a, **kw: fake_store
    )
    with pytest.raises(ValueError, match="không áp dụng được bản chỉnh"):
        mod.run_adjust_team_task({"task_id": "t1", "amendment_id": "amend-1"})


def test_run_returns_confirmation_message_and_appends_milestone_on_success(monkeypatch):
    confirm_result = SimpleNamespace(ok=True, reason=None)
    post_task = _task(steps=[_step("s3", "pending", title="C")])
    fake_store = _FakeStore(confirm_result=confirm_result, post_confirm_task=post_task)
    monkeypatch.setattr(
        "my_crew.runtime.team_task_store.TeamTaskStore", lambda *a, **kw: fake_store
    )

    appended = {}

    def _fake_append(task_id, *, author, kind, body, also_office=False):
        appended["task_id"] = task_id
        appended["body"] = body

    monkeypatch.setattr(
        "my_crew.runtime.office_room_append.append_office_event", _fake_append
    )

    msg = mod.run_adjust_team_task({"task_id": "t1", "amendment_id": "amend-1"})
    assert "Đã chỉnh kế hoạch việc #t1" in msg
    assert appended["task_id"] == "t1"
    assert appended["body"]["milestone"] == "plan_adjusted"
    assert "s3" in appended["body"]["message"]
    assert fake_store.closed is True


# --- cancel_adjust_team_task ---------------------------------------------------------


def test_cancel_is_a_no_op_when_no_amendment_id_was_ever_recorded(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        "my_crew.runtime.team_task_store.TeamTaskStore",
        lambda *a, **kw: calls.append("constructed") or _FakeStore(),
    )
    mod.cancel_adjust_team_task({"task_id": "t1"})
    assert calls == []  # store never opened — nothing to cancel


def test_cancel_terminalizes_the_draft_when_an_amendment_id_is_present(monkeypatch):
    fake_store = _FakeStore()
    monkeypatch.setattr(
        "my_crew.runtime.team_task_store.TeamTaskStore", lambda *a, **kw: fake_store
    )
    mod.cancel_adjust_team_task({"task_id": "t1", "amendment_id": "amend-1"})
    assert fake_store.cancelled_amendment_id == "amend-1"
    assert fake_store.closed is True
