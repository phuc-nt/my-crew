# System Architecture — my-project-manager

> Kiến trúc kỹ thuật. Status: **Initial draft 2026-06-21**, sẽ cập nhật khi codebase hình thành.
> Đọc cùng `project-overview-pdr.md` (vì sao) + `code-standards.md` (viết thế nào).

## 1. Nguyên tắc kiến trúc

1. **LangGraph là lõi orchestration** — control flow tường minh (graph: node/edge/state), KHÔNG agentic-loop ẩn. Mỗi bước agent quyết định phải nhìn thấy được trong graph.
2. **Tool = lớp tách biệt** — mỗi công cụ ngoài (Slack/Jira/Confluence/GitHub) là 1 module tool độc lập, có interface thống nhất, dễ mock/test.
3. **MVP local-first** — chạy CLI được ngay, nhưng tách biệt rõ "lõi agent" và "cách kích hoạt" để lên service + Slack UI sau mà không viết lại lõi.
4. **Mọi write đi qua 1 cổng** — không tool nào tự ý ghi; mọi mutation qua 1 lớp `action gateway` áp guardrail (§5). Đây là điều kiện sống còn của "full autonomous write".
5. **State persistable** — dùng checkpointer của LangGraph (SQLite local → Postgres khi scale). Resume được, audit được.

## 2. Sơ đồ tầng (high-level)

```
┌─────────────────────────────────────────────────────────┐
│  Entry points (cách kích hoạt agent)                     │
│  - CLI (MVP)          - Cron (report định kỳ)            │
│  - [sau] Slack bot    - [sau] HTTP/service               │
└───────────────────────────┬─────────────────────────────┘
                            │ (1 lối vào lõi, đa entry)
┌───────────────────────────▼─────────────────────────────┐
│  LangGraph Agent Core                                    │
│  - Graph: nodes (perceive → reason → plan → act → report)│
│  - State (typed), Checkpointer (SQLite→Postgres)         │
│  - LLM calls (provider-agnostic)                         │
└──────┬──────────────────────────────────┬───────────────┘
        │ đọc                              │ ghi (mutation)
┌──────▼───────────────┐         ┌────────▼──────────────────┐
│  Tool layer (READ)   │         │  Action Gateway (WRITE)    │
│  - jira_read         │         │  - guardrail: audit/dry-run│
│  - github_read       │         │    /kill-switch/rate-limit │
│  - slack_read        │         │    /idempotency            │
│  - confluence_read   │         │  → jira_write / slack_post │
└──────┬───────────────┘         │    / confluence_write / gh │
        │                         └────────┬──────────────────┘
┌──────▼─────────────────────────────────▼──────────────────┐
│  External services: Slack · Jira · Confluence · GitHub     │
└────────────────────────────────────────────────────────────┘
        ▲
        │
┌───────┴───────────────┐
│  Cross-cutting         │
│  - Config (.env)       │
│  - Audit log (immutable)│
│  - Secrets (scoped tok)│
│  - Observability/log   │
└────────────────────────┘
```

## 3. Agent core (LangGraph) — mô hình graph đề xuất

MVP reporting flow, dạng graph tường minh (đề xuất, agent build có thể tinh chỉnh):

```
START
  → perceive    : gọi tool READ, gom trạng thái Jira+GitHub (+Slack/Confluence nếu cần)
  → analyze     : LLM suy luận tiến độ, phát hiện rủi ro (quá hạn/PR treo/burndown lệch)
  → decide      : cần hành động gì? (chỉ report / report + cảnh báo / tạo ticket…)
       ├─ (chỉ report) → compose_report
       └─ (cần write)  → plan_actions → [Action Gateway] → compose_report
  → compose_report : LLM viết report theo template
  → deliver     : post Slack + update Confluence (qua Action Gateway)
  → END
```

- **State** (typed, vd TypedDict/pydantic): `raw_signals`, `analysis`, `risks`, `planned_actions`, `report_draft`, `delivered`, `audit_refs`.
- **Checkpointer**: SQLite file local (MVP). Cho resume + time-travel debug + nền audit.
- **Human-in-the-loop**: dù chốt "autonomous", graph PHẢI có node interrupt tùy chọn cho các hành động §5.2 (nhạy cảm) — bật/tắt qua config.

## 4. Tool layer (READ) — interface thống nhất qua 2 adapter

**CHỐT 2026-06-21**: Agent KHÔNG gọi SDK Python trực tiếp tới Jira/Confluence/Slack. Mọi giao tiếp công cụ đi qua **2 kiểu integration**, gom về 2 adapter:

- **MCP adapter** — Jira, Confluence, Slack qua các **MCP server có sẵn** (Node/TS, stdio-default). Agent là **MCP client** (dùng `langchain-mcp-adapters` để expose tool MCP cho LangGraph). Server **chạy sẵn, agent connect** (không agent-spawn). 3 server tại:
  - `~/workspace/jira-cloud-mcp-server` (`mcp-jira-cloud-server` v4.x, 46 tool, modular core/agile/dashboard/search — load chọn lọc được).
  - `~/workspace/confluence-cloud-mcp-server` (v1.x, 11 tool: create/get/update/delete page, getSpaces, searchPages CQL, version history, comments).
  - `~/workspace/slack-browser-mcp-server` (v1.x, 12 tool: post/update/delete message, Block Kit, search, channel/user list — **browser-token auth**).
- **CLI adapter** — GitHub qua **`gh` CLI** (subprocess, bounded). Tương lai: **GWS (Google Workspace) qua CLI**. Cùng adapter pattern.

