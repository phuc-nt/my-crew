# Deployment & Setup Guide — my-project-manager

> Cách chạy + cấu hình. Status: **As-built (Phase 0–5 complete).** Mọi lệnh dưới đây chạy thật.

## 1. Yêu cầu

- Python 3.12+ (venv pin 3.12 qua `uv python install 3.12`; KHÔNG dùng global nếu là 3.14+)
- `uv` (khuyến nghị) hoặc `pip`
- **Node.js** — chạy 3 MCP server (Jira/Confluence/Slack, đều Node/TS stdio). Build `dist/` trước (`npm install && npm run build` trong mỗi repo server).
- **`gh` CLI** — GitHub integration (auth: `gh auth login`, scoped — xem §3).
- **`gws` CLI** (Google Workspace CLI, unofficial — `gws sheets spreadsheets values get`) — [M6+] chỉ cần cho **hr-pack** đọc Google Sheet; PM không cần. Auth qua `gws auth` (OAuth riêng, độc lập core; token KHÔNG ở `.env`). Spawn như `gh`. Không có → hr-pack báo lỗi rõ khi chạy.
- Token: Atlassian (Jira+Confluence chung site) + Slack **browser-token** → để ở **`.env` của agent**; agent **inject xuống env subprocess** khi spawn MCP server (server đọc từ process env lúc startup). GitHub auth qua `gh`.
- **OpenRouter API key** — provider LLM (instance thật, không mock). Model mặc định `minimax/minimax-m2.7`, fallback `qwen/qwen-3.7`.

> **Integration (CHỐT 2026-06-21)**: agent KHÔNG gọi SDK Python tới Jira/Confluence/Slack. Agent **SPAWNS** 3 MCP server làm subprocess (stdio-only via `langchain-mcp-adapters==0.3.0`): `~/workspace/{jira,confluence,slack-browser}-*-mcp-server` + GitHub via `gh` CLI. Xem `system-architecture.md §4`. Mỗi MCP spawn tắt subprocess sau gọi (chống leak node).

> Tất cả instance là **THẬT** (Atlassian Cloud + Slack + GitHub thật). Build/test trực tiếp, không mock — cẩn trọng với write (xem kill switch §4 + dry-run trước khi chạy thật).

## 2. Setup local

```bash
git clone git@github.com:phuc-nt/my-project-manager.git
cd my-project-manager
uv sync                       # cài deps (Python 3.12)
uv run pytest                 # verify install — 269 tests, không cần network/secret
cp config.example.env .env    # điền token vào .env (KHÔNG commit .env)
```

### 2.1 Build 3 MCP server (external dependency)

Agent đọc Jira/Confluence/Slack qua 3 MCP server (Node, stdio) mà nó spawn làm subprocess. Clone +
build từng cái (mỗi repo có README riêng):

```bash
cd ~/workspace
for repo in jira-cloud-mcp-server confluence-cloud-mcp-server slack-browser-mcp-server; do
  git clone git@github.com:phuc-nt/$repo.git
  (cd $repo && npm install && npm run build)   # tạo dist/index.js
done
```

- Jira → https://github.com/phuc-nt/jira-cloud-mcp-server
- Confluence → https://github.com/phuc-nt/confluence-cloud-mcp-server
- Slack (browser-token) → https://github.com/phuc-nt/slack-browser-mcp-server

Mặc định agent tìm `dist/index.js` ở `~/workspace/{jira,confluence,slack-browser}-*-mcp-server`. Nếu
để chỗ khác, set `JIRA_MCP_DIST` / `CONFLUENCE_MCP_DIST` / `SLACK_MCP_DIST` trong `.env`. GitHub không
cần MCP server — chỉ cần `gh auth login` (§3).

### 2.2 Chạy

```bash
# DRY_RUN=true (mặc định trong .env khi dev) → log "định làm gì", KHÔNG post thật
uv run python -m src.entrypoints.cli report --daily
uv run python -m src.entrypoints.cli report --weekly --audience external   # → Lớp B queue

# chạy thật (write lên Slack/Confluence) — bật explicit
DRY_RUN=false uv run python -m src.entrypoints.cli report --daily
```

