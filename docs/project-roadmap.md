# Project Roadmap — my-crew

> Lộ trình + trạng thái (as-built v50). Cập nhật khi mốc đổi. Chi tiết mỗi vòng: `docs/journals/`.
> Cập nhật: 2026-07-16.

## Trạng thái tổng

**Production-usable, single-user autonomy-first. Đã ship tới v50.** ~2345 backend test, ruff/tsc
sạch. Mọi vòng lớn E2E trên browser + LLM + ticker thật (live daemon, kill-9 resume, fan-out parallelism).

**v40–v50 (deep_agent + runtime-tier + governance + onboarding + UI catch-up):** v40–v42 deep_agent hardening ·
v43 deep_team in-sandbox · v44 benchmark-hardening · v45 tier-0 routing (no-shell→create_agent) ·
**v46 audit actor** (attribution end-to-end) · **v47 Docker UX** (health probe, prepull) ·
**v48 MCP pool** (team-step reuse) · **v49 quickstart** (OpenRouter-only first report) ·
**v50 UI catch-up** (surface v43–v46 backend: actor column, tier badge, per-task cost, deep_team toggle).

## Đã hoàn thành (gọn — chi tiết ở journals/plans)

| Mốc | Nội dung |
|---|---|
| **Nền tảng (v1)** | Single-agent PM: 4 báo cáo (daily/weekly/okr/resource) + Action Gateway (Lớp A/B) + đa-audience. |
| **Platform (v2, M1-M2)** | Multi-agent core (registry + worker + isolated store) · LangGraph interrupt/SSE · Web SPA (React) · Postgres+Store opt-in. |
| **Extensibility (M3-M6)** | Skills · cross-agent memory · domain-packs (pm/hr) · MCP suite · company docs. |
| **Trust & ops (v8, v10)** | Trust ladder (auto-approve Lớp B) · multi-project rollup · theme/dual-mode/installer hardening. |
| **Reporting (D4)** | Xuất .xlsx đính email (Lớp B, internal-only). |
| **Agent Office (v12)** | Team-task: coordinator ticker + store + lease · giao việc đội · office room + màn 3D. |
| **Team self-op (v13-v14)** | Soát chéo tự chèn · consult đồng nghiệp · song song cap 2 · full replan · tự cứu bước kẹt · 3D "sống". |
| **PIC & office UX (v15-v17)** | Giao việc @PIC/@all · auto-confirm · màn Văn phòng hợp nhất → workrooms → command-center 3 cột · artifact viewer · coordinator health banner. |
| **Registry user-data (v18)** | registry.yaml thành user-data (hết mất đội) · recovery UI · scheduler seed-at-discovery · 3D theme-aware. |
| **MCP suite + adapter (v11)** | 3 MCP server (Jira/Confluence/Slack) + session-pool cache (2ms warm) + npm publish 4.2.0/1.5.0/1.3.0. |
| **Agent-harness v1 (v19)** | Memory provider seam (static; kioku hoãn v19.5) · workspace protocol v2 (vault/ + skills/ per-agent) · per-agent skill có guard · capability block internal-only. |
| **AgentRuntime + community (v20)** | AgentRuntime seam (Native/ToolCalling/DeepAgent) giữ deliver→gateway · positive read-allowlist + classify shim (E2E LLM thật) · 3 ổ cắm: skill agentskills.io, pack-MCP spawn gate, pack template + PACK-AUTHORING. |
| **Runtime tiers + DeepAgent (v20.5)** | Multi-tier guardrail (native < tool-calling < deep) · DeepAgent Docker sandbox (fail-closed, token-free, teardown sạch) · team-step egress qua gateway. |
| **Capture telemetry + session log (v26)** | Bảng captures riêng · unify cost 3 engine · side-channel collector · telemetry per-step. |
| **Deep-agent harden (v27)** | Sanitize-at-source 5 kênh · network AND-gate fail-closed · container hardening · reaper orphan cleanup. |
| **Runtime consolidation (v28)** | DRY loop core (record_loop_result + invoke_capped) · migrate tools-tier to langchain.agents.create_agent. |
| **Autonomy-first trust model (v30)** | Lớp B split: autonomous (chạy ngay, audit rationale "trust_mode=autonomous", mặc định) vs guarded (queue duyệt, opt-in `trust_mode: guarded`). Chat flatten. Fleet-flip. No daily-cap in autonomous. |
| **Agent-tools capability wave (v31)** | Hậu kiểm fleet-wide (2 surface: web + ops-chat) · 4 native action types (schedule_update, team_task_create/move, gws_write) · wake-gate hồi sinh (perceive-only, no-LLM khi không đổi, CEO alert on fail/stale) · OpenAlex academic search tool. |
| **Staff templates + crew, office-3D refactor, UI/UX audit (v32)** | One-click template create (agent TẮT → token → bật ở trang Đội) + crew bootstrap từ `profiles/templates/crew.yaml` (per-member independent, skip-existing, coordinator auto-wire) · office-3D visual overhaul (flat low-poly solid pastel theme per light/dark, state hue on monitor, desk click→room/page, hover tooltip, panel 38vh) · error boundary + 12s watchdog cho lazy-office chunk · chat /commands listing "Trợ lý làm được gì?" · AgentPage profile-error recovery · office activity filter note. |
| **Connections + output hub + clarify + search (v33)** | Màn Kết nối = UI của .env (catalog presence-only) · hub Kết quả cross-task kanban · clarify buttons (CEO answer mid-execution) · history FTS5 search. |
| **Autonomy core: checkpointer + interrupt + follow-up (v34)** | Checkpointer resume after crash (attempt adopt tiến độ) · interrupt() pause-ask-resume · proactive follow-up sweep (SQL 8h cooldown) · per-criterion review scoring · fan-out parallelization (1 step → N parallel subtasks + gather). Live E2E verified. |
| **Tool-error resilience + memory consolidation (v35)** | `tool_error_guard` bọc mọi read-tool (Jira/Confluence/web) — lỗi thân tool trả "⚠️ tool lỗi" cho LLM thay vì làm nổ cả step · nightly (03:00) memory consolidation rút gọn `MEMORY.md` khi vượt ngưỡng, archive bản gốc trước khi ghi. |
| **Storage hygiene + template hybrid (v36)** | Template skill nạp LIVE lúc chạy (không copy-once) → sửa skill template lan mọi agent cùng vai ngay · template config version-pin: badge "⬆ bản mới vN" ở trang Đội, review dialog áp/giữ theo trường tự-chỉnh, backup `profile.yaml.bak-<ts>` trước khi ghi · GC nền (captures 180d/office_room 90d/clarify 90d đã trả lời/dedup 7d) + daily integrity audit. 2149 BE + 200 FE tests. |
| **UI design-system sync (v37)** | Văn phòng 3 cột canh cùng baseline · phân cấp size rõ ở cột Kết quả · input/button đồng nhất kích cỡ toàn app. Thuần CSS, không đổi hành vi. |
| **Harness wave 1: send_message + skill-curator (v38)** | `send_message` facade (slack/telegram/email) qua Action Gateway — agent chủ động gửi, thừa hưởng Lớp A/B + trust_mode + audit; surface chat-ops (không tool LLM ghi trong loop) · skill-curator: đếm skill được chọn + archive skill agent-own quá hạn (không xoá, không đụng template-role). 2177 BE + 200 FE tests. |
| **Google Workspace context + SMTP + Calendar-create (v39)** | Agent bật `gws_context` đọc Gmail/Calendar/Drive (gws CLI, argv CODE-cố-định, internal-only, flag mặc định TẮT) · SMTP vào Connections UI · Calendar-create WRITE qua Gateway (`("calendar","events","insert")` allowlist, delete/acl = Lớp A). 2207 BE + 200 FE tests, live E2E OAuth thật. |
| **UI catch-up: surface v43–v46 backend (v50)** | Audit actor column trên AuditTable (v46 data lộ UI) · tier badge "🔒 N sandbox" kanban card (v45 count steps_needs_shell) · GET `/api/team-tasks/{id}/cost` + TeamTaskCost component lazy-expand "Chi phí" (v26 telemetry bộ lộ) · create-wizard deep_team toggle (v43 feature YAML-only → UI, guarded passthrough). 2344 BE + 201 FE tests, E2E UAT browser 5/5. |

