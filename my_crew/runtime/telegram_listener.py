"""Wake-on-message Telegram listener (v57) — DM được trả lời ~1-2s thay vì chờ tick phút.

Mỗi agent có `telegram:` được MỘT thread long-poll "peek": `getUpdates(timeout=45)` treo
chờ Telegram — KHÔNG LLM, KHÔNG parse nội dung, KHÔNG advance offset. Có update rơi vào
→ spawn đúng worker subprocess `inbox` sẵn có (pipeline trả lời, bootstrap, offset,
dedup, cap 3 trả lời/poll — nguyên vẹn) và CHỜ worker xong mới treo peek tiếp, nên chính
listener không bao giờ tạo 2 getUpdates song song.

Vì sao peek-then-spawn thay vì trả lời ngay trong thread: giữ bất biến "LLM chạy trong
worker subprocess" (cách ly tiến trình), và tái dùng nguyên đường inbox đã có test.

Đồng tồn tại với inbox theo lịch (giữ nguyên làm fallback khi thread chết): Telegram chỉ
cho một getUpdates treo mỗi bot — fetch của worker theo lịch sẽ ngắt peek đang treo bằng
409 Conflict. Peek coi 409/lỗi mạng là chuyện thường: backoff ngắn rồi treo lại, không
bao giờ làm chết thread hay ghi nhận run lỗi.

Rate cap: listener kích tối đa `_MAX_SPAWNS_PER_WINDOW` worker mỗi cửa sổ 60s — một trận
flood tin nhắn không đốt LLM vô hạn. Phần dư nằm trong backlog Telegram; lần peek sau
hoặc tick theo lịch xử lý tiếp, vẫn dưới cap trả lời của chính inbox.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from my_crew.config.telegram_config import TelegramConfig
from my_crew.config.telegram_token import resolve_bot_token
from my_crew.runtime.telegram_inbox import load_offset

logger = logging.getLogger(__name__)

#: Telegram giữ request mở tối đa chừng này giây (API cap ~50); socket timeout phải lớn hơn.
_LONG_POLL_S = 45
_SOCKET_TIMEOUT_S = _LONG_POLL_S + 10
#: Nghỉ sau lỗi peek (409 do tick lịch fetch, mạng rớt…) trước khi treo lại.
_ERROR_BACKOFF_S = 3.0
#: Trần số worker listener được kích trong một cửa sổ — phanh chi phí LLM khi bị flood.
_MAX_SPAWNS_PER_WINDOW = 6
_WINDOW_S = 60.0

#: Callback chạy MỘT lượt inbox cho agent (spawn worker subprocess + chờ xong).
RunInboxWorker = Callable[[str], Any]


def peek_has_updates(
    telegram: TelegramConfig, *, offset: int | None, timeout_s: float = _LONG_POLL_S
) -> bool:
    """Long-poll một nhịp: có update nào đang chờ từ `offset` không? KHÔNG đổi state.

    `offset=None` (chưa bootstrap) → -1: Telegram chỉ trả update MỚI NHẤT — đủ để đánh
    thức worker, và chính worker sẽ bootstrap-ack backlog như nó vẫn làm ở tick lịch.
    """
    token = resolve_bot_token(telegram)
    from my_crew.actions.telegram_write import api_call

    payload: dict[str, Any] = {
        "timeout": int(timeout_s),
        "allowed_updates": ["message", "callback_query"],
        "offset": offset if offset is not None else -1,
    }
    updates = api_call(token, "getUpdates", payload, timeout_s=_SOCKET_TIMEOUT_S)
    return bool(updates)


def run_listener_loop(
    agent_id: str,
    telegram: TelegramConfig,
    data_dir: Path,
    *,
    run_inbox_worker: RunInboxWorker,
    stop_event: threading.Event,
    peek: Callable[..., bool] = peek_has_updates,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Vòng đời một listener: peek treo → (có tin) spawn worker → chờ xong → peek tiếp."""
    spawn_times: deque[float] = deque()
    logger.info("telegram listener %s: started (long-poll %ds)", agent_id, _LONG_POLL_S)
    while not stop_event.is_set():
        try:
            has_updates = peek(telegram, offset=load_offset(Path(data_dir)))
        except Exception as exc:  # noqa: BLE001 — 409/mạng rớt là thường; thread bất tử
            logger.debug("telegram listener %s: peek interrupted (%s) — re-arming", agent_id, exc)
            sleep(_ERROR_BACKOFF_S)
            continue
        if not has_updates or stop_event.is_set():
            continue
        now = clock()
        while spawn_times and now - spawn_times[0] > _WINDOW_S:
            spawn_times.popleft()
        if len(spawn_times) >= _MAX_SPAWNS_PER_WINDOW:
            # Flood: nhường phần dư cho tick lịch / cửa sổ sau — backlog không mất
            # (offset chỉ advance khi worker xử lý), chi phí LLM bị chặn trần.
            wait = max(_WINDOW_S - (now - spawn_times[0]), _ERROR_BACKOFF_S)
            logger.warning(
                "telegram listener %s: rate cap (%d/%.0fs) — deferring %.0fs",
                agent_id, _MAX_SPAWNS_PER_WINDOW, _WINDOW_S, wait,
            )
            sleep(wait)
            continue
        spawn_times.append(now)
        try:
            run_inbox_worker(agent_id)
        except Exception:  # noqa: BLE001 — một lượt worker hỏng không được giết listener
            logger.warning("telegram listener %s: inbox worker failed", agent_id, exc_info=True)
            sleep(_ERROR_BACKOFF_S)


def start_telegram_listeners(
    agents: Iterable[tuple[str, TelegramConfig, Path]],
    *,
    run_inbox_worker: RunInboxWorker,
    stop_event: threading.Event | None = None,
) -> list[threading.Thread]:
    """Mỗi (agent_id, telegram, data_dir) một daemon thread. Trả về threads đã start.

    Daemon=True: service chết thì listener chết theo — không cần shutdown protocol
    riêng (tick lịch vẫn là fallback độc lập)."""
    stop = stop_event or threading.Event()
    threads: list[threading.Thread] = []
    for agent_id, telegram, data_dir in agents:
        thread = threading.Thread(
            target=run_listener_loop,
            args=(agent_id, telegram, data_dir),
            kwargs={"run_inbox_worker": run_inbox_worker, "stop_event": stop},
            name=f"tg-listener-{agent_id}",
            daemon=True,
        )
        thread.start()
        threads.append(thread)
    return threads
