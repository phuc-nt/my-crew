# Project Roadmap — my-project-manager

> Lộ trình + milestone. Status sống, cập nhật khi phase đổi trạng thái.
> Status hiện tại: **Phase 4 (Resource + Cost Reporting) HOÀN TẤT (2026-06-22) — Resource+cost read + analyzer + report (CLI + weekly embed) + Slack delivery + cron. Sẵn sàng Phase 5.**

## Trạng thái tổng

| Phase | Tên | Trạng thái | Mục tiêu chính |
|---|---|---|---|
| 0 | Khởi tạo docs + scaffold | ✅ Done | Bộ docs + cấu trúc repo + setup LangGraph chạy được |
| 1 | MVP Reporting + Monitoring | ✅ Done | Đọc Jira/GitHub → report (daily/weekly) → đăng Slack/Confluence + cron |
| 2 | Guardrail hardening | ✅ Done | Dedup bền + audit query + Lớp B interrupt (queue+approve) |
| 3 | OKR / objective | ✅ Done | Đặt + track OKR, map xuống Jira epic |
| 4 | Resource + Cost | ✅ Done | Capacity (load tương đối), cost tracking + budget band |
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

**Slice 1 — Jira+GitHub → Slack (✅ DONE, E2E thật 2026-06-21):**
- [x] `tools/jira_read.py` — pull issues (via MCP spawn).
- [x] `tools/github_read.py` — pull PR/CI (via `gh` CLI).
- [x] `agent/report_graph.py` graph: perceive → analyze → compose → deliver (injectable deps).
- [x] Risk detect: overdue/blocker/stale_pr/ci_failure (risk_analyzer.py pure).
- [x] `actions/slack_write.py` + action_gateway write guardrail. E2E: post Slack thật.

**Slice 2 — Confluence detail + Slack short+link (✅ DONE, E2E thật 2026-06-22):**
- [x] `actions/confluence_write.py` — createPage qua gateway, parse page id/URL.
- [x] Report detail (XHTML storage) lên Confluence (page/ngày, space MPM) + short+link lên Slack.
- [x] Slack mrkdwn sạch; state chỉ primitive (checkpointer-safe). 130 UT.

**Slice 3 — Daily/Weekly + Cron (✅ DONE, E2E thật 2026-06-22):**
- [x] `cli report --daily|--weekly`: 2 loại report (daily standup ngắn / weekly sprint review).
- [x] Weekly kéo Jira sprint data (get_active_sprint + get_sprint_issues).
- [x] `cron.py` thật + launchd (`deploy/launchd/`: daily 9:00, weekly thứ 6 17:00). 136 UT.

**Còn lại (Phase 2 / sau):**
- [ ] Burndown / velocity metrics nâng cao.
- [ ] (Phase 2) Lớp B interrupt cho hành động nhạy cảm; dedup bền qua restart.

**Exit Phase 1**: ✅ ĐẠT. Agent tự sinh + đăng report tiến độ (Slack + Confluence), daily/weekly có sprint data, chạy tự động qua cron. Số liệu sát Jira/GitHub, không cần người viết tay.

## Phase 2 — Guardrail hardening (✅ DONE 2026-06-22, 156 UT, reviewed)

- [x] Audit log query được (`audit_log.query` + `cli audit --tool/--verdict/--since/--limit`).
- [x] Kill switch + rate limit + idempotency có test (Phase 0 + bổ sung).
- [x] **Dedup bền qua restart** (`dedup_store.py` SQLite, reserve-before-execute).
- [x] **Lớp B interrupt** (`hard_block.needs_interrupt` + `approval_store.py` + gateway queue + `cli approvals/approve/reject`). Danh sách: merge/close PR, close/transition/assign issue, post Slack channel external. Order: Lớp A > Lớp B > allowlist.
- [ ] Scoped token review (để sau — token ở MCP server, agent không cầm trực tiếp).

> Review (DONE_WITH_CONCERNS → fixed): skip_interrupt private; external-channel Slack = Lớp B; dedup atomic reserve; approval store redact secret; reject audited; double-approve CAS. Red line (Lớp A) verified không bypass được.

## Phase 3 — OKR Tracking (✅ DONE 2026-06-22, 202 UT, ruff clean, code-reviewed)