## Việc nên làm tiếp (từ UAT + nợ kỹ thuật)

Ưu tiên giảm dần. Nguồn: `plans/260711-0711-.../reports/uat-*findings*.md` + HANDOVER §8.

### Agent-harness (chương trình 3 vòng — brainstorm 260711)
- [x] **v19**: memory seam + static + workspace protocol (vault/skills per-agent) + capability block.
- [x] **v20**: AgentRuntime seam (Native/ToolCalling/DeepAgent) + 3 ổ cắm community. Red-team 4
  reviewer (5 Critical) → fix thiết kế giữ moat. DeepAgent experimental (deepagents optional);
  researcher-pack = template skeleton (team-step đã phục vụ researcher).
- [x] **v20.5**: runtime-tiers — team-step egress qua gateway (Phase 0, nối external_write) +
  guardrail phân tầng (runtime_loop_limit per-runtime) + DeepAgent cháy thật (Docker self-hosted
  sandbox, fail-closed allowlist, PII gate) + wizard chọn runtime theo role. Red-team 3 reviewer
  (6 Critical, đọc deepagents wheel) → provider đổi sang Docker (không dịch vụ ngoài). **DeepAgent
  tự chủ trong Docker verify THẬT** (LLM tự gọi docker exec, container token-free, teardown sạch).
