---
title: Thư ký riêng CEO trên Telegram (v57)
description: >-
  Agent thư ký riêng cho CEO, full-ga trong khung an toàn, tham chiếu năng lực
  Pong (openclaw)
status: completed
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
| 2 | [Briefing chủ động (morning + weekly)](./phase-02-briefing-ch-ng-morning-weekly.md) | Completed |
| 3 | [Gmail Calendar Drive (gws)](./phase-03-gmail-calendar-drive-gws.md) | Completed |
| 4 | [Web search cho thư ký](./phase-04-web-search-cho-th-k.md) | Completed |
| 5 | [Memory nâng cao (daily notes + search)](./phase-05-memory-n-ng-cao-daily-notes-search.md) | Completed |

## Dependencies

- Phase 2–5 phụ thuộc Phase 1 (profile + pack phải chạy được chat trước).
- Phase 3, 4 độc lập nhau và độc lập Phase 2 — có thể đảo thứ tự nếu chờ user action (bot token, API key).
- User actions cần CEO tự làm: tạo bot BotFather (P1), OAuth Google (P3), API key search (P4).

## Acceptance (toàn plan)

- [x] Nhắn DM bot thư ký → trả lời đúng persona, dữ liệu thật, TỨC THÌ (~1-2s, listener 1.5).
- [x] Briefing/Weekly theo lịch — UAT chạy tay giao thật; briefing 7:00 sáng 04/08 là lần tự
      chạy đầu (điểm xác nhận cuối, CEO để ý Telegram).
- [x] Hỏi lịch/email → đọc gws thật trả lời (Firecrawl + gws CLI dùng chung hạ tầng openclaw).
- [x] Việc ghi: `tao_lich` chạy ngay (autonomous) + audit; Lớp A vẫn chặn verb phá hoại
      (test phản chứng). Email KHÔNG làm — catalog cấm by design, ghi roadmap.
- [x] Nhớ qua ngày: daily notes 7 ngày + recall ở session mới (UAT thật).
- [x] Suite 2423 BE + 280 FE + 8 e2e xanh; 6 bất biến HANDOVER §5 nguyên vẹn (Lớp A không
      đổi một dòng; 2 fix còn SIẾT thêm: `{} or None` allowlist + calendarId argv).

**Hoàn thành 2026-08-03** — brainstorm → 5/5 phase + phase 1.5 phát sinh (instant chat), 7 commit,
3 vòng UAT thật bắt 6 bug/hành-vi lệch trước khi user gặp.
