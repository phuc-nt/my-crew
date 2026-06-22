# Codebase Summary — my-project-manager

> Bản đồ codebase, cập nhật khi code hình thành. Đọc để biết "cái gì ở đâu" nhanh.
> Status: **2026-06-22 — Phase 0 + Phase 1 + Phase 3 (OKR) + Phase 4 (Resource+Cost) HOÀN TẤT (236 UT, ruff clean, E2E thật).** `cli report --daily|--weekly|--okr|--resource` → đọc Jira (MCP) + GitHub (gh) + Confluence OKR → risk_analyzer + okr_analyzer + resource_analyzer → LLM compose → **Confluence detail page + Slack short+link + weekly OKR+resource section** qua Action Gateway. Cron qua launchd (`deploy/launchd/`).

## Trạng thái hiện tại

- Code: **có** — `src/` đã scaffold theo `system-architecture.md §8`. Python venv 3.12 (uv).
- Hello-agent: `python -m src.entrypoints.cli "hello"` chạy graph (perceive→respond) + checkpointer SQLite. Cần `OPENROUTER_API_KEY` để gọi LLM thật.
- Guardrail core: Action Gateway (allowlist + Lớp A hard-deny), audit JSONL append-only + redaction secret, budget tracker $50/tháng, DRY_RUN + kill-switch.
- Test: `uv run pytest` (74 UT, không cần network). `uv run ruff check src tests`.
- Chưa có: tool READ thật (jira/github/...), MCP/CLI adapter, write handler thật — Phase 1.

## Cây thư mục dự kiến (sẽ điền khi build)

```
src/
├── agent/        # LangGraph graph + nodes + state — LÕI
├── tools/        # *_read.py: jira/github/slack/confluence (READ)
├── actions/      # action_gateway.py + *_write.py (WRITE, qua guardrail)
├── llm/          # provider config + prompts
├── config/       # env loading, settings
├── audit/        # audit log (append-only)
└── entrypoints/  # cli.py, cron.py (sau: slack.py, server.py)
```

## Bản đồ "tìm gì ở đâu" (điền dần)

| Cần tìm | Ở |
|---|---|
| Flow agent (graph) | `src/agent/report_graph.py` (perceive→analyze→compose→deliver, `report_kind` daily/weekly, deliver 2 bước Confluence+Slack, injectable ReportDeps); hello-graph cũ ở `src/agent/graph.py`. State: `src/agent/state.py` (chỉ primitive), checkpoint: `src/agent/checkpoint.py` |
| Cách đọc Jira | `src/tools/jira_read.py` (get_open_issues, parse_issue; + sprint: get_active_sprint/get_sprint_issues/parse_sprint); adapter MCP ở `src/adapters/mcp_adapter.py` (langchain-mcp-adapters 0.3.0, spawn stdio; `_coerce_result` bóc content-block) |
| Cách đọc GitHub | `src/tools/github_read.py` (get_open_prs, get_recent_ci, staleness); adapter CLI `src/adapters/cli_adapter.py` (run_gh subprocess + JSON parse) |
| Models | `src/tools/models.py` (Issue, PullRequest, CiRun, Risk, Sprint) |
| Risk phát hiện | `src/agent/risk_analyzer.py` (pure: overdue/blocker/stale_pr/ci_failure) |
| Config reporting | `src/config/reporting_config.py` (McpServerSpec jira/slack/confluence, project/repo/channel/space + thresholds) |
| Cách agent ghi/post | `src/actions/action_gateway.py` (MỌI mutation qua đây; dedup_hint per kind+ngày) |
| Post Slack | `src/actions/slack_write.py` (deliver_report + build_slack_short link) |
| Tạo page Confluence | `src/actions/confluence_write.py` (create_report_page via gateway, parse page id/URL từ text-block) |
| Guardrail allow/deny | `src/actions/hard_block.py` (allowlist + Lớp A hard-deny + Lớp B `needs_interrupt`) |
| Lớp B duyệt người | `src/actions/approval_store.py` (queue SQLite) + gateway `approve/reject` + `cli approvals/approve/reject` |
| Dedup bền (chống post trùng) | `src/actions/dedup_store.py` (SQLite, reserve-before-execute) |
| Xem audit | `cli audit [--tool/--verdict/--since/--limit]` (`audit_log.query`) |
| Phát hiện/redact secret | `src/actions/secret_patterns.py` (shared: gateway + audit) |
| Report prompt | `src/llm/report_prompt.py` (build_detail_messages daily/weekly XHTML, build_slack_short mrkdwn) |
| OKR Confluence read | `src/tools/confluence_read.py` (get_page_content, parse_okr_table, parse_epic_keys, parse_weight) |
| OKR epic progress | `src/tools/okr_read.py` (compute_epic_progress, get_epic_progress, get_epic_progress_map) |
| OKR analyzer | `src/agent/okr_analyzer.py` (build_objectives, OkrRollup with weighted rollup + at-risk detection) |
| OKR report prompt | `src/llm/okr_report_prompt.py` (render_okr_table_xhtml, build_okr_slack_short, build_okr_narrative_messages) |
| OKR standalone report | `src/agent/okr_report_graph.py` (build_okr_graph, OkrReportDeps) |
| OKR weekly section | `src/agent/okr_weekly_section.py` (weekly_okr_section, weekly_okr_slack_line, fault-isolated) |
| Resource analyzer | `src/agent/resource_analyzer.py` (build_resource_report, build_cost_summary, relative-to-mean overload) |
| Resource report prompt | `src/llm/resource_report_prompt.py` (render_resource_xhtml, build_resource_slack_short, build_resource_narrative_messages, _slack_safe sanitizer) |
| Resource standalone report | `src/agent/resource_report_graph.py` (build_resource_graph, ResourceReportDeps) |
| Resource weekly section | `src/agent/resource_weekly_section.py` (weekly_resource_section, weekly_resource_slack_line, fault-isolated) |
| Budget cap LLM | `src/llm/budget_tracker.py` ($50/tháng, hard-stop) |
| Gọi LLM (OpenRouter) | `src/llm/client.py` + `cost.py` |
| Config/env | `src/config/settings.py` |
| Audit log | `src/audit/audit_log.py` (JSONL append-only) |
| Chạy thế nào | `src/entrypoints/cli.py` (`report --daily\|--weekly\|--okr\|--resource`), `cron.py` (launchd) + `deployment-guide.md §5` |
| Cron / lịch chạy | `src/entrypoints/cron.py` + `deploy/launchd/` (3 plist: daily, weekly, resource + run-report.sh) |

