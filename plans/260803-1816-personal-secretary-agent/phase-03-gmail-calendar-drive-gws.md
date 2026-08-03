---
phase: 3
title: "Gmail Calendar Drive (gws)"
status: pending
priority: P2
effort: "0.5d"
dependencies: [1]
---

# Phase 3: Gmail Calendar Drive (gws)

## Overview

Bật cho thư ký đọc Gmail/Calendar/Drive (`gws_context: true` — tools `gws.gmail/calendar/drive`
đã có trong read_only_toolset, INTERNAL-only) và cho phép việc ghi (gws_write, email_send) tự
chạy qua auto-approve trust ladder thay vì chờ duyệt tay.

## Requirements

- Functional: hỏi "hôm nay có lịch gì / email nào chưa đọc quan trọng / tìm file X trên Drive"
  → trả lời từ dữ liệu thật. "Gửi mail trả lời anh A" → chạy ngay (auto-approve), vẫn audit.
- Non-functional: OAuth token không vào repo/log; DM Telegram là internal audience nên reads
  không bị audience-split chặn (xác nhận lại bằng test/UAT chứ không giả định).

## Architecture

- Reads: đã có sẵn, chỉ bật cờ profile. Xác minh cách auth của adapter gws (CLI `gws`? service
  nào?) trong code trước khi hướng dẫn CEO OAuth — bước 1.
- Writes: `gws_write` + `email_send` là Lớp B. Cấu hình profile `auto_approve:` (đã có
  `_parse_auto_approve` + `auto_approve_policy.py`): grants theo action-type, trusted_senders =
  Telegram user id CEO, daily cap. KHÔNG nới Lớp A (mail có attachment ngoài artifact dir,
  verb destructive gws… vẫn bị chặn — đúng thiết kế).
- Nếu argv cố định của reads thiếu lệnh thư ký cần (vd search query Gmail) → chỉ mở rộng khi
  UAT chứng minh thiếu, mỗi lệnh mới đi kèm test + giữ nguyên nguyên tắc argv cố định.

## Related Code Files

- Đọc trước: `my_crew/runtime_backends/read_only_toolset.py` (gws tools + `_INTERNAL_ONLY_READS`),
  adapter gws thực tế (grep `gws` trong my_crew/), `my_crew/actions/hard_block.py`
  (`_GWS_ALLOWLIST_PREFIXES`, `_hard_deny_email`), `my_crew/actions/auto_approve_policy.py`.
- Modify: `profiles/thu-ky/profile.yaml` (gws_context, auto_approve grants — user-data);
  chỉ đụng product code nếu bước "mở rộng argv" được kích hoạt có bằng chứng.

## Implementation Steps

1. Đọc adapter gws → viết hướng dẫn OAuth ngắn cho CEO (user action; token để đúng chỗ adapter
   đọc, ngoài repo).
2. Bật `gws_context: true`; UAT 3 câu hỏi đọc (lịch/mail/drive) qua Telegram thật.
3. Khai `auto_approve:` cho `email_send` + `gws_write`, trusted sender = CEO, cap/ngày hợp lý
   (đề xuất 20). UAT: nhờ gửi 1 mail test → đi thẳng không chờ duyệt, audit ghi
   `auto_approve:trusted_sender:<id>`.
4. UAT phản chứng: giả lệnh chứa verb destructive (xoá file Drive) → Lớp A chặn, thư ký báo lại
   lý do lịch sự.

## Success Criteria

- [ ] 3 câu đọc gws trả lời đúng dữ liệu thật.
- [ ] Mail test gửi ngay qua auto-approve, có audit; quá cap/ngày → rơi về queue duyệt tay.
- [ ] Lệnh destructive bị Lớp A chặn (bằng chứng audit), thư ký giải thích thay vì im lặng.

## Risk Assessment

- Đây là phase đầu tiên agent GHI ra ngoài không hỏi — cap/ngày là phanh chính, bắt đầu thấp.
- Email nhạy cảm trong context: chỉ internal audience; không route công việc gws qua deep_agent
  (sanitizer sẽ redact tên người — không phù hợp thư ký).
