---
phase: 2
title: "Briefing chủ động (morning + weekly)"
status: pending
priority: P1
effort: "1d"
dependencies: [1]
---

# Phase 2: Briefing chủ động (morning + weekly)

## Overview

Run-kind mới `briefing`: prompt cố định chạy theo cron, kết quả đẩy chủ động vào Telegram của
agent (qua gateway `telegram_send`). Cấu hình cho thư ký: Morning Briefing 7:00 hằng ngày +
Weekly Review CN 8:00 (Asia/Saigon) — ngang Pong.

## Requirements

- Functional: profile khai `briefings: [{id, cron, prompt}]` → mỗi mục due thì chạy LLM
  (đường Q&A M11 với tools đọc của runtime) rồi gửi kết quả vào chat Telegram bound của agent.
- Non-functional: dedup 1 lần/ngày/briefing (kể cả restart); DRY_RUN vẫn log-not-send;
  không LLM khi không due; đi qua gateway như mọi send (audit + secret-scan).

## Architecture

- Tái dùng tối đa: `run_qa_task` (recurring_task.py) đã chạy "câu hỏi cố định → M11 answer" —
  nhưng nó reply theo mention. Briefing = biến thể "không có tin nhắn đến": chạy answer path
  với question = prompt, rồi `send_telegram_message` (actions/telegram_write.py) tới chat bound.
  Pattern đẩy chủ động này ops_alert_runner.py / milestone_mirror_runner.py đã làm — soi trước.
- Schedule: parse `briefings:` trong profile loader (`loader_mapping.py` + `loader.py`), synthesize
  vào `_effective_schedule` (service.py) như watch/ops-alerts; dispatch kind mới trong `worker.py`.
- Dedup: theo pattern dedup key hiện có (`qa-task:{digest}:{day}` là mẫu).

## Related Code Files

- Đọc trước: `my_crew/runtime/recurring_task.py`, `my_crew/runtime/ops_alert_runner.py`,
  `my_crew/runtime/service.py::_effective_schedule`, `my_crew/runtime/worker.py`,
  `my_crew/profile/loader_mapping.py`, `my_crew/actions/telegram_write.py`.
- Create: `my_crew/runtime/briefing_runner.py` + tests.
- Modify: `loader.py`/`loader_mapping.py` (field `briefings:`), `service.py`, `worker.py`,
  `profiles/thu-ky/profile.yaml` (user-data: 2 briefing entries).

## Implementation Steps

1. Đọc 4 runner hiện có, chốt: briefing_runner tái dùng hàm nào của qa path (không copy).
2. Parse + validate `briefings:` (id kebab, cron hợp lệ, prompt non-empty; floor cron 5 phút
   dùng `hard_block.cron_floor_error` như schedule_update).
3. `briefing_runner.py`: due-check → LLM answer → telegram_send qua gateway → dedup claim/ngày.
   Yêu cầu agent có telegram binding; thiếu thì skip + log rõ (không crash tick).
4. Tests: due/không-due, dedup qua restart, DRY_RUN không gửi, thiếu telegram skip, prompt
   rỗng bị loader từ chối.
5. Cấu hình thư ký: morning 7:00 (tóm hôm nay: lịch, việc mở, follow-up) + weekly CN 8:00.
   Restart service, verify schedule; UAT: đổi cron tạm +5 phút để nhận thật 1 bản.

## Success Criteria

- [ ] `thu-ky | briefing:morning | 07:00` và `briefing:weekly` hiện trong schedule.
- [ ] Nhận briefing thật trên Telegram đúng giờ, chỉ 1 bản/ngày kể cả restart giữa chừng.
- [ ] Suite xanh; agent không có `briefings:` → zero hành vi mới.

## Risk Assessment

- Prompt briefing tự do = bề mặt prompt-injection thấp (operator viết, không phải dữ liệu ngoài) —
  giữ nguyên tầng format_internal_content khi nhét dữ liệu tool vào context.
- Giờ chạy phụ thuộc tick daemon: chấp nhận lệch ≤1 poll interval, ghi rõ trong docs.