## Mô hình guardrail (CHỐT 2026-06-21, sau 2 vòng review)

**Allowlist + Lớp A hard-deny (defense-in-depth)**. `hard_block.classify(action)`:
1. **Lớp A hard-deny TRƯỚC** — data-loss / credential / security bị chặn cứng dù có nằm trong allowlist. Action shape: MCP `{type,server,tool,args}` hoặc gh `{type,argv}`.
2. **Default-DENY allowlist** — chỉ (server,tool) / gh-subcommand được liệt kê mới qua. Còn lại deny.

Lý do đổi từ denylist: denylist cho qua mọi thứ chưa liệt kê → không an toàn cho red line. Secret detection dùng chung `secret_patterns.py` để gateway-chặn = audit-redact (không lệch).

## Ghi chú tích hợp (Integration Reality)

- **Jira MCP `enhancedSearchIssues` omitted `duedate` field** (Phase-3 E2E discovered): caused `overdue_task` risk to never fire during Phase 1. Fixed in MCP server repo (commit 41a6a30): added `duedate` to defaultFields + mapper. After fix, daily report correctly flags overdue tasks. **Lesson**: verify integration early, don't assume tool output shape matches SDK docs.

## Quy ước đọc

- Bắt đầu mỗi session: `project-overview-pdr.md` → file này → file phase đang làm.
- Mọi mutation phải truy ngược về `action_gateway.py`. Nếu thấy write trực tiếp ngoài đó → bug.

## Cập nhật file này khi nào

- Sau mỗi phase / module mới: thêm vào bản đồ + mô tả 1 dòng.
- Đây là tài liệu sống — agent build CÓ TRÁCH NHIỆM cập nhật.

## Reference & Docs (đọc trước khi viết code — KHÔNG copy thẳng)

### Source tham khảo trên máy: DeerFlow 2.0

`~/workspace/deer-flow` — harness production **xây trên LangGraph**, đọc để học pattern, KHÔNG copy code (kiến trúc nặng hơn nhiều so với MVP này).

- **Phân tích kiến trúc đã có sẵn**: `docs/reference-deerflow-2-architecture.md` (trong repo này) — đọc cái này TRƯỚC khi mò repo gốc, đỡ tốn token.
- Path subsystem cụ thể trong `deer-flow/backend/packages/harness/deerflow/` (đã verify tồn tại 2026-06-21):

| Cần học pattern | Path trong deer-flow |
|---|---|
| Agent loop / graph lõi | `deerflow/agents/lead_agent/` |
| Sub-agent spawn (fan-out/gather) | `deerflow/subagents/` |
| Memory (LLM extract + persist) | `deerflow/agents/memory/` |
| Middleware chain (hooks before/after) | `deerflow/agents/middlewares/` |
| Sandbox (local + Docker) | `deerflow/sandbox/` |
| Skill loader (SKILL.md) | `deerflow/skills/` |
| Model factory (provider-agnostic) | `deerflow/models/` |
| Config (YAML + env) | `deerflow/config/` |
| Checkpointer / persistence | `deerflow/persistence/` |

> Lưu ý đối chiếu: DeerFlow dùng middleware-heavy + checkpointer Postgres + sandbox Docker. MVP này LOCAL-first, SQLite, KHÔNG cần sandbox/middleware phức tạp. Học *cách họ tách lớp*, không bê nguyên độ phức tạp.

### Docs chính thức (training data CÓ THỂ cũ — đọc docs thật trước khi code)

| Lib | Docs |
|---|---|
| LangGraph (Python) | https://langchain-ai.github.io/langgraph/ |
| LangGraph concepts (graph/state/checkpointer) | https://langchain-ai.github.io/langgraph/concepts/ |
| OpenRouter API (OpenAI-compatible) | https://openrouter.ai/docs |
| atlassian-python-api (Jira + Confluence) | https://atlassian-python-api.readthedocs.io/ |
| PyGithub | https://pygithub.readthedocs.io/ |
| slack-sdk (Python) | https://slack.dev/python-slack-sdk/ |
| LangSmith / Langfuse (observability, tùy chọn) | https://docs.smith.langchain.com/ · https://langfuse.com/docs |

> ⚠️ API LangGraph + SDK đổi thường xuyên. ĐỌC docs thật trước khi viết, đừng dựa trí nhớ.
