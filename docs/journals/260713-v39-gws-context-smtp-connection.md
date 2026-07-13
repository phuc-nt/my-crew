# v39 — Google Workspace context + SMTP connection UI
2026-07-13 · ✅ Done (2207 BE)

Từ đánh giá connection 260713: agent nhiều context/công cụ hơn. 3 phase, review Sonnet 0 finding, live E2E bắt 1 bug format.

## Làm gì
- **P1 Google READ (Gmail/Calendar/Drive)**: `src/tools/gws_read.py` — 3 helper spawn gws CLI với argv CODE-cố-định (`gmail +triage` / `calendar +agenda` / `drive files list`, thêm `--format json`). LLM chỉ truyền `query` (drive), không chạm argv. Tool trong `read_only_toolset` sau flag `gws_context` (mirror academic_search, mặc định TẮT), internal-only, degrade-to-string. Agent office/admin/researcher đọc được context công ty thật.
- **P2 SMTP-UI**: thêm 7 SMTP key vào SETUP_WRITABLE_KEYS + `_smtp_check` (present-only) + card "Email (SMTP)" ở Connections. Bịt lỗ v38 (send_message email cần SMTP mà UI không thấy).
- **P3 Calendar-create WRITE**: prefix `("calendar","events","insert")` vào `_GWS_ALLOWLIST_PREFIXES` + `"acl"` vào security markers. Chat-ops command `create_calendar_event` (slot→argv CODE-dựng→gateway, mirror v38 ops_send_message). Gmail-send KHÔNG làm (đã có email_send). Lớp B: guarded queue, autonomous audit; delete/acl/share = Lớp A.

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| gws-read flag-gated per-agent (mặc định TẮT) | Toolset byte-identical cho agent không bật; mirror academic_search | Phải bật `gws_context: true` từng agent |
| READ không qua Gateway, WRITE bắt buộc qua | Read không mutate (đúng nguyên tắc); calendar-create mutate → Lớp A/B | — |
| Drive metadata+link, không nội dung file | File lớn, tốn token; metadata đủ cho "tìm/liệt kê" | Đọc nội dung file để sau |
| Gmail-send KHÔNG làm (chỉ Calendar-create) | Đã có email_send — tránh 2 cửa mail | Gmail từ Workspace account thật để sau nếu cần |
| Thêm "acl" vào security markers | calendar acl insert = cấp quyền → deny theo CATEGORY rõ hơn "outside prefix" | substring match mãi (chấp nhận fail-closed) |

## Vấp & học được
- **Live E2E bắt bug format**: `gws +agenda`/`+triage` mặc định in TABLE, không JSON → parser tìm `{` fail. Unit test (fake subprocess) không bắt được vì fake trả JSON sẵn. Chạy gws CLI thật → thấy ngay → thêm `--format json`. Bài học lặp lại: fake-transport test không thay được 1 lượt gọi CLI thật.
- Review Sonnet trace mọi VERIFY HARD trên code thật, 0 finding: read-argv injection đóng (query là JSON data không phải argv token), audience gate đều, calendar marker scan ĐỌC được trong --json body (fail-closed có chủ đích, test rõ).
- SMTP_PASSWORD vào SETUP_WRITABLE_KEYS nhất quán với ATLASSIAN_API_TOKEN/SLACK token (không phải class rủi ro mới; FINISH_WRITABLE_KEYS chỉ dành login app).

## Mở / sang sau
- Google WRITE Gmail-send/Calendar-invite từ Workspace account (nếu admin-agent cần).
- Drive đọc nội dung file (hiện metadata-only).
- Notion (nếu công ty dùng).
