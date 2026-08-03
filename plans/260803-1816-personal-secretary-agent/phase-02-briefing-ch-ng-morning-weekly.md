---
phase: 2
title: Briefing chủ động (morning + weekly)
status: completed
priority: P1
effort: 0.5d
dependencies:
  - 1
---

# Phase 2: Briefing chủ động (morning + weekly)

## Overview

**Thiết kế đổi so với plan gốc** (phát hiện ở phase 1): không cần run-kind mới trong core —
pack đã sở hữu kind `briefing` chạy được qua `schedule:` chuẩn. Phase 2 = thêm kind
`weekly-review` vào pack + nối cron trong profile: Morning 7:00 hằng ngày + Weekly CN 8:00.

## Requirements

- Functional: 7:00 sáng nhận bản tin ngày; CN 8:00 nhận bản nhìn-lại-tuần — không cần hỏi.
- Non-functional: dedup 1 bản/ngày/kind (đã có, thêm kind vào hint); agent khác zero thay đổi;
  weekly cũng internal-only như briefing.

## Related Code Files

- Modify: `domain-packs/personal-pack/graphs.py` (builder tham số hoá theo kind),
  `pack.yaml` (thêm kind), `tests/test_personal_pack.py`.
- Create: `domain-packs/personal-pack/prompts/weekly-review-system.md`.
- User-data: `profiles/thu-ky/profile.yaml` — `reports: [briefing, weekly-review]`,
  `schedule: {briefing: "0 7 * * *", weekly-review: "0 8 * * 0"}`.

## Implementation Steps

1. Tham số hoá `build_briefing_graph` theo kind (prompt `<kind>-system`, dedup hint
   `personal-<kind>:<chat>:<date>`, rationale riêng); `REPORT_KINDS` 2 kind.
2. Prompt weekly: nhìn lại tuần từ TRÍ NHỚ (việc dặn còn treo, việc đã xong), hướng tuần tới.
3. Tests: assembly 2 kind; weekly chạy offline; 2 kind cùng ngày KHÔNG dedup lẫn nhau.
4. Profile: reports + schedule; restart service; verify /api/schedule/upcoming có 2 dòng.
5. UAT: chạy tay `my-crew agent run thu-ky --report weekly-review` → nhận bản thật.

## Success Criteria

- [x] Schedule hiện `thu-ky | briefing | 07:00 (04/08)` và `weekly-review | CN 09/08 08:00`.
- [x] Weekly chạy tay giao bản thật (executed, $0.0008; xưng em/anh + plain text đúng
      prompt mới; sửa thêm: lời chào lấy theo DATA thay vì hardcode "Chủ Nhật").
- [x] Suite xanh (2406); dedup hai kind độc lập (test cross-kind trong live-send test).
- [ ] Briefing 7:00 sáng mai tự đến — CEO xác nhận sau (điểm mở duy nhất).

## Risk Assessment

- Giờ chạy lệch ≤1 tick phút — chấp nhận, như mọi kind.
- Service seed lịch lúc boot → đổi schedule profile cần restart service (ghi vào hướng dẫn).