- [x] `confluence_read.py` — `get_page_content` (getPageContent tool) + parsers: `parse_okr_table` (html.parser, nested-table-safe), `parse_epic_keys` (validates PROJECT-123, blocks JQL inject), `parse_weight`.
- [x] `okr_read.py` — epic progress from Jira children: `compute_epic_progress` (pure), `get_epic_progress` (JQL `parent = <epic>`, fallback `"Epic Link"`), `get_epic_progress_map` (memoized).
- [x] `okr_analyzer.py` — pure `build_objectives` + `OkrRollup` (weighted rollup, any-blank⇒equal weighting, child-count multi-epic, at-risk, problems).
- [x] `okr_report_prompt.py` — deterministic XHTML table + Slack short + overall progress pct + LLM-only prose (no number injection).
- [x] `okr_report_graph.py` — standalone `build_okr_graph` + `OkrReportDeps`.
- [x] `okr_weekly_section.py` — fault-isolated `weekly_okr_section` / `weekly_okr_slack_line`.
- [x] Models: EpicProgress, KeyResult, Objective, OkrProblem dataclasses (`src/tools/models.py`).
- [x] Config: okr_confluence_page_id, okr_behind_threshold (`src/config/reporting_config.py`).
- [x] CLI: `cli report --okr` flag; precedence: okr>weekly>daily (`src/entrypoints/cli.py`).
- [x] Weekly embed: OKR section appended to weekly report (native rollup + Slack line).
- [x] **E2E verified**: 3 Jira epics + OKR Confluence page; real write: page 557057 "OKR Status 2026-06-22" + Slack post, dedup confirmed re-run.

**Exit Phase 3**: ✅ ĐẠT. Agent reads external OKR table (Confluence), maps to Jira epics, rolls up weighted progress, delivers via `cli report --okr` + weekly embed + Slack with NO new MCP write authority.

> **Bug found + fixed (integration verification)**: Jira MCP `enhancedSearchIssues` omitted `duedate` field → overdue_task risk never fired (Phase-1 regression). Fixed in MCP server repo (commit 41a6a30): added `duedate` to defaultFields. After fix, daily report flags 6 overdue tasks. Reinforce: **verify integration early**.

## Phase 4 — Resource + Cost Reporting (✅ DONE 2026-06-22, 236 UT, ruff clean, code-reviewed)

- [x] `resource_analyzer.py` — pure `build_resource_report` (relative-to-mean overload, self-adjusting) + `build_cost_summary` (BudgetTracker status bands: ok/warn/over, no raise).
- [x] `resource_report_prompt.py` — deterministic XHTML table (`render_resource_xhtml`, assignee names escaped) + Slack short (`build_resource_slack_short`, names sanitized via `_slack_safe`) + LLM prose (narrative, no number injection).
- [x] `resource_report_graph.py` — standalone `build_resource_graph` + `ResourceReportDeps`.
- [x] `resource_weekly_section.py` — fault-isolated `weekly_resource_section` + `weekly_resource_slack_line` (alongside OKR section).
- [x] Models: `AssigneeLoad` (load = open_issues + overdue + blocker per assignee), `ResourceReport`, `CostSummary` dataclasses.
- [x] Config: `resource_overload_ratio` (default 1.5, self-adjusting), `labor_cost_per_issue` (optional labor estimate).
- [x] CLI: `cli report --resource` flag; precedence: resource>okr>weekly>daily.
- [x] Cron: `--resource` Monday 09:00 (`deploy/launchd/com.mpm.report.resource.plist`).
- [x] **E2E verified**: seeded dataset (SCRUM-19/20/21 → Phúc Nguyễn 3 open/3 overdue/1 blocker). Real write: Confluence page 589825 "Resource & Cost Status 2026-06-22" + Slack post.

> **Security fix (C1 found + fixed in code review)**: assignee names reached Slack mrkdwn unescaped via fallback path. XHTML path already escaped. Added `_slack_safe` sanitizer to block Slack mrkdwn/mention/link injection + regression test. Reinforce: **multi-path sanitization**.

**Exit Phase 4**: ✅ ĐẠT. Agent reads Jira workload (open/overdue/blocker per assignee) + LLM budget (BudgetTracker), computes relative load, delivers via `cli report --resource` + weekly embed + Slack with NO new write authority. Cron automated (Monday 09:00).

## Phase 4–5 — tóm tắt

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
