---
phase: 5
title: Memory nâng cao (daily notes + search)
status: completed
priority: P2
effort: 1.5d
dependencies:
  - 1
---

# Phase 5: Memory nâng cao (daily notes + search)

## Overview

Nâng memory lên gần Pong: (a) **daily notes** `profiles/<id>/memory/YYYY-MM-DD.md` — agent tự ghi
sau mỗi lượt việc, tự đọc lại 2 ngày gần nhất mỗi session; (b) **memory search** — tìm lại trên
toàn bộ memory files ("tuần trước tôi dặn gì?"). Hiện trạng: chỉ MEMORY.md (mirror section +
consolidation đêm) và history.search (SQLite keyword trên steps/audit, KHÔNG phủ memory files).

## Requirements

- Functional: sau mỗi lượt chat/briefing có thông tin đáng nhớ → 1-3 dòng vào daily note của
  ngày; context mỗi run nạp MEMORY.md + 2 daily notes gần nhất; tool `memory.search` cho agent
  tra memory files theo từ khoá.
- Non-functional: chặn phình token (cap kích thước note/ngày + cap phần nạp context); memory là
  internal-only (external audience không bao giờ thấy — theo audience-split hiện có); feature
  opt-in qua `memory:` config, agent khác zero thay đổi.

## Architecture (quyết định trước khi code)

- **Search: keyword FTS trước, embeddings sau.** Mở rộng index SQLite của
  `history_search_index.py` (hoặc index chị em cùng pattern) phủ `profiles/<id>/memory/*.md`.
  Embeddings/semantic để dành cho provider `kioku` (đã reserve trong `memory/provider.py`) —
  chỉ làm khi keyword chứng minh không đủ. KISS.
- **Ghi note:** tái dùng đường `memory_node.py`/`memory_extractor.py` (đang nuôi mirror section)
  — extractor bắn thêm bản ghi vào daily note thay vì viết cơ chế trích xuất mới.
- **Nạp context:** mở rộng `resolve_memory_text` (memory/provider.py) ghép MEMORY.md + 2 notes
  gần nhất, cap tổng ký tự (đề xuất 12K) — cắt từ cũ nhất.
- Consolidation đêm hiện có giữ nguyên vai trò distill MEMORY.md; note cũ >30 ngày để nguyên
  (file nhỏ, không GC vội — YAGNI).

## Related Code Files

- Đọc trước: `my_crew/memory/provider.py`, `my_crew/agent/memory_node.py`, `memory_extractor.py`,
  `memory_mirror.py`, `my_crew/memory/consolidation.py`, `my_crew/runtime/history_search_index.py`,
  `read_only_toolset.py` (đăng ký tool mới).
- Create: `my_crew/memory/daily_notes.py` (đọc/ghi/nạp), index memory search + tool
  `memory.search`, tests cho cả ba.
- Modify: `provider.py` (ghép context), `memory_node.py` (ghi note), `read_only_toolset.py`
  (tool, internal-only), `loader_mapping.py` (cờ trong `memory:`), profile thư ký (bật).

## Implementation Steps

1. Đọc 6 file trên → chốt điểm móc chính xác (ghi ở node nào, nạp ở đâu) — ghi lại rồi mới code.
2. `daily_notes.py`: append có khoá ngày + cap/ngày; loader nạp 2 ngày gần nhất.
3. Móc extractor → daily note (kèm cờ tắt); test: 2 lượt chat cùng ngày append cùng file.
4. Index + tool `memory.search` (internal-only, policy-shim như tools khác); test: tìm ra dòng
   note tuần trước, external-audience không có tool này.
5. Bật cho thư ký; UAT: dặn 1 việc hôm nay → hỏi lại "hôm qua/tuần này tôi dặn gì" ở session mới.

## Success Criteria

- [x] Dặn việc → xuất hiện trong daily note; session mới trả lời đúng không cần nhắc lại
      (UAT thật: dặn quà sinh nhật → note có mốc 08/08 tự tính; hỏi lại ở session mới →
      trả lời từ nhật ký + dữ liệu gws thật).
- [x] ~~`memory.search`~~ **BỎ có chủ đích**: chat DM đi đường M11 không có tool-loop —
      tool search chỉ phục vụ team-step, trong khi cửa sổ 7 ngày nạp thẳng context đã phủ
      "tuần trước dặn gì". Làm khi có pain signal thật (ghi roadmap, không làm mù).
- [x] Agent không bật `memory.daily_notes` → hành vi byte-identical; suite 2418 xanh.

## Kết quả (2026-08-03)

- **Phát hiện nền:** đường chat trước v57 KHÔNG có trí nhớ nào — "dặn em nhớ X" trả lời
  xong là quên. Core của phase hoá ra là hook remember vào chat, không phải search.
- Đã dựng: `my_crew/memory/daily_notes.py` (append theo ngày + nạp 7 ngày, cap file/ngày
  4K + cap context 8K, path-confined, file lạ bỏ qua) · `chat_memory.remember_chat_exchange`
  (chạy SAU khi reply đã gửi — không cộng độ trễ; không bao giờ raise) · `resolve_memory_text`
  ghép "NHẬT KÝ GẦN ĐÂY" khi opt-in `memory.daily_notes: true` · extractor nhận `system`
  prompt riêng cho chat (tiêu chí "đáng nhớ" của thư ký ≠ sự kiện dự án — prompt dự án
  lúc trích lúc không với chat).
- **UAT bắt 2 lỗi hành vi:** (1) classifier tạo lịch quá tay — "nhắc anh review…" thành
  sự kiện Calendar thật → siết description `tao_lich` (chỉ sự kiện có thời điểm cụ thể;
  lời dặn ⇒ question); (2) markdown `**` vẫn lọt dù prompt cấm → strip cấu trúc trong
  `sanitize_reply` (hope-level → guarantee). Sự kiện lạc đã xoá.
- 9 test mới (tests/test_memory_daily_notes.py); suite 2418; ruff sạch.

## Risk Assessment

- Phình context = phình chi phí: cap 12K + đo token thực tế trong UAT trước khi chốt số.
- Note chứa thông tin cá nhân CEO: nằm trong profiles/ (gitignored) — thêm test khẳng định
  đường ghi không bao giờ trỏ ra ngoài profile dir (path-confinement như artifact dir).
