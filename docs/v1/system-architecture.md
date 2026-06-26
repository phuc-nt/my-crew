# System Architecture — my-project-manager

> Kiến trúc kỹ thuật. Status: **As-built (Phase 0–5).** Các đề xuất "agent build có thể tinh chỉnh"
> bên dưới giờ KHỚP với code thật (spot-check verify). Phần "guardrail" có explainer riêng:
> `action-gateway-explainer.md`. Đọc cùng `project-overview-pdr.md` (vì sao) + `code-standards.md`.

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

- **MCP adapter** — Jira, Confluence, Slack qua các **MCP server có sẵn** (Node/TS, **stdio-only, KHÔNG có HTTP**). Agent là **MCP client** (`langchain-mcp-adapters==0.3.0`). **CHỐT lại 2026-06-21 (Phase 1)**: vì stdio-only, agent **SPAWN từng server làm subprocess** (`node dist/index.js` + env token), KHÔNG phải "server chạy sẵn rồi connect" (giả định Phase 0 sai). API adapter là async → bridge sang CLI sync bằng `asyncio.run`; mỗi lần gọi mở `async with client.session()` để tắt subprocess sau (chống leak node). Code: `src/adapters/mcp_adapter.py`. 3 server tại:
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

### 5.1 Mỗi write request đi qua chuỗi (CHỐT — `action_gateway.py`):
```
request → [Lớp A hard-deny] → [Lớp B interrupt? → queue chờ approve, KHÔNG chạy]
        → [deny nếu blocked] → [kill-switch] → [dry-run?] → [rate-limit]
        → [idempotency dedup bền (SQLite, reserve-before-execute)]
        → [execute handler] → [audit log] → return
```
Lớp B (merge/close PR, close/transition/assign issue, post channel external) →
ghi `approval_store` (SQLite) + audit verdict `pending`, người duyệt qua
`cli approve <id>` (chạy qua gateway, skip Lớp B nhưng VẪN qua Lớp A + audit).
Lớp A KHÔNG bao giờ bị override kể cả khi approve.

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

### 6.1 Skill system (M3-P10) — instruction-only PM guidance

Agent chứa 1 **candidate pool** những bundled PM kỹ năng (`.md` files ở `skills/`) — mỗi skill là frontmatter YAML (name/description/applies_to; `allowed-tools` được parse-nhưng-bỏ-qua) + markdown instruction body.

**Data flow**:
1. `profile.yaml` `skills: [flag-risk, prioritize-blockers, ...]` ⇒ danh sách tên ứng viên.
2. `src/skills/skill_loader.py:load_skills()` quét `skills/*.md` → `Skill` objects (name, description, body, applies_to).
3. `src/skills/skill_pool.py:build_skill_context()` lọc danh sách ứng viên ra `(pool, selector)`, với selector là injectable LLM picker.
4. Graph-build entry points (worker/cron/cli ở `src/runtime/worker.py`, `src/entrypoints/cron.py`, `src/entrypoints/cli.py`) gọi `build_skill_context(loaded, settings)` → cặp `(skills, skill_selector)` vào `ProfileContext`.
5. Ở compose node, mỗi report builder gọi `select_skill_text(context, audience, kind="report|okr|resource")` → LLM selector chọn kỹ năng phù hợp từ pool.
6. Chosen skill bodies render vào `<pm_skills>` block, inject vào **INTERNAL-only** compose prompt (report/okr/resource).

**Red line (critical)**: skills = INSTRUCTION-ONLY, INTERNAL-ONLY. Chúng:
- **Không grant tool authority** — không MCP tool nào, không Action Gateway seam nào.
- **Không reach external audience** — external report path return TRƯỚC khi reference `context.skills`; `select_skill_text()` trả "" khi `audience != "internal"`.
- Phòng chống sâu: mỗi builder's external branch return trước access context.skills.

**Backward-compat**: `profile.yaml` không declare `skills:` (hoặc dùng default profile) → empty pool → `build_skill_context()` return `((), None)` KHÔNG construct `LlmClient` (allocation-free, không cần key) → compose prompt byte-identical với v1.

**Wiring**: tất cả graph-build sites (worker/cron/cli) → mọi `builder(context=...)` call mang skills; M2-P6 server run path kế thừa via worker helper.

### 6.2 Cross-agent memory (M3-P9 A3) — sibling facts đọc-chéo, internal-only

Hai agent khai cùng `project: <slug>` trong `profile.yaml` là **sibling**. Một agent ĐỌC fact đã nhớ của sibling (chính các fact mà node `remember` A2 ghi vào Store) — read-only; không bao giờ ghi namespace của sibling.

Luồng:
1. `profile.yaml` `project: acme` ⇒ `LoadedProfile.project_group`. Không khai ⇒ `None` ⇒ không sibling.
2. Entry point gọi `src/agent/sibling_memory.py:build_sibling_context(loaded, settings, store, registry)`: liệt kê agent enabled cùng `project_group` trong registry (trừ self; sibling load lỗi → warn + skip, không crash), rồi đọc fact mỗi sibling từ Store namespace `(sibling_id, "memory")` qua `store.search` **namespace-scoped** (KHÔNG prefix wildcard — chạy được cả InMemoryStore lẫn PostgresStore), cap `MAX_SIBLING_FACTS`.
3. Cặp `(sibling_facts, selector)` vào `ProfileContext` (3 field: `sibling_facts`/`sibling_selector`/`sibling_project`). Selector là injectable LLM ranker (`sibling_selector.make_llm_selector`), chỉ dựng khi có fact (no-op path allocation-free, không cần key).
4. Compose node gọi `select_sibling_text(context, audience, kind, project_group)` → ranker giữ fact liên quan kind (lọc về đúng input set, chống bịa) → render block `--- Bộ nhớ agent khác (project: <slug>) ---` → inject vào **INTERNAL** compose prompt, sau `<pm_skills>`.

**Red line (critical)**: sibling facts INTERNAL-ONLY — external report KHÔNG lấy gì (gate `select_sibling_text` trả "" cho external; mỗi builder fold sibling text SAU external early-return). KHÔNG qua Action Gateway (memory là internal state). Phòng thủ 2 lớp như skills.

**WO-self / RO-sibling**: ghi memory chỉ vào `(self_id, "memory")` — `memory_node._assert_self_namespace` raise `PermissionError` nếu namespace khác (fail loud). Cross-agent là READ-only.

**Threat-model widening (R6)**: A3 MỞ RỘNG phạm vi lộ — agent B giờ đọc fact thô của agent A; memory KHÔNG được secret-scan (`memory_extractor.py` accepted residual risk). Mitigation = ranh giới internal-only (không tạo bề mặt external mới). **Đừng route sibling facts ra external.**

**Hiệu lực runtime**: đọc-chéo chỉ hiệu lực khi Store CHIA SẺ giữa process các sibling — tức `store: postgres`. Với `store: memory` (default), mỗi process có store riêng → B không thấy fact của A ở chạy multi-process thật; A3 khi đó degrade sạch về "no sibling facts" (đúng nhánh backward-compat). E2E offline chứng minh logic bằng một InMemoryStore chung (cùng process).

**Backward-compat**: không `project:` (hoặc group 1 agent) → `build_sibling_context` return `((), None)` không dựng `LlmClient` → compose prompt byte-identical.

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
