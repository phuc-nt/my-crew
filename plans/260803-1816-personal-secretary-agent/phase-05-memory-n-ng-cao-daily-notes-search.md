---
phase: 5
title: "Memory nâng cao (daily notes + search)"
status: pending
priority: P2
effort: "1.5d"
dependencies: [1]
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

- [ ] Dặn việc → xuất hiện trong daily note; session mới trả lời đúng không cần nhắc lại.
- [ ] `memory.search` tìm được note cũ; external audience không truy cập được.
- [ ] Agent không bật `memory:` mới → hành vi y hệt cũ; suite xanh.

## Risk Assessment

- Phình context = phình chi phí: cap 12K + đo token thực tế trong UAT trước khi chốt số.
- Note chứa thông tin cá nhân CEO: nằm trong profiles/ (gitignored) — thêm test khẳng định
  đường ghi không bao giờ trỏ ra ngoài profile dir (path-confinement như artifact dir).
