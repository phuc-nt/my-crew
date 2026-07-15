# v50 — UI catch-up: surface v43-v46 backend trong FE
2026-07-15 · ✅ Done

## Làm gì
Audit FE lộ backend v40-49 tiến nhưng nhiều capability không có UI. Vá 4 gap + 2 inconsistency:
- **P1 actor (v46):** cột "Ai thực hiện" ở AuditTable (rỗng→"—") + tag "[bởi {actor}]" ở CompanyActivity khi actor≠agent_id. Data đã trên wire (`_AUDIT_FIELDS`), FE chỉ drop → thêm type + cột.
- **P2 tier badge (v45):** board card thêm `steps_needs_shell` (đếm bước cần shell) → kanban hiện "🔒 N sandbox". Bước leo deep_agent (Docker) giờ nhìn thấy.
- **P3 per-task cost (v26):** endpoint `GET /api/team-tasks/{id}/cost` bọc `CaptureStore.list_for_task` (allowlist projection + tổng) → component `TeamTaskCost` lazy-expand trên kanban card.
- **P4 deep_team (v43):** toggle trong create-wizard CHỈ hiện khi runtime=deep_agent; `agent_create` passthrough `deep_team`(bool)+`deep_team_max_calls`(int>0). Trước chỉ sửa YAML tay.
- **P5 consistency:** comment dual-mount CoordinatorHealthBanner (Team+office khác route, không đồng thời); AuditRow type drift vá ở P1.

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Xếp ROI: actor trước (rẻ nhất) | data đã trên wire, FE-only | — |
| P2 aggregate count không per-step | KISS — card index chỉ cần "có/mấy bước cần sandbox" | không rõ bước NÀO (đủ cho glance) |
| P3 allowlist `_COST_FIELDS` | mirror fleet_activity — không leak attempt_id/started_at/error | — |
| P4 toggle chỉ deep_agent + BE passthrough guarded bool | deep_team vô nghĩa runtime khác; loader pop nó nên inert nếu lọt | — |
| P4 KHÔNG structured field ở Config.tsx | Config đã raw-YAML edit → thêm = trùng | wizard-only (raw YAML vẫn power-user path) |
| P5 comment thay hoist context | 2 mount khác route không đồng thời — hoist = over-engineer | — |
| deep_team_max_calls check `not isinstance(bool)` | bool là subclass int, True/False lọt thành 1/0 | — |

## Vấp & học được
- **Card refactor rơi CSS (review HIGH):** đổi kanban card từ 1 `<Link>` sang div-wrapper+Link+cost-sibling (để nút cost không nằm trong anchor) → class `.team-kanban-card-link`/`.team-kanban-sandbox` KHÔNG có rule → title render link xanh gạch chân. **jsdom test không bắt CSS** ("test pass" che regression style). Vá: thêm rule + rebuild.
- Kiểm route collision `/team-tasks/board` vs `/{id}/cost` — Starlette phân biệt theo số segment, OK.

## UAT browser thật (2026-07-15)
5/5 pattern PASS trên browser THẬT + data THẬT + kết nối THẬT (OpenRouter/gateway/MCP Slack+Telegram live, fleet 8 agent). P1 verify cả empty ("—") lẫn non-empty (giao 1 team-task thật → 39 audit row `actor='admin'` live). P3 cost endpoint trả breakdown thật ($0.0124/4 step, 2 engine). **Bài học: server đang chạy là code CŨ pre-v50 → phải restart web+coordinator trước UAT** (routes v50 mới xuất hiện). Puppeteer headed+session-reuse treo macOS → headless tự-launch. Chi tiết: `plans/reports/uat-v50-ui-patterns-real-browser-260715-1505-report.md`.

## Mở / sang sau
- P2 chỉ aggregate — nếu cần per-step tier phải có task-detail view.
- P3 cost breakdown trên card; chưa gộp vào Cost.tsx (per-agent). Cân nhắc drill-down sau.
- Tag `[bởi X]` (actor≠owner) chưa thấy live — cần action điều phối/PIC (agent A thay B); logic verify code+unit.
