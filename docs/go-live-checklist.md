# Go-live có kiểm soát — checklist vận hành

> Lập 2026-08-03 (v58 P5) từ kiểm kê fleet THẬT + drill kill-switch thật. Người quyết
> định bật: CEO. Tài liệu này là quy trình, không phải công tắc — không flag nào tự đổi.

## 1. Hiện trạng fleet (kiểm kê 2026-08-03)

| Agent | dry_run | Kênh ghi cấu hình sẵn | Ghi chú |
|---|---|---|---|
| admin, hr, thu-ky | **false (đã live)** | Telegram (bot riêng, allowlist CEO) | Đã chạy thật ổn định; thu-ky thêm gws calendar write |
| truong-phong (coordinator) | true | — (ghi nội bộ store, không gateway) | dry_run chủ yếu ảnh hưởng escalate Telegram |
| noi-dung, nghien-cuu, phan-tich, kiem-dinh, thiet-ke | true | qua env fallback: Jira + Slack + Confluence (token có sẵn trong .env) | Ghi ngoài chỉ khi team-task đụng external_action |
| sales-pm | true | schedule `daily` — sẽ post Slack + Confluence THẬT khi bật | Ứng viên pilot tốt nhất: 1 báo cáo/ngày, dễ soi |
| default | true | — | Giữ nguyên (agent mẫu) |

Env sẵn: `ATLASSIAN_API_TOKEN` ✓, `SLACK_XOXC_TOKEN` ✓, `JIRA_PROJECT_KEY` ✓,
`SLACK_REPORT_CHANNEL` ✓, `CONFLUENCE_SPACE_KEY` ✓, `GITHUB_REPO` ✓ (presence-only,
không ghi giá trị ở đây).

## 2. Lộ trình 2 nấc (per agent, không bật cả fleet một phát)

1. **Nấc guarded**: sửa profile agent —
   `safety: {dry_run: false, trust_mode: guarded}` → restart `com.mpm.service`.
   Mọi Lớp B (post Slack, comment Jira, tạo trang Confluence, gửi mail) **xếp hàng ở
   action rail** (cockpit, cột phải) — CEO duyệt từng cái bằng 1 bấm. Chạy ≥3–5 ngày,
   đọc mỗi hành động trước khi duyệt.
2. **Nấc autonomous**: hành động nào duyệt mãi thấy nhàm (luôn đúng) → đổi
   `trust_mode: autonomous` (chạy thẳng + audit) — có thể giữ guarded riêng cho loại
   nhạy cảm bằng cách cấu hình `auto_approve` grants thay vì flip cả agent.

## 3. Nghi thức soi hằng ngày (khi có agent live mới)

- **Audit**: `uv run my-crew agent audit <id> | tail -30` hoặc UI trang Đội → Audit
  (cột actor v46). Soi: hành động lạ? rationale `trust_mode=autonomous` có hợp lý?
- **Chi phí**: `/api/budget` hoặc trang Đội — cap mỗi agent hiện $50/tháng
  (`budget.monthly_usd`); pilot nên hạ còn $10 để phanh sớm.
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
