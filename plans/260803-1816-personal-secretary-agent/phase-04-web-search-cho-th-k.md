---
phase: 4
title: "Web search cho thư ký"
status: pending
priority: P3
effort: "0.25d"
dependencies: [1]
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

- [ ] 2 câu hỏi cần web trả lời được, có nguồn.
- [ ] Không key trong log/audit; suite xanh (nếu có sửa lệch provider-check thì kèm test).

## Risk Assessment

- Prompt-injection từ trang web → đã có lớp wrap nội dung không tin cậy; UAT thử 1 trang có
  chỉ thị ("ignore instructions") xác nhận thư ký không nghe theo.
