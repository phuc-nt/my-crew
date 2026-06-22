# Phase 4 — Resource + Cost Reporting

2026-06-22 · ✅ Done (236 UT, reviewed, E2E thật + write thật)

## Làm gì
- **Workload từ Jira (không story point)**: `resource_analyzer.build_resource_report` gom open issue theo assignee → đếm open/overdue/blocker mỗi người. **Quá tải = TƯƠNG ĐỐI** so với trung bình team (`open_count > team_mean × ratio`, default 1.5) → tự điều chỉnh theo team size. Unassigned đếm riêng, không thành 1 "người".
- **Cost 2 phần**: (a) LLM budget THẬT — đọc `BudgetTracker` san có (spent/cap/% + status ok/warn/over, mirror `check_allowed` nhưng không raise); (b) labor ƯỚC LƯỢNG = open_issue × `LABOR_COST_PER_ISSUE` (config; =0 ⇒ ẩn dòng labor). `build_cost_summary` nhận scalar → pure, không đụng/nhân bản budget logic.
- **2 đường giao** (giống P3): `cli report --resource` (Confluence "Resource & Cost Status" + Slack short qua gateway, dedup `resource-<date>`) VÀ section nhúng vào **weekly** (sau section OKR, fault-isolated). Số render deterministic; LLM chỉ viết 1 đoạn prose.
- **Cron `--resource`**: refactor `cron.py` dispatch theo kind (resource/okr/weekly/daily) + plist thứ 2 9:00.
- **KHÔNG mở write authority**: tái dùng createPage + Slack post (đã allowlist Auto). Không đổi gateway/allowlist/Lớp A-B.

## Quyết định & vì sao
| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| Capacity = issue count (không story point) | Jira MCP đang chạy không expose story point | Thô hơn velocity thật, nhưng đủ tín hiệu "ai gánh nhiều" |
| Overload tương đối theo mean | Tự điều chỉnh theo team, không phải chỉnh ngưỡng cứng | Team 1 người không bao giờ tự cờ (đúng ý) |
| Cost analyzer nhận scalar | Giữ analyzer pure; budget đọc ở call site | 1 lớp gián tiếp nhỏ |
| Labor là ước lượng có nhãn | Không có roster/rate thật | Chỉ tham khảo, không phải số thật |

## Vấp & học được
- **Code review bắt C1 thật** (HIGH→fixed): tên assignee (Jira display name — người dùng tự đặt) chảy vào **Slack mrkdwn KHÔNG escape**. XHTML path đã escape rồi, nhưng Slack path interpolate thẳng `overloaded` names vào `*Quá tải: ...*` → 1 tên như `<!channel>` / `<https://x|y>` / `*foo*` có thể inject mention/link hoặc vỡ format ở channel stakeholder. Đây là bản Slack của lỗi XHTML ở P3. Vá: `_slack_safe()` trung hòa control char (`* _ < > @ ...`) + test injection. Bài học: escape phải phủ **mọi sink** (XHTML *và* Slack), không chỉ cái nghĩ tới đầu tiên.
- **Data thật lộ giới hạn test**: 18 issue seed đều unassigned + Jira chỉ có 1 user thật → không demo được multi-person overload qua data thật (logic đã có UT với fixture 3 người). Gán SCRUM-19/20/21 cho user thật → E2E hiện 1 load row đúng (3 open/3 overdue/1 blocker). Không tạo user giả được (mời người = Lớp A security, không làm).

## Mở / sang sau
- **M1 (tech-debt, chấp nhận)**: weekly gọi `build_resource_rollup` 2 lần/run (compose + deliver) → 2× Jira fetch. Khớp precedent OKR; dedupe qua closure-box để sau nếu cần (YAGNI giờ).
- Multi-person overload chưa E2E (Jira 1 user) — đã phủ UT.
- Test data giữ (xem memory `seeded-test-dataset`). OKR page 98466, resource page 589825.
- Sang Phase 5 (Stakeholder + scale: audience-split report, service backend + Slack UI, multi-user).
