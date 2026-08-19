# Go-live có kiểm soát — checklist vận hành

> Lập 2026-08-03 (v58 P5) từ kiểm kê fleet THẬT + drill kill-switch thật. Soát lại
> 2026-08-19 (v88, web 5-hub). Người quyết định bật: CEO. Tài liệu này là quy trình,
> không phải công tắc — không flag nào tự đổi.

## 1. Hiện trạng fleet (kiểm kê lại 2026-08-16)

| Agent | dry_run | Kênh ghi cấu hình sẵn | Ghi chú |
|---|---|---|---|
| admin, hr, secretary | **false (đã live)** | Telegram (bot riêng, allowlist CEO) | Đã chạy thật ổn định; secretary thêm gws calendar write |
| pong | **false (đã live)** | Telegram (bot riêng, DM CEO) | Trợ lý cá nhân (v70–71): briefing sáng + review Chủ nhật |
| coordinator (coordinator) | **false (v66)** | — (ghi nội bộ store, không gateway) | Escalate Telegram chạy thật |
| content, researcher, analyst, qa, designer | **false (v66)** | qua env fallback: Jira + Slack + Confluence (token có sẵn trong .env) | Đội làm việc thật; ghi ngoài chỉ khi team-task đụng external_action |
| sales-pm | true | schedule `daily` — sẽ post Slack + Confluence THẬT khi bật | Ứng viên pilot tốt nhất: 1 báo cáo/ngày, dễ soi |
| default | true | — | Giữ nguyên (agent mẫu) |

Env sẵn: `ATLASSIAN_API_TOKEN` ✓, `SLACK_XOXC_TOKEN` ✓, `JIRA_PROJECT_KEY` ✓,
`SLACK_REPORT_CHANNEL` ✓, `CONFLUENCE_SPACE_KEY` ✓, `GITHUB_REPO` ✓ (presence-only,
không ghi giá trị ở đây).

## 2. Lộ trình 2 nấc (per agent, không bật cả fleet một phát)

1. **Nấc guarded**: sửa profile agent —
   `safety: {dry_run: false, trust_mode: guarded}` → restart `com.mpm.service`.
   Mọi Lớp B (post Slack, comment Jira, tạo trang Confluence, gửi mail) **xếp hàng
   chờ duyệt** — hàng này hiện ở hub **Công việc** (số chờ duyệt hiện luôn trên nút
   Công việc ở thanh điều hướng) và ở khung chờ duyệt trong hub **Trò chuyện**; CEO
   duyệt từng cái bằng 1 bấm. Chạy ≥3–5 ngày, đọc mỗi hành động trước khi duyệt.
2. **Nấc autonomous**: hành động nào duyệt mãi thấy nhàm (luôn đúng) → đổi
   `trust_mode: autonomous` (chạy thẳng + audit) — có thể giữ guarded riêng cho loại
   nhạy cảm bằng cách cấu hình `auto_approve` grants thay vì flip cả agent.

## 3. Nghi thức soi hằng ngày (khi có agent live mới)

- **Audit**: `uv run my-crew agent audit <id> | tail -30` hoặc UI **Hệ thống → Nhật
  ký kiểm tra** (cột actor v46). Soi: hành động lạ? rationale `trust_mode=autonomous`
  có hợp lý?
- **Chi phí**: `/api/budget`, cột chi phí trong bảng nhân sự hub **Đội ngũ**, hoặc
  **Hệ thống → Số liệu** — cap mỗi agent hiện $50/tháng
  (`budget.monthly_usd`); pilot nên hạ còn $10 để phanh sớm. Trần per-task
  `team_task_cap_usd` trong `company.yaml` (mặc định $2) — từ 0.10.0 chạm trần là
  halt cả bước ĐANG chạy, không chỉ chặn bước mới; ngân sách soát/sửa per-task
  (2× số bước nội dung, sàn 5) cạn là task stall + escalate thay vì đốt tiếp.
- **Alert tự động đã có sẵn**: ops-alerts DM CEO khi agent chết ngầm/fail; budget cảnh
  báo ở 80%; follow-up sweep nhắc việc kẹt. Không cần dựng thêm gì.

## 4. Kill-switch & rollback (đã DRILL THẬT 2026-08-03)

- **Chặn toàn fleet**: thêm `AGENT_WRITE_DISABLED=true` vào `.env` + restart service
  → mọi mutation bị từ chối TRƯỚC khi tốn LLM.
  - Bằng chứng drill: run thật trả `error: AGENT_WRITE_DISABLED is on; all mutations
    are refused.` với `cost=None`.
  - **Bug drill bắt được (đã vá cùng ngày)**: trước đó mọi profile ghi
    `write_disabled: false` tường minh nên luật "profile wins" làm env bất lực —
    nay env `true` thắng tuyệt đối (test pin trong `test_profile_loader.py`).
- **Chặn một agent**: `safety: {write_disabled: true}` trong profile + restart.
- **Rollback một nấc**: `trust_mode` về `guarded` (hành động quay lại hàng duyệt) hoặc
  `dry_run: true` (về diễn tập). Đổi profile nào cũng cần
  `launchctl kickstart -k gui/$(id -u)/com.mpm.service`.
- Hàng đang chờ duyệt không mất khi rollback — approvals store bền qua restart.

## 5. Việc CEO quyết (điền khi quyết)

- [ ] Pilot agent nào, từ ngày nào? (đề xuất: `sales-pm`, nấc guarded)
- [ ] Hạ budget cap pilot xuống $10/tháng?
- [ ] Ngày review nâng nấc autonomous (sau ≥3–5 ngày guarded)?
