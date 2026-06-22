# Phase 5 — Audience-split Reporting

2026-06-22 · ✅ Done (269 UT, reviewed, E2E thật: external → Lớp B → approve → post)

## Làm gì
- **`--audience internal|external`** cho cả 4 loại report (daily/weekly/okr/resource). `internal` (mặc định) = hành vi cũ **byte-identical**; `external` = giọng business cho stakeholder, BỎ chi tiết nội bộ (mã issue, số PR, tên người, labor cost).
- **External → Lớp B sẵn có**: report external post Slack short tới `SLACK_STAKEHOLDER_CHANNEL` (config mới). Channel đó BẮT BUỘC nằm trong `SLACK_EXTERNAL_CHANNELS` → `needs_interrupt` (Phase 2, KHÔNG sửa) tự route Lớp B → queue chờ người duyệt. KHÔNG cơ chế duyệt mới, KHÔNG đổi gateway/allowlist.
- `audience_delivery.resolve_audience_delivery`: external → (stakeholder channel, dedup `{kind}-external-{today}`); internal → (None, `{kind}-{today}` **không đổi**); raise nếu external mà thiếu stakeholder channel (không im lặng fallback về channel nội bộ).
- `pending_approval` = SUCCESS cho external (cả 3 graph ok-check). External weekly BỎ section OKR/resource nhúng (nhiễu nội bộ). External resource short BỎ tên người + labor.

## Quyết định & vì sao
| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| Chỉ làm audience-split, hoãn service/bot/multi-user | Slack MCP browser-token **send-only** (không nhận event) → bot UI cần hạ tầng mới lớn | Roadmap P5 còn 1 phần lớn để sau |
| External dùng lại Lớp B qua channel selection | Đúng guardrail sẵn có, không mở đường mới | Foot-gun: stakeholder channel phải ∈ external set (validate raise) |
| internal dedup hint GIỮ `{kind}-{today}` | Backward-compat: re-run cùng ngày không double-post | Chỉ external thêm hậu tố `-external-` |

## Vấp & học được
- **Code review bắt C1 (privacy leak thật)**: external resource Slack short SẠCH (không tên/labor), NHƯNG nó **link tới trang Confluence** mà trang đó vẫn render bảng per-assignee đầy đủ (tên, count, labor `$`). Stakeholder click 1 phát là thấy hết. Test bỏ sót vì chỉ check text của short. Vá: external resource short BỎ link Confluence (trang vẫn tạo, internal-visibility, không trao URL). Bài học: privacy phải tính cả **artifact liên kết**, không chỉ text trực tiếp.
- **E2E lộ gap Phase 2 thật**: `approve <id>` chỉ "authorize" chứ KHÔNG dispatch — handler là stub từ Phase 2 ("real handlers land when a Lớp B action actually enters a flow"). Phase 5 là flow đầu tiên Lớp B thực sự cần execute. Vá: `_dispatch_approved_action` route action đã duyệt (slack post_message) tới live handler thật. Sau vá: `approve 4 → posted to C0BBZN04XPX ts=…` (post thật). → E2E thật mới lộ; queue-only test không đủ.
- **Single-channel collision**: chỉ có 1 channel test → dùng chung cho internal + stakeholder. Thêm nó vào external set khiến internal post tới đó CŨNG bị Lớp B (đúng logic, sai ý định). Deployment thật phải tách 2 channel.

## Mở / sang sau
- **Hoãn (roadmap P5 phần còn lại)**: service backend + Slack bot UI (cần Slack Bot App OAuth + event server, không dùng được browser-token MCP) + multi-user/multi-project (config + checkpoint hiện single-tenant). Là effort lớn riêng.
- Deploy: tách `SLACK_REPORT_CHANNEL` (internal, auto) khỏi `SLACK_STAKEHOLDER_CHANNEL` (external, Lớp B).
- Roadmap Phase 0–5 core: ✅ HOÀN TẤT.
