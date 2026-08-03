---
phase: 3
title: Gmail Calendar Drive (gws)
status: completed
priority: P2
effort: 0.5d
dependencies:
  - 1
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

## Tiến độ 2026-08-03 — 3a (ĐỌC) xong, 3b (GHI) cần 1 quyết định thiết kế

**3a xong:** `gws` CLI đã cài + OAuth sẵn trên máy (Pong dùng chung CLI này) → KHÔNG cần
user action. `PersonalToolProvider.read` giờ ghép lịch 24h tới (`calendar +agenda`) + email
chưa đọc (`gmail +triage`) vào snapshot — chat DM lẫn briefing sáng tự giàu lên, degrade
per-source "(chưa đọc được: …)" khi CLI lỗi (không cần cờ: pack personal theo định nghĩa là
thư ký chủ máy; `gws_context: true` vẫn bật trong profile cho tier team-step). Smoke thật:
snapshot trả calendar + inbox thật. +2 test, suite 2407.

**3b (GHI) xong — CEO chốt "thư ký được quyền ghi":** catalog `commands.py` của pack với
lệnh `tao_lich` (native `gws_write`, argv CODE-fixed `calendar events insert`, slots chỉ vào
`--json`) — trust_mode autonomous nên chạy ngay + audit, không cần cấu hình auto_approve
riêng. **Email KHÔNG làm**: catalog cấm type `email_send` by design (v31 P2) — muốn có phải
nới vetted-types, để lại như một quyết định riêng nếu CEO thật sự cần.

**2 bug thật UAT 3b bắt được:**
- Argv calendar insert (cả chat-ops v39 lẫn lệnh mới) thiếu path-param `calendarId` — Google
  400, tức lệnh v39 CHƯA TỪNG chạy nổi với API thật mà test vẫn xanh (pin đúng argv hỏng —
  phantom coverage lần 2 của repo). Fix: builder chung `calendar_insert_argv()` (+ `--params
  '{"calendarId":"primary"}'`), test cập nhật theo argv đã nghiệm thật.
- `gws_write` handler chỉ lấy stderr khi lỗi → noise keyring che mất JSON lỗi API ở stdout.
  Fix: ghép cả hai vào detail.
- Classifier lệnh chat không biết "bây giờ" → slot thời gian tương đối ("tối nay") bịa ngày.
  Fix core: chèn `BÂY GIỜ: <ISO local>` vào prompt phân loại.

**UAT thật:** tin nhắn "đặt giúp anh lịch … 23 giờ 15 tối nay" → classifier điền RFC3339 đúng
ngày → gateway tự duyệt (autonomous) → sự kiện có thật trên Calendar (đã xoá 2 event test).
Suite 2409 + 12 test pack, ruff sạch.

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

- [x] Đọc lịch + email chưa đọc từ dữ liệu thật (smoke provider + chat DM).
- [x] Lệnh ghi (tạo lịch) qua chat chạy ngay (autonomous) + audit; sự kiện lên Calendar thật.
- [x] Verb destructive không thể lọt: slot chỉ vào --json (test), argv chế tay có `delete`
      bị Lớp A chặn (test); email bị loại khỏi catalog by design — ghi nhận, không làm.

## Risk Assessment

- Đây là phase đầu tiên agent GHI ra ngoài không hỏi — cap/ngày là phanh chính, bắt đầu thấp.
- Email nhạy cảm trong context: chỉ internal audience; không route công việc gws qua deep_agent
  (sanitizer sẽ redact tên người — không phù hợp thư ký).
