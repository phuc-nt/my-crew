# Deployment & Setup Guide — my-project-manager

> Cách chạy + cấu hình. Status: **Initial 2026-06-21** (Phase 0, chưa có code chạy thật).
> Cập nhật chi tiết khi scaffold xong.

## 1. Yêu cầu

- Python 3.12+ (venv pin 3.12 qua `uv python install 3.12`; KHÔNG dùng global nếu là 3.14+)
- `uv` (khuyến nghị) hoặc `pip`
- **Node.js** — chạy 3 MCP server (Jira/Confluence/Slack, đều Node/TS stdio). Build `dist/` trước (`npm install && npm run build` trong mỗi repo server).
- **`gh` CLI** — GitHub integration (auth: `gh auth login`, scoped — xem §3). Tương lai: **GWS CLI**.
- Token: Atlassian (Jira+Confluence chung site) + Slack **browser-token** → cấp cho **MCP server** (không cho agent Python). GitHub auth qua `gh`.
- **OpenRouter API key** — provider LLM (instance thật, không mock). Model mặc định `minimax/minimax-m2.7`, fallback `qwen/qwen-3.7`.

> **Integration (CHỐT 2026-06-21)**: agent KHÔNG gọi SDK Python tới Jira/Confluence/Slack. Đi qua MCP server có sẵn (`~/workspace/{jira,confluence,slack-browser}-*-mcp-server`) + `gh` CLI. Xem `system-architecture.md §4`. MCP server chạy sẵn, agent connect (`langchain-mcp-adapters`).

> Tất cả instance là **THẬT** (Atlassian Cloud + Slack + GitHub thật). Build/test trực tiếp, không mock — cẩn trọng với write (xem kill switch §4 + dry-run trước khi chạy thật).

## 2. Setup local (MVP)

```bash
cd ~/workspace/my-project-manager
# cài deps (sau khi có pyproject.toml)
uv sync            # hoặc: pip install -e .
cp config.example.env .env
# điền token vào .env (KHÔNG commit .env)
```

Chạy (sau khi có entrypoint):
```bash
# dry-run mặc định khi dev
DRY_RUN=true python -m src.entrypoints.cli "tạo report tiến độ sprint hiện tại"
# chạy thật (write lên Slack/Confluence) — bật explicit
DRY_RUN=false python -m src.entrypoints.cli "..."
```

## 3. Secrets & scoped tokens (BẮT BUỘC tối thiểu quyền)

Mỗi token cấp quyền **tối thiểu** cần (PDR §7.4). KHÔNG dùng token full-admin.

Token Atlassian/Slack cấp cho **MCP server** (đặt ở env của server), GitHub auth qua **`gh`**. Agent Python chỉ giữ `OPENROUTER_API_KEY` + cấu hình kết nối MCP. Mỗi quyền **tối thiểu** (PDR §7.4). KHÔNG token full-admin.

| Công cụ | Integration | Token / auth | Scope tối thiểu (MVP) |
|---|---|---|---|
| GitHub | `gh` CLI | `gh auth login` (PAT fine-grained) | đọc repo + PR + commit + checks; **không** admin/delete |
| Jira | MCP server | API token (email + token) | đọc issue/sprint; write comment/tạo issue — chỉ project liên quan |
| Confluence | MCP server | **cùng** Atlassian token (`CONFLUENCE_EMAIL` + `CONFLUENCE_API_TOKEN`) | đọc/ghi space report cụ thể |
| Slack | MCP server | **browser-token** (session) | ⚠️ rộng quyền — siết: chỉ post channel cho phép; gateway hard-block public/credential |
| OpenRouter | agent Python | API key (`sk-or-...`) | gọi model; set `HTTP-Referer` + `X-Title` header |

Token MCP server lưu ở env **của server đó** (xem README mỗi repo `~/workspace/*-mcp-server`). Agent: `.env` chỉ chứa OpenRouter + config kết nối MCP (host/port/transport). Liệt kê biến ở `config.example.env` (commit, không giá trị thật).

**Atlassian Cloud lưu ý**: Jira + Confluence chung 1 site (`https://<org>.atlassian.net`) → **1 API token dùng chung** (email + token). Lấy tại id.atlassian.com → Security → API tokens. Token này cấp cho **MCP server**, không cho agent.

**⚠️ Slack browser-token**: `slack-browser-mcp-server` auth bằng session cookie/browser-token (không cần app/admin approve) → quyền **rộng hơn** bot-token scoped. Đây là rủi ro credential cao hơn → guardrail Lớp A siết kỹ, và chỉ cho post vào channel whitelist.

**⚠️ Known residual risk — Atlassian token không có prefix cố định (CHỐT chấp nhận 2026-06-21)**: bộ phát hiện secret (`src/actions/secret_patterns.py`) bắt token theo regex prefix (xox*, sk-or-, ghp_, AKIA…). Atlassian API token (`ATATT…` không ổn định) → **không bắt được khi nằm trong free-text**; chỉ bị redact/chặn khi đặt dưới key tên secret (`token`, `api_token`…). Nguyên tắc vận hành: KHÔNG đưa Atlassian token vào field free-text. Sẽ siết thêm khi wire MCP thật ở Phase 1 (token nằm ở env của MCP server, agent không cầm token trực tiếp nên rủi ro thực tế thấp).

**Biến env agent dự kiến** (tên chính xác chốt ở `config.example.env`):
```
OPENROUTER_API_KEY=
OPENROUTER_MODEL=minimax/minimax-m2.7        # fallback: qwen/qwen-3.7
# Kết nối MCP server (chạy sẵn, agent connect) — host/port/transport chốt Phase 1
# Token Atlassian/Slack đặt ở env của từng MCP server, KHÔNG ở đây
DRY_RUN=true
AGENT_WRITE_DISABLED=false
MONTHLY_BUDGET_USD=50
```

## 4. Kill switch (PDR §7.3)

Tắt toàn bộ write tức thì:
```bash
# cách dự kiến — agent build implement + ghi lại chính xác ở đây
export AGENT_WRITE_DISABLED=true
```
→ Action Gateway từ chối mọi mutation, chỉ còn READ + log.

## 5. Cron (report định kỳ — Phase 1)

Dự kiến chạy qua launchd (macOS) hoặc cron:
- Daily standup digest (vd 9:00).
- Weekly sprint report (vd thứ 6 17:00).

Lệnh cụ thể + lịch: agent build điền sau khi entrypoint cron xong.

## 6. Đường lên service (Phase 5 — chưa làm)

- Đóng container, deploy backend + Slack bot.
- Checkpointer SQLite → Postgres.
- Per-user/per-project isolation.
Xem `system-architecture.md §7`.

## 7. Unresolved (deploy)

1. Có Jira/GitHub/Slack/Confluence instance thật để test chưa, hay cần sandbox/mock? (PDR §9.1)
2. Chạy cron trên máy nào (máy cá nhân / server)?
3. LLM provider + nơi giữ key (env / secret manager)?
