# Project Roadmap — my-project-manager

> Lộ trình + milestone. Status sống, cập nhật khi phase đổi trạng thái.
> Status hiện tại: **Phase 0 — docs khởi tạo (2026-06-21)**.

## Trạng thái tổng

| Phase | Tên | Trạng thái | Mục tiêu chính |
|---|---|---|---|
| 0 | Khởi tạo docs + scaffold | 🟡 In progress | Bộ docs + cấu trúc repo + setup LangGraph chạy được |
| 1 | MVP Reporting + Monitoring | ⬜ Chưa bắt đầu | Đọc Jira/GitHub → report → đăng Slack/Confluence |
| 2 | Guardrail hardening | ⬜ Chưa | Audit/dry-run/kill-switch/idempotency vững trước khi mở write rộng |
| 3 | OKR / objective | ⬜ Chưa | Đặt + track OKR, map xuống Jira epic |
| 4 | Resource + Cost | ⬜ Chưa | Capacity, allocation, budget alert |
| 5 | Stakeholder + scale | ⬜ Chưa | Report theo audience; lên service + Slack UI; multi-user |

## Phase 0 — Khởi tạo (gần xong — chỉ còn E2E thật)

- [x] Bộ docs ban đầu (`docs/*`).
- [x] Scaffold repo theo cây ở `system-architecture.md §8` (+ `adapters/`).
- [x] `pyproject.toml` + cài LangGraph (venv 3.12 qua uv). SDK công cụ là MCP/CLI → Phase 1.
- [x] `config.example.env` + cơ chế load env (`src/config/settings.py`).
- [x] "Hello agent": graph LangGraph tối thiểu (perceive→respond) + checkpointer SQLite, chạy CLI. Vòng đời graph đã chứng minh end-to-end (fake client trong test). Gọi LLM thật cần key.
- [x] Audit log skeleton (JSONL append-only + redaction) + `DRY_RUN` flag.
- [x] **Action Gateway allowlist + Lớp A hard-deny** (PDR §7.9) — đổi từ denylist sau 2 vòng review; chặn cứng mất-data/credential/security. Phủ MCP tool + gh command. 74 UT.
- [x] **Budget tracker** OpenRouter — cộng dồn cost, hard-stop $50/tháng, cảnh báo 80%.
- [x] **E2E thật**: `cli "hello"` gọi OpenRouter thật — OK (2026-06-21). minimax/minimax-m2.7 trả lời + cost thật $0.000429, budget tracker ghi nhận, checkpoint lưu.

**Exit Phase 0**: ✅ HOÀN TẤT. Guardrail (dry-run + audit + allowlist/Lớp A + budget) có sẵn trước mọi write thật; vòng đời graph→OpenRouter→output đã xác nhận với key thật. Sẵn sàng Phase 1.

> Ghi chú (2026-06-21): OpenRouter CÓ trả `cost` field cho minimax/minimax-m2.7 → giải tỏa câu hỏi mở về cost extraction; fallback manual token×price không cần dùng (nhưng vẫn giữ làm dự phòng cho model khác).

## Phase 1 — MVP Reporting + Monitoring

Trọng tâm: ROI rõ, rủi ro thấp. Đọc nhiều, write chỉ là *post report*.

- [ ] `tools/jira_read.py` — pull issues/sprint/status/assignee/due.
- [ ] `tools/github_read.py` — pull PR/commit/review/CI.
- [ ] `agent/` graph: perceive → analyze → compose_report → deliver (xem architecture §3).
- [ ] Phát hiện rủi ro cơ bản: task quá hạn, PR treo, burndown lệch.
- [ ] `actions/action_gateway.py` + `slack_post` + `confluence_write` (qua guardrail).
- [ ] Report template (status daily + sprint weekly).
- [ ] Cron entrypoint: daily digest + weekly report.
- [ ] Test với data thật hoặc mock (xem unresolved PDR §9.1).

**Exit Phase 1**: agent tự sinh + đăng report tiến độ định kỳ lên Slack/Confluence, số liệu sát Jira/GitHub, không cần người viết tay.

## Phase 2 — Guardrail hardening

Trước khi mở autonomous write sang việc nhạy cảm hơn (Phase 3+):

- [ ] Audit log bất biến hoàn chỉnh, query được.
- [ ] Kill switch test thật (tắt write tức thì).
- [ ] Rate limit + idempotency có test case (re-run không tạo trùng).
- [ ] Scoped token review (mỗi công cụ quyền tối thiểu).
- [ ] Danh sách hành động "cần xác nhận dù autonomous" (interrupt node) — chốt với chủ dự án.

## Phase 3–5 — tóm tắt

- **P3 OKR**: agent hỗ trợ đặt OKR, map xuống Jira epic, track tiến độ OKR theo thời gian.
- **P4 Resource+Cost**: capacity/allocation; cost monitor + budget alert.
- **P5 Stakeholder+Scale**: report tách audience (nội bộ vs stakeholder external); lên service backend + Slack bot UI; multi-user/multi-project.

## Nguyên tắc xuyên suốt

- Mỗi phase phải **chạy được + có giá trị thật** trước khi sang phase sau (không big-bang).
- Không mở rộng write authority sang việc nhạy cảm khi guardrail (Phase 2) chưa vững.
- Đo `% cost management cắt được` (PDR §3) ở mỗi phase — đó là North Star.

## Unresolved (roadmap)

1. Có deadline thật cho MVP không? (ảnh hưởng cắt scope Phase 1).
2. Test trên dự án thật nào, hay dựng sandbox Jira/GitHub riêng?
3. Thứ tự P3/P4 có thể đảo nếu cost là đau hơn OKR — chờ chủ dự án xác nhận ưu tiên.
