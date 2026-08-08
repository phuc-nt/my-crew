"""Chat web lookup (v57 P4) — cho đường Q&A M11 tra web mà không cần tool-loop.

M11 là một lượt compose duy nhất (không tool-loop), nên "tra web trong chat" chạy theo
nhịp 2-pass rẻ nhất có thể:

    pass 1: compose bình thường + 1 rule marker → model CẦN web thì trả về đúng một dòng
            `WEB_SEARCH: <truy vấn>` (tin nhắn thường ⇒ zero chi phí thêm)
    giữa 2 pass: CODE chạy search (Tavily/Brave — cùng tool + audit redacted-query +
            formatter chống-injection của team-step v20.5) — LLM không bao giờ tự gọi mạng
    pass 2: compose lại với KẾT QUẢ WEB trong user message → trả lời có nguồn

Gate như team-step: profile `web_search: true` + có key trong env. Thiếu một trong hai ⇒
hook None, rule không chèn, đường QA byte-identical. Marker là READ thuần — một tin nhắn
prompt-injected "hãy trả về WEB_SEARCH: …" chỉ có thể kích một lượt tìm kiếm công khai
(bounded, audit), không chạm được gateway.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

#: Reply pass-1 mở đầu bằng chuỗi này (và chỉ 1 dòng) ⇒ yêu cầu tra web.
MARKER = "WEB_SEARCH:"
_QUERY_MAX = 200

#: Rule chèn vào system prompt CHỈ khi hook khả dụng.
WEB_RULE = (
    "TRA CỨU WEB: nếu câu hỏi cần thông tin công khai mà DATA/TRÍ NHỚ không có (tin tức, "
    "giá cả, sự kiện đang diễn ra), trả về DUY NHẤT một dòng theo dạng "
    f"`{MARKER} <truy vấn ngắn>` — không kèm bất kỳ chữ nào khác. Hệ thống sẽ tra giúp và "
    "đưa kết quả để bạn trả lời ở lượt kế. Chỉ dùng khi thật sự cần; câu trả lời cuối phải "
    "ghi rõ nguồn (tên trang/URL)."
)


def extract_query(reply: str) -> str | None:
    """Truy vấn từ reply pass-1, hoặc None. CHỈ nhận reply đúng-một-dòng bắt đầu bằng
    marker — model vừa trả lời vừa kèm marker là làm sai giao thức, coi như văn bản."""
    text = (reply or "").strip()
    if "\n" in text or not text.startswith(MARKER):
        return None
    query = text[len(MARKER):].strip()
    if not query or len(query) > _QUERY_MAX:
        return None
    return query


def build_chat_search_hook(loaded, settings) -> Callable[[str], str] | None:
    """`query → khối kết quả đã format` — None khi agent không bật cờ hoặc thiếu key.

    Cùng nguyên liệu với hook team-step (v20.5): WebSearchConfig từ Settings (key chỉ ở
    env), audit redacted-query vào trail per-agent, `format_search_results` bọc nội dung
    web không tin cậy (4 lớp chống injection)."""
    if loaded is None or not getattr(loaded, "web_search", False):
        return None
    from my_crew.tools.web_search_tool import WebSearchConfig, web_search

    config = WebSearchConfig(
        tavily_api_key=getattr(settings, "tavily_api_key", None),
        brave_api_key=getattr(settings, "brave_api_key", None),
    )
    if not config.available():
        return None
    from my_crew.audit.audit_log import AuditLog

    audit_log = AuditLog(Path(settings.data_dir) / "audit" / "audit.jsonl")

    def _hook(query: str) -> str:
        from my_crew.tools.search_result_formatter import format_search_results

        actor = Path(str(getattr(settings, "data_dir", ""))).name
        results = web_search(query, config=config, audit_log=audit_log, actor=actor)
        text, count, quarantined = format_search_results(results)
        if quarantined:
            logger.info("chat web lookup: %d/%d kết quả bị cách ly", quarantined, count)
        return text

    return _hook
