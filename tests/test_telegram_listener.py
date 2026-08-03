"""v57: wake-on-message Telegram listener. Offline — peek/clock/sleep/spawn đều inject.

Load-bearing properties:

- Peek là long-poll ĐỌC THUẦN: gọi getUpdates với timeout dài + offset hiện tại
  (None → -1 = chỉ update mới nhất), KHÔNG ghi state file nào.
- Loop: có update → spawn worker inbox rồi mới peek tiếp; lỗi peek (409 khi tick lịch
  fetch, mạng rớt) → backoff rồi treo lại, thread bất tử, worker không bị kích.
- Rate cap: quá `_MAX_SPAWNS_PER_WINDOW` lần kích trong 60s → nhường backlog cho tick
  lịch (sleep, không spawn) — flood không đốt LLM vô hạn.
- Service chỉ mở listener cho agent enabled + có telegram; argv worker đúng kind inbox.
"""

from __future__ import annotations

import threading
from pathlib import Path

from my_crew.config.telegram_config import TelegramConfig
from my_crew.runtime import telegram_listener as tl

_TELEGRAM = TelegramConfig(bot_token_env="TK_TEST_BOT_TOKEN", chat_ids=("111",))


# --- peek ---


def test_peek_long_polls_with_current_offset_and_writes_no_state(tmp_path, monkeypatch):
    monkeypatch.setenv("TK_TEST_BOT_TOKEN", "tok")
    seen: dict = {}

    def fake_api_call(token, method, payload, *, timeout_s):
        seen.update({"method": method, "payload": payload, "timeout_s": timeout_s})
        return [{"update_id": 5}]

    monkeypatch.setattr("my_crew.actions.telegram_write.api_call", fake_api_call)
    assert tl.peek_has_updates(_TELEGRAM, offset=None) is True
    assert seen["method"] == "getUpdates"
    assert seen["payload"]["offset"] == -1  # chưa bootstrap → chỉ update mới nhất
    assert seen["payload"]["timeout"] == tl._LONG_POLL_S
    assert seen["timeout_s"] > tl._LONG_POLL_S  # socket timeout phải lớn hơn long-poll
    assert list(tmp_path.iterdir()) == []  # không ghi state — offset là việc của worker


def test_peek_passes_stored_offset(monkeypatch):
    monkeypatch.setenv("TK_TEST_BOT_TOKEN", "tok")
    captured: dict = {}
    monkeypatch.setattr(
        "my_crew.actions.telegram_write.api_call",
        lambda token, method, payload, *, timeout_s: captured.update(payload) or [],
    )
    assert tl.peek_has_updates(_TELEGRAM, offset=42) is False
    assert captured["offset"] == 42


# --- loop ---


def _loop(peek_script, *, clock=None):
    """Chạy loop tới khi peek_script cạn (mỗi phần tử: bool | Exception)."""
    stop = threading.Event()
    spawned: list[str] = []
    slept: list[float] = []
    script = list(peek_script)

    def peek(telegram, *, offset):
        if not script:
            stop.set()
            return False
        item = script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    tl.run_listener_loop(
        "thu-ky", _TELEGRAM, Path("/nonexistent-dir-ok"),  # load_offset: missing → None
        run_inbox_worker=spawned.append, stop_event=stop,
        peek=peek, clock=clock or (lambda: 0.0), sleep=slept.append,
    )
    return spawned, slept


def test_loop_spawns_worker_on_updates_and_rearms():
    spawned, slept = _loop([False, True, False])
    assert spawned == ["thu-ky"]
    assert slept == []


def test_loop_survives_peek_errors_with_backoff():
    spawned, slept = _loop([RuntimeError("409 Conflict"), OSError("net down"), True])
    assert spawned == ["thu-ky"]
    assert slept == [tl._ERROR_BACKOFF_S, tl._ERROR_BACKOFF_S]


def test_loop_rate_cap_defers_instead_of_spawning():
    burst = [True] * (tl._MAX_SPAWNS_PER_WINDOW + 2)
    spawned, slept = _loop(burst, clock=lambda: 100.0)  # đứng im trong 1 cửa sổ
    assert len(spawned) == tl._MAX_SPAWNS_PER_WINDOW  # phần dư bị chặn
    assert len(slept) == 2  # 2 lần vượt cap → sleep-nhường, không spawn
    assert all(s >= tl._ERROR_BACKOFF_S for s in slept)


def test_loop_worker_failure_does_not_kill_listener():
    stop = threading.Event()
    calls: list[str] = []
    script = [True, True]

    def peek(telegram, *, offset):
        if not script:
            stop.set()
            return False
        return script.pop(0)

    def worker(agent_id):
        calls.append(agent_id)
        raise RuntimeError("worker exploded")

    slept: list[float] = []
    tl.run_listener_loop(
        "thu-ky", _TELEGRAM, Path("/nonexistent-dir-ok"),
        run_inbox_worker=worker, stop_event=stop,
        peek=peek, clock=lambda: 0.0, sleep=slept.append,
    )
    assert calls == ["thu-ky", "thu-ky"]  # vẫn kích tiếp sau lỗi


# --- service wiring ---


def test_start_telegram_listeners_starts_daemon_thread_per_agent():
    stop = threading.Event()
    stop.set()  # loop thoát ngay — chỉ kiểm wiring
    threads = tl.start_telegram_listeners(
        [("a1", _TELEGRAM, Path("/tmp")), ("a2", _TELEGRAM, Path("/tmp"))],
        run_inbox_worker=lambda agent_id: None, stop_event=stop,
    )
    assert [t.name for t in threads] == ["tg-listener-a1", "tg-listener-a2"]
    assert all(t.daemon for t in threads)
    for t in threads:
        t.join(timeout=5)
        assert not t.is_alive()
