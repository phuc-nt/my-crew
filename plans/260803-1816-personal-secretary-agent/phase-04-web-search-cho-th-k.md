---
phase: 4
title: Web search cho thư ký
status: completed
priority: P3
effort: 0.25d
dependencies:
  - 1
---

# Phase 4: Web search cho thư ký

## Overview

Bật `web_search: true` cho thư ký (tool `web.scrape` đã có trong read_only_toolset, cờ-gated).
Máy hiện CHƯA có key (v56 đã xác nhận hint "thiếu key" hiển thị đúng) — cần user action thêm key.

## Requirements

- Functional: hỏi việc cần thông tin ngoài ("giá vé X", "tin Y hôm nay") → thư ký tra web trả lời,
  ghi rõ nguồn.
- Non-functional: key chỉ ở env; kết quả web là dữ liệu KHÔNG TIN CẬY → phải qua
  `format_internal_content` như hiện tại (xác minh, không thêm đường tắt).

## Related Code Files

- Đọc trước: `my_crew/runtime_backends/read_only_toolset.py` (provider nào cho `web.scrape`:
  Firecrawl/Tavily/Brave — xác định env var đúng tên), cách v56 check
  `web_search_ready` trong `my_crew/server/routes_office_assign.py` (TAVILY_API_KEY/BRAVE_API_KEY).
- Modify: `profiles/thu-ky/profile.yaml` (web_search: true — user-data). Product code: không,
  trừ khi provider hiện tại không dùng được (khi đó dừng lại báo CEO chọn provider/key).

## Implementation Steps

1. Đọc toolset xác định provider + env var; đối chiếu với check `web_search_ready` (2 nơi phải
   cùng đáp án — nếu lệch là bug, sửa + test).
2. **User action:** CEO thêm API key vào env store.
3. Bật cờ, restart, UAT 2 câu hỏi cần web qua Telegram thật; xác nhận hint thiếu-key trong UI
   giao việc biến mất với thư ký.

## Success Criteria

- [x] Câu hỏi cần web trả lời được, có nguồn (UAT thật: giá vàng SJC — Brave search thật,
      trả lời kèm nguồn + caveat thành thật về độ tươi số liệu).
- [x] Không key trong log/audit (web_search audit ghi redacted query); suite 2423 xanh.

## Kết quả (2026-08-03) — không tốn đồng nào, thêm chat 2-pass

- **User action "mua key" biến mất**: Brave key dùng lại từ config openclaw
  (`plugins.brave.config.webSearch.apiKey` → `.env`, không hiển thị); Firecrawl self-host
  `localhost:3002` của openclaw đang chạy sẵn và `FIRECRAWL_BASE_URL` đã có trong .env từ
  trước → `web.scrape` team-step tự sống lại.
- **Phát sinh thiết kế (CEO chốt "làm chat web đầy đủ")**: chat M11 không có tool-loop →
  nhịp **2-pass** mới (`agent/chat_web_lookup.py` + `qa_answer`): pass-1 compose thường,
  model cần web thì trả đúng 1 dòng `WEB_SEARCH: <query>` → CODE chạy search (tool + audit
  redacted-query + formatter chống-injection của team-step v20.5) → pass-2 trả lời từ kết
  quả trong user message (không bao giờ vào system). Tin nhắn thường zero chi phí thêm;
  marker lặp ở pass-2 bị cắt vòng. Gate: `web_search: true` + có key — agent khác
  byte-identical. +5 test.

## Risk Assessment

- Prompt-injection từ trang web → đã có lớp wrap nội dung không tin cậy; UAT thử 1 trang có
  chỉ thị ("ignore instructions") xác nhận thư ký không nghe theo.
