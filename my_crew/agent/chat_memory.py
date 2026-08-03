"""Chat remember (v57 P5) — sau một lượt chat internal ĐÃ GỬI THẬT, ghi điều đáng nhớ.

Trước v57 đường chat hoàn toàn không có trí nhớ: "dặn em nhớ X" trả lời xong là quên.
Hook này chạy SAU khi reply đã gửi (không cộng độ trễ vào câu trả lời): trích fact từ
cặp (tin nhắn, trả lời) bằng đúng extractor của remember-node, rồi ghi song song vào
daily note của ngày + mirror section MEMORY.md (đường nạp context sẵn có).

Gate như remember-node: chỉ khi profile opt-in `memory.daily_notes: true`, không dry-run.
KHÔNG BAO GIỜ raise — reply đã đến tay người dùng, một lỗi ghi nhớ chỉ được phép log.
Internal agent state — không qua Action Gateway.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

#: Extractor: text → list fact (chữ ký của `make_llm_extractor`).
Extractor = Callable[[str], list[str]]

#: Tiêu chí "đáng nhớ" cho CHAT thư ký — khác prompt báo cáo dự án (extractor mặc định):
#: lời dặn, hẹn/deadline, thói quen, việc đã làm giúp. Chat xã giao ⇒ dòng trống.
_CHAT_SYSTEM = (
    "Bạn trích những điều ĐÁNG NHỚ từ MỘT lượt trò chuyện giữa chủ nhân và thư ký riêng: "
    "lời dặn dò ('dặn em', 'nhắc anh…'), hẹn/deadline kèm mốc thời gian, thói quen/sở thích "
    "chủ nhân tiết lộ, việc thư ký vừa làm giúp (vd đã tạo sự kiện lịch). Trả về TỐI ĐA 3 "
    "gạch đầu dòng NGẮN tiếng Việt, mỗi dòng tự đứng được (kèm mốc thời gian nếu có). "
    "TUYỆT ĐỐI không token/khóa/bí mật. Chào hỏi xã giao hay không có gì đáng nhớ ⇒ trả về "
    "dòng trống."
)


def remember_chat_exchange(
    loaded, settings, *, question: str, reply: str, extractor: Extractor | None = None
) -> int:
    """Trích + ghi fact từ một lượt chat. Trả số fact đã ghi (0 khi gate chặn/không có gì)."""
    try:
        config = getattr(loaded, "memory_config", None)
        if config is None or not getattr(config, "daily_notes", False):
            return 0
        if getattr(settings, "dry_run", True):
            return 0
        exchange = f"CHỦ NHÂN nhắn: {question.strip()}\nĐÃ TRẢ LỜI: {reply.strip()}"
        if extractor is None:
            from my_crew.agent.memory_extractor import make_llm_extractor
            from my_crew.llm.client import LlmClient

            extractor = make_llm_extractor(LlmClient(settings), system=_CHAT_SYSTEM)
        facts = [f for f in extractor(exchange) if f.strip()]
        if not facts:
            return 0
        from my_crew.agent.memory_mirror import write_memory_file
        from my_crew.memory.daily_notes import append_daily_note
        from my_crew.profile.loader import profile_memory_path

        profile_id = getattr(loaded, "profile_id", "") or ""
        written = append_daily_note(profile_id, facts)
        write_memory_file(profile_memory_path(profile_id), facts)
        # v58 P7: provider kioku ⇒ fact còn vào vault (một entry/lượt) cho recall ngữ
        # nghĩa về sau. Best-effort như mọi thứ ở đây — kioku_remember tự degrade.
        if getattr(config, "provider", "static") == "kioku":
            from my_crew.memory.kioku_provider import kioku_remember

            kioku_remember(profile_id, "\n".join(facts))
        return written
    except Exception:  # noqa: BLE001 — trí nhớ hỏng không được phá lượt chat đã xong
        logger.warning("chat remember thất bại (bỏ qua)", exc_info=True)
        return 0