Các lệnh khác: `report [--daily|--weekly|--okr|--resource] [--audience internal|external]`,
`audit [filters]`, `approvals`, `approve <id>`, `reject <id>` (audit/approval không cần OpenRouter key).

## 3. Secrets & scoped tokens (BẮT BUỘC tối thiểu quyền)

Mỗi token cấp quyền **tối thiểu** cần (PDR §7.4). KHÔNG dùng token full-admin.

**Mô hình token (CHỐT 2026-06-21):** Tất cả token sống **1 chỗ duy nhất — `.env` của agent**. Agent (MCP client) đọc từ `.env`, rồi **inject vào env của subprocess** khi spawn MCP server (`reporting_config.py` build env → `mcp_adapter.py` truyền qua `MultiServerMCPClient`). Server đọc env lúc startup. KHÔNG có file `.env` riêng cho từng server; KHÔNG có chuyện token nằm 2 nơi. (MCP protocol không truyền credential qua message với 3 server stdio này → bắt buộc env-at-spawn; đây là giới hạn của *server*, không phải lựa chọn.) GitHub auth qua `gh` (CLI tự quản, không qua `.env`). Mỗi quyền **tối thiểu** (PDR §7.4). KHÔNG token full-admin.

| Công cụ | Integration | Token / auth | Scope tối thiểu (MVP) |
|---|---|---|---|
| GitHub | `gh` CLI | `gh auth login` (PAT fine-grained) | đọc repo + PR + commit + checks; **không** admin/delete |
| Jira | MCP server | API token (email + token) | đọc issue/sprint; write comment/tạo issue — chỉ project liên quan |
| Confluence | MCP server | **cùng** Atlassian token (`CONFLUENCE_EMAIL` + `CONFLUENCE_API_TOKEN`) | đọc/ghi space report cụ thể |
| Slack | MCP server | **browser-token** (session) | ⚠️ rộng quyền — siết: chỉ post channel cho phép; gateway hard-block public/credential |
| OpenRouter | agent Python | API key (`sk-or-...`) | gọi model; set `HTTP-Referer` + `X-Title` header |

**Token MCP server** (để ở `.env` AGENT; agent inject vào subprocess lúc spawn):
- **Jira**: `ATLASSIAN_SITE_NAME`, `ATLASSIAN_USER_EMAIL`, `ATLASSIAN_API_TOKEN`
- **Slack**: `SLACK_XOXC_TOKEN`, `SLACK_XOXD_TOKEN`, `SLACK_TEAM_DOMAIN`
- **GitHub**: `gh auth login` (không `.env`, CLI tự quản)

Toàn bộ ở **1 file `.env` của agent** cùng OpenRouter + config report (`JIRA_PROJECT_KEY`, `GITHUB_REPO`, `SLACK_REPORT_CHANNEL`, `PR_STALE_DAYS`, `BLOCKER_LABEL_SUBSTRING`). Liệt kê đầy đủ ở `config.example.env` (commit, không giá trị thật). `.env` gitignored.

**Atlassian Cloud lưu ý**: Jira + Confluence chung 1 site (`https://<org>.atlassian.net`) → **1 API token dùng chung** (email + token). Lấy tại id.atlassian.com → Security → API tokens. Để token vào `.env` agent (agent inject xuống MCP server lúc spawn).

**⚠️ Slack browser-token**: `slack-browser-mcp-server` auth bằng session cookie/browser-token (không cần app/admin approve) → quyền **rộng hơn** bot-token scoped. Đây là rủi ro credential cao hơn → guardrail Lớp A siết kỹ, và chỉ cho post vào channel whitelist.