Mỗi tool vẫn là 1 module `src/tools/<tool>_read.py` expose hàm thuần trả **dữ liệu chuẩn hóa** (không đẩy raw MCP/CLI output cho LLM). Bên trong, module gọi adapter tương ứng.

| Công cụ | Integration | Đọc gì (MVP) |
|---|---|---|
| Jira | MCP (`jira-cloud-mcp-server`) | issues, sprint, status, assignee, due date |
| GitHub | CLI (`gh`) | PR (open/stale), commit, review, CI status |
| Slack | MCP (`slack-browser-mcp-server`) | (MVP: chủ yếu post; read channel nếu cần context) |
| Confluence | MCP (`confluence-cloud-mcp-server`) | (MVP: chủ yếu write report; read template/space nếu có) |
| GWS (sau) | CLI | (phase sau) |

> ⚠️ 3 MCP server là **stdio-default**. "Chạy sẵn + agent connect" cần cầu transport (HTTP/SSE wrapper) hoặc session-manager giữ stdio bền — quyết chi tiết khi build tool layer Phase 1. Cần Node trên máy + `dist/` đã build.

Mỗi adapter/module: retry/timeout bounded, trả lỗi tường minh (không nuốt), dễ thay bằng mock khi test.

## 5. Action Gateway (WRITE) — trái tim guardrail

Mọi mutation BẮT BUỘC qua đây. Không module nào gọi API write trực tiếp.

### 5.1 Mỗi write request đi qua chuỗi:
```
request → [kill-switch check] → [dry-run?] → [rate-limit] → [idempotency dedup]
        → [scoped-token exec] → [audit log ghi kết quả] → return
```

### 5.2 Phân loại hành động (CHỐT — xem PDR §7.9):

> Gateway phân loại theo **MCP tool name + args** (vd Confluence `deletePage`, Jira delete-issue, Slack post tới channel lạ) và **`gh` command line** (vd `gh ... --force`, delete repo/branch). Hard-block match trên cả 2 kiểu integration, KHÔNG chỉ SDK Python.

- **🚫 Lớp A — CẤM cứng (hard-block ở Gateway, KHÔNG để LLM quyết)**: thao tác mất data vĩnh viễn (`gh` force-push, xóa commit/branch/issue, Confluence `deletePage` / ghi đè không version, xóa backup/file), mọi thao tác credential (gửi/echo secret ra ngoài — nhất là **Slack browser-token** rộng quyền), mọi thao tác gây security incident (public hóa private, cấp quyền, mời người ngoài, tắt security). → Gateway từ chối TRƯỚC khi tới LLM. Đây là lằn ranh đỏ.
- **⏸️ Lớp B — interrupt, phải hỏi người**: hủy/đóng ticket, đổi scope sprint, message external stakeholder, đổi assignee người thật, đóng/merge PR. → Agent đề xuất + lý do, người approve.
- **✅ Auto (autonomous OK)**: post report Slack, update trang Confluence report (có version), comment Jira, tạo ticket trong project được phép.

### 5.3 Bắt buộc (xem PDR §7):
audit log bất biến · `DRY_RUN` default khi dev · kill switch · scoped tokens · rate limit · idempotency · ưu tiên reversible · **budget cap $50/tháng OpenRouter (hard-stop 100%, cảnh báo 80%)**.

## 6. Cross-cutting

- **Config**: `.env` (không commit) + `config.example.env` (commit, làm mẫu). Mọi secret qua env, KHÔNG hardcode.
- **Secrets**: token scoped tối thiểu mỗi công cụ. Document cách lấy ở `deployment-guide.md`.
- **Audit log**: append-only (file JSONL hoặc bảng riêng). Mỗi entry: thời gian, tool, action, params, kết quả, lý do agent.
- **Observability**: log structured; cân nhắc LangSmith/Langfuse khi cần trace LLM (DeerFlow dùng cả hai — tham khảo).

## 7. Đường lên scale (đừng làm bây giờ, nhưng đừng chặn)

| Khía cạnh | MVP local | Khi scale |
|---|---|---|
| Entry | CLI + cron | + Slack bot + HTTP service |
| Checkpointer | SQLite file | Postgres |
| Multi-user | 1 user | per-user session/thread isolation |
| Deploy | chạy tay / launchd | container + scheduler |

Giữ "lõi agent" không biết gì về entry point → thêm Slack/HTTP sau chỉ là thêm adapter, không sửa graph.

## 8. Cây thư mục đề xuất (agent build tự quyết chi tiết)

```
my-project-manager/
├── src/
│   ├── agent/            # LangGraph graph, nodes, state
│   ├── adapters/         # mcp_adapter.py (langchain-mcp-adapters) + cli_adapter.py (gh, sau: GWS)
│   ├── tools/            # *_read.py (READ layer) — gọi adapter, trả data chuẩn hóa
│   ├── actions/          # action_gateway.py + hard_block.py + *_write.py (WRITE layer)
│   ├── llm/              # provider config, prompts
│   ├── config/           # settings, env loading
│   ├── audit/            # audit log
│   └── entrypoints/      # cli.py, cron.py, (sau: slack.py, server.py)
├── tests/
├── docs/                 # (bộ docs này)
├── plans/
├── .env / config.example.env
└── pyproject.toml
```

## 9. Unresolved (kiến trúc)

1. LLM provider/model cụ thể → quyết prompt + cost (PDR §9.3).
2. Có cần message queue khi scale (nhiều report song song) hay cron tuần tự là đủ?
3. Audit log: file JSONL local đủ cho MVP, hay cần DB ngay để query/đối soát?
4. Multi-project data model — ảnh hưởng state schema, quyết sớm nếu chắc chắn multi.
