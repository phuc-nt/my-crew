"""v65 one-shot timed reminders: store round-trip, Lớp A shape gate, actor-bound write
handler, delivery sweep (fake gateway send), and the pending-gated schedule synthesis."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from my_crew.actions.hard_block import classify
from my_crew.actions.reminder_write import make_reminder_handler
from my_crew.runtime.reminder_store import (
    ReminderStore,
    has_pending_reminders,
    reminders_db_path,
)


def _store(tmp_path) -> ReminderStore:
    return ReminderStore(reminders_db_path(tmp_path))


# --- store ---------------------------------------------------------------------------


def test_store_round_trip_due_and_states(tmp_path):
    store = _store(tmp_path)
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    future = (datetime.now(UTC) + timedelta(hours=3)).isoformat()
    rid_past = store.add(chat_id="123", text="gọi anh X", due_at=past)
    rid_future = store.add(chat_id="123", text="họp chiều", due_at=future)

    due = store.due()
    assert [r["id"] for r in due] == [rid_past]
    assert store.mark_sent(rid_past) is True
    assert store.mark_sent(rid_past) is False  # idempotent — already sent
    assert store.cancel(rid_future) is True
    assert store.due() == []
    assert store.has_pending() is False
    store.close()


def test_due_compares_mixed_offsets_correctly(tmp_path):
    """+07:00 vs Z do not sort lexicographically — due() must parse, not string-compare."""
    store = _store(tmp_path)
    past_local = (datetime.now(UTC) - timedelta(minutes=5)).astimezone().isoformat()
    store.add(chat_id="1", text="x", due_at=past_local)
    assert len(store.due()) == 1
    store.close()


def test_has_pending_probe_never_creates_the_db(tmp_path):
    assert has_pending_reminders(tmp_path) is False
    assert not reminders_db_path(tmp_path).exists()  # probe left no empty store behind


# --- Lớp A shape gate ----------------------------------------------------------------


def test_hard_block_rejects_bad_reminder_shapes():
    base = {"type": "reminder_create", "chat_id": "1", "dedup_hint": "x"}
    assert classify({**base, "text": "", "due_at": "2026-08-05T15:00:00+07:00"}).blocked
    assert classify({**base, "text": "ok", "due_at": "mai 3h"}).blocked
    assert classify({**base, "text": "ok", "due_at": "2026-08-05T15:00"}).blocked  # no offset
    assert not classify(
        {**base, "text": "gọi anh X", "due_at": "2026-08-05T15:00:00+07:00"}
    ).blocked
    assert classify({"type": "reminder_cancel", "reminder_id": 0, "dedup_hint": "x"}).blocked
    assert not classify({"type": "reminder_cancel", "reminder_id": 3, "dedup_hint": "x"}).blocked


def test_hard_block_scans_reminder_text_for_secrets():
    fake_token = "ghp_" + "a1b2c3d4" * 5  # noqa: S105 — giả, ghép runtime
    verdict = classify({"type": "reminder_create", "chat_id": "1", "dedup_hint": "x",
                        "text": f"token: {fake_token}",
                        "due_at": "2026-08-05T15:00:00+07:00"})
    assert verdict.blocked


# --- actor-bound write handler -------------------------------------------------------


def test_handler_writes_and_cancels_in_the_actor_store(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "my_crew.runtime.agent_paths.agent_data_dir", lambda agent_id: tmp_path / agent_id,
    )
    handler = make_reminder_handler("secretary")
    summary = handler({"type": "reminder_create", "chat_id": "1", "text": "gọi X",
                       "due_at": "2030-01-01T09:00:00+07:00"})
    assert "đã đặt nhắc #1" in summary
    assert has_pending_reminders(tmp_path / "secretary")
    assert not has_pending_reminders(tmp_path / "analyst")  # actor-bound, never elsewhere

    assert "đã huỷ nhắc #1" in handler({"type": "reminder_cancel", "reminder_id": 1})
    with pytest.raises(PermissionError, match="không tồn tại hoặc đã gửi"):
        handler({"type": "reminder_cancel", "reminder_id": 1})


# --- delivery sweep ------------------------------------------------------------------


def _loaded(tmp_path, agent_id="secretary"):
    telegram = SimpleNamespace(bot_token_env="X", chat_ids=("123",), poll_minutes=5,
                               ops_operator_id="123")
    return SimpleNamespace(
        profile_id=agent_id,
        config=SimpleNamespace(telegram=telegram, slack_external_channels=()),
    )


def test_sweep_sends_due_and_marks_sent(tmp_path, monkeypatch):
    from my_crew.runtime import reminder_sweep

    monkeypatch.setattr(
        "my_crew.runtime.agent_paths.agent_data_dir", lambda agent_id: tmp_path / agent_id,
    )
    store = ReminderStore(reminders_db_path(tmp_path / "secretary"))
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    rid = store.add(chat_id="123", text="gọi anh X", due_at=past)
    store.add(chat_id="123", text="chưa tới giờ", due_at=future)
    store.close()

    sent: list[tuple[str, str]] = []

    def _fake_send(text, *, gateway, telegram, chat_id, dedup_hint, **kw):
        sent.append((chat_id, text))
        return SimpleNamespace(status="executed", summary="ok")

    monkeypatch.setattr("my_crew.actions.telegram_write.send_telegram_message", _fake_send)
    monkeypatch.setattr(
        "my_crew.actions.action_gateway.ActionGateway",
        lambda *a, **k: SimpleNamespace(),
    )

    result = reminder_sweep.run_reminder_sweep(_loaded(tmp_path), settings=SimpleNamespace())

    assert result["status"] == "ok"
    assert result["delivered"] is True
    assert sent == [("123", "⏰ Nhắc hẹn: gọi anh X")]
    store = ReminderStore(reminders_db_path(tmp_path / "secretary"))
    try:
        pending = store.list_pending()
        assert [r["text"] for r in pending] == ["chưa tới giờ"]  # due row marked sent
        assert all(r["id"] != rid for r in pending)
    finally:
        store.close()


def test_sweep_leaves_row_pending_when_send_denied(tmp_path, monkeypatch):
    from my_crew.runtime import reminder_sweep

    monkeypatch.setattr(
        "my_crew.runtime.agent_paths.agent_data_dir", lambda agent_id: tmp_path / agent_id,
    )
    store = ReminderStore(reminders_db_path(tmp_path / "secretary"))
    store.add(chat_id="123", text="x",
              due_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat())
    store.close()

    monkeypatch.setattr(
        "my_crew.actions.telegram_write.send_telegram_message",
        lambda *a, **k: SimpleNamespace(status="deny", summary="blocked"),
    )
    monkeypatch.setattr(
        "my_crew.actions.action_gateway.ActionGateway", lambda *a, **k: SimpleNamespace(),
    )

    result = reminder_sweep.run_reminder_sweep(_loaded(tmp_path), settings=SimpleNamespace())

    assert result["delivered"] is False
    store = ReminderStore(reminders_db_path(tmp_path / "secretary"))
    try:
        assert len(store.list_pending()) == 1  # NOT drained — next sweep retries
    finally:
        store.close()


# --- schedule synthesis --------------------------------------------------------------


def test_schedule_synthesizes_reminder_sweep_only_while_pending(tmp_path, monkeypatch):
    from my_crew.runtime.service import _effective_schedule

    monkeypatch.setattr(
        "my_crew.runtime.agent_paths.agent_data_dir", lambda agent_id: tmp_path / agent_id,
    )
    loaded = _loaded(tmp_path)
    loaded.schedule = {}
    loaded.reports = ()
    loaded.watchers = None

    schedule, reports = _effective_schedule(loaded)
    assert "reminder-sweep" not in schedule  # no pending rows → byte-identical-ish

    store = ReminderStore(reminders_db_path(tmp_path / "secretary"))
    store.add(chat_id="123", text="x", due_at="2030-01-01T09:00:00+07:00")
    store.close()

    schedule, reports = _effective_schedule(loaded)
    assert schedule["reminder-sweep"] == "* * * * *"
    assert "reminder-sweep" in reports