**⚠️ Known residual risk — Atlassian token không có prefix cố định (CHỐT chấp nhận 2026-06-21)**: bộ phát hiện secret (`src/actions/secret_patterns.py`) bắt token theo regex prefix (xox*, sk-or-, ghp_, AKIA…). Atlassian API token (`ATATT…` không ổn định) → **không bắt được khi nằm trong free-text**; chỉ bị redact/chặn khi đặt dưới key tên secret (`token`, `api_token`…). Nguyên tắc vận hành: KHÔNG đưa Atlassian token vào field free-text. Sẽ siết thêm khi wire MCP thật ở Phase 1 (token nằm ở env của MCP server, agent không cầm token trực tiếp nên rủi ro thực tế thấp).

**Biến env agent** (chốt ở `config.example.env`):
```
# LLM
OPENROUTER_API_KEY=
OPENROUTER_MODEL=minimax/minimax-m2.7        # fallback: qwen/qwen-3.7

# Report config
JIRA_PROJECT_KEY=
GITHUB_REPO=
SLACK_REPORT_CHANNEL=
PR_STALE_DAYS=7
BLOCKER_LABEL_SUBSTRING=block

# Guardrail
DRY_RUN=true
AGENT_WRITE_DISABLED=false
MONTHLY_BUDGET_USD=50

# MCP server — KHÔNG để token ở đây; token Atlassian/Slack ở env của từng server
```

## 4. Kill switch (PDR §7.3)

Tắt toàn bộ write tức thì:
```bash
# cách dự kiến — agent build implement + ghi lại chính xác ở đây
export AGENT_WRITE_DISABLED=true
```
→ Action Gateway từ chối mọi mutation, chỉ còn READ + log.

## 5. Cron (report định kỳ — launchd macOS)

Entrypoint: `python -m src.entrypoints.cron --daily|--weekly` (gọi cùng luồng report).
- **Daily standup digest** — 9:00 mỗi ngày (`com.mpm.report.daily.plist`).
- **Weekly sprint review** — thứ 6 17:00, kéo thêm Jira sprint data (`com.mpm.report.weekly.plist`).

Artifacts ở `deploy/launchd/`: 4 plist template (placeholder `__REPO_DIR__`) + `run-report.sh`
(wrapper tự dò repo root, set PATH cho node/gh/uv, gọi cron) + `install.sh` / `uninstall.sh`.

**Cài** — dùng `install.sh`, nó tự thay đường dẫn clone vào plist (KHÔNG cần sửa path tay):
```bash
./deploy/launchd/install.sh            # service điều phối (v2): worker/agent theo registry + schedule
./deploy/launchd/install.sh --legacy   # hoặc: 3 cron single-agent (v1) cho profile `default`
```
> Chỉ chạy MỘT trong hai — chạy cả hai gây double-schedule.

**Gỡ:** `./deploy/launchd/uninstall.sh` (unload + xóa mọi job mpm).
**Log:** service → `.data/service.log`; legacy cron → `.data/cron-{daily,weekly,resource}.log` (+ `.err.log`).

⚠️ **Lưu ý**:
- launchd chỉ chạy khi máy bật. Cron chạy với env tối thiểu → wrapper tự set PATH; token đọc từ `.env`.
- Mặc định `.env` có `DRY_RUN=true` (chỉ log). **Để cron post thật, đặt `DRY_RUN=false` trong `.env`.**
- `install.sh` bake đường dẫn clone tuyệt đối vào plist ở `~/Library/LaunchAgents/` (launchd cần path tuyệt đối + không expand biến). Pull template mới thì chạy lại `install.sh`.

## 6. Đường lên service (Phase 5 — chưa làm)

- Đóng container, deploy backend + Slack bot.
- Checkpointer SQLite → Postgres.
- Per-user/per-project isolation.
Xem `system-architecture.md §7`.

## 7. Unresolved (deploy)

1. Có Jira/GitHub/Slack/Confluence instance thật để test chưa, hay cần sandbox/mock? (PDR §9.1)
2. Chạy cron trên máy nào (máy cá nhân / server)?
3. LLM provider + nơi giữ key (env / secret manager)?