- [ ] **v19.5 (kioku adapter)**: cắm my-kioku sau khi giải 7 điều kiện red-team — dist
  (`bun link`+`MY_KIOKU_BIN`, BỎ `bun x`); recall `<query>` (không `--digest`); wrap digest
  `format_internal_content`; env allowlist subprocess; flock per-vault + stagger reflect;
  health probe thật; pin "zero network I/O". Xem `plans/260711-1543-v19-.../plan.md` §"Giữ cho v19.5".
- [ ] **v20**: channel binding account→agent (mỗi agent 1 bot Telegram, OpenClaw-style).
- [ ] **v21**: 2-mode UI (CEO đơn giản / Maintainer config+monitoring).

### Tài liệu
- [x] Dựng bộ doc chuẩn v18 (overview-pdr, system-architecture, deployment-guide, roadmap).
- [x] Archive doc cũ (v1/v2/interview) + gộp UAT.
- [ ] Đồng bộ header `codebase-summary.md` (ghi v13 → v18) + gộp phần lịch sử dài.

### Sản phẩm
- [ ] **Web-search key cảnh báo → hành động**: agent bật web_search thiếu key mới chỉ
  cảnh báo; cân nhắc auto-tắt flag hoặc nhắc rõ ở luồng giao việc.
- [ ] **Queue transparency**: coordinator 1 hành-động/tick (60s) theo thứ tự cũ→mới →
  task mới chờ vài phút khi hàng đợi đông; UI nên hiện "đang xếp sau N việc".
- [ ] **QA reply persist (tùy chọn)**: câu trả lời "hỏi tiến độ" hiện không lưu — thêm
  kind lưu nếu CEO muốn lịch sử hỏi-đáp.
- [ ] **Chi phí classify/QA vào cost-cap**: hiện chỉ log, chưa tính vào trần chi phí việc.

### Kỹ thuật
- [ ] Focus-trap + hiển thị detail lỗi cho artifact viewer (drawer).
- [ ] Dọn artifact hex mồ côi sau demo (task giao thật trong demo).
- [ ] Cân nhắc gộp/chuẩn hóa các module >200 LOC còn lại (theo rule modularization).

## Ngoài phạm vi hiện tại (cần thiết kế lại nếu mở)

- Multi-user / hosted multi-tenant (auth + isolation phải làm lại).
- RBAC, thanh toán, chạy cloud.

## Nguyên tắc khi thêm tính năng

1. Brainstorm → plan → **red-team plan** → cook → review → **E2E thật** → docs/journal.
2. Field mới trên step → hỏi "có va `_verify_plan_hash` không?" (metadata phải NGOÀI hash).
3. Ghi ra ngoài mới → PHẢI qua Action Gateway.
4. Không phá 6 bất biến (xem HANDOVER §5).
