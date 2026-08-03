---
title: Thư ký riêng CEO trên Telegram (v57)
description: >-
  Agent thư ký riêng cho CEO, full-ga trong khung an toàn, tham chiếu năng lực
  Pong (openclaw)
status: pending
priority: P1
created: 2026-08-03T00:00:00.000Z
---

# Thư ký riêng CEO trên Telegram (v57)

## Overview

Tạo agent "thư ký riêng" cho CEO: bot Telegram riêng, trả lời DM, briefing chủ động sáng/tuần,
đọc Gmail/Calendar/Drive, tra web, memory daily-notes + search. Tham chiếu năng lực: hồ sơ Pong
`/Users/phucnt/workspace/openclaw-workspace/plans/reports/reference-260803-1805-openclaw-personal-assistant-capability-profile-report.md`.

**3 quyết định CEO đã chốt (brainstorm 2026-08-03):**

1. **"Không hạn chế" = full-ga trong khung an toàn** — `trust_mode: autonomous`, `dry_run: false`,
   bật hết cờ đọc, auto-approve Lớp B qua trusted Telegram sender (trust ladder v8 M23 sẵn có).
   **Giữ nguyên Lớp A** (xoá vĩnh viễn / lộ credential / đổi permission) — không viết bypass.
2. **Làm cả 4 nhóm tính năng, tuần tự theo ưu tiên** (phase 1→5 dưới).
3. **Code mới vào product** (`my_crew/` + `domain-packs/personal-pack/`, có tests) — hồ sơ thư ký
   của CEO chỉ là 1 profile user-data (gitignored, không commit).

**NGOÀI phạm vi (đối chiếu Pong, chủ động bỏ):** host-exec không sandbox (phá bất biến lõi),
browser tool, media (image/video/tts/music), Telegram streaming partial, Memory Dreaming,
heartbeat (watchers + cron đã phủ), multi-agent spawn (team feature đã có).

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [Personal pack + hồ sơ thư ký + chat lõi](./phase-01-personal-pack-h-s-th-k-chat-l-i.md) | Completed |
| 2 | [Briefing chủ động (morning + weekly)](./phase-02-briefing-ch-ng-morning-weekly.md) | Pending |
| 3 | [Gmail Calendar Drive (gws)](./phase-03-gmail-calendar-drive-gws.md) | Pending |
| 4 | [Web search cho thư ký](./phase-04-web-search-cho-th-k.md) | Pending |
| 5 | [Memory nâng cao (daily notes + search)](./phase-05-memory-n-ng-cao-daily-notes-search.md) | Pending |

## Dependencies

- Phase 2–5 phụ thuộc Phase 1 (profile + pack phải chạy được chat trước).
- Phase 3, 4 độc lập nhau và độc lập Phase 2 — có thể đảo thứ tự nếu chờ user action (bot token, API key).
- User actions cần CEO tự làm: tạo bot BotFather (P1), OAuth Google (P3), API key search (P4).

## Acceptance (toàn plan)

- [ ] Nhắn DM bot thư ký → trả lời đúng persona, có dữ liệu thật (Jira/GitHub/lịch sử).
- [ ] 7:00 sáng nhận Morning Briefing, CN 8:00 nhận Weekly Review — không cần hỏi.
- [ ] Hỏi "hôm nay có lịch gì / email nào cần trả lời" → đọc gws thật trả lời.
- [ ] Việc ghi (gửi mail, append Sheets…) tự chạy qua auto-approve, vẫn audit đầy đủ; Lớp A vẫn chặn.
- [ ] Thư ký nhớ việc qua ngày (daily notes) và tra lại được ("tuần trước tôi dặn gì?").
- [ ] Toàn suite BE/FE/e2e xanh; 6 bất biến HANDOVER §5 không đổi.
