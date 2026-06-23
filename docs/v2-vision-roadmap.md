---
title: "v2 Vision + Roadmap — Multi-agent PM platform"
description: "From a single-project PM agent to N profile-bound agents managed from a web dashboard, guardrail preserved per-agent."
status: draft
created: 2026-06-23
supersedes: extends docs/project-roadmap.md (picks up its deferred items: service backend, multi-user, Postgres scale-up)
priority: P2
tags: [v2, vision, roadmap, multi-agent, langgraph, web-ui]
---

# v2 Vision + Roadmap — my-project-manager

> Forward-looking design doc. Status: **draft** — đọc, duyệt, rồi `/cook` từng phase.
> Mở rộng `docs/project-roadmap.md` (v1 Phase 0–5 đã xong). v1 = single-agent, single-project.
> v2 = **nhiều agent, mỗi agent một project, quản lý từ web dashboard, guardrail giữ nguyên per-agent.**
> Bilingual như các doc khác: prose tiếng Việt, code/identifier tiếng Anh.

## 1. Vision

v1 chứng minh được một luận điểm: một LLM agent có thể **full autonomous write** vào Jira/GitHub/Slack/Confluence mà vẫn an toàn, nhờ Action Gateway (Lớp A hard-deny + Lớp B approve + audit + budget + dedup). Nhưng v1 chỉ phục vụ **một project**, cấu hình qua **một file `.env` toàn cục**, kích hoạt qua **CLI/cron**. Muốn theo dõi project thứ hai phải clone repo hoặc đổi `.env` — không scale.

v2 biến nó thành một **multi-agent PM platform**. Mỗi agent = **một `profile.md`** (YAML frontmatter cho config + Markdown body cho persona/SOUL) bound vào **một project** (Jira/GitHub/Slack/Confluence bindings riêng). Một **registry** liệt kê tất cả agent; một **coordinating service** spawn mỗi agent thành một **worker process** chạy graph của nó (theo lịch + on-demand), với **data isolation hoàn toàn** per-agent (`checkpoints/audit/budget/approvals/dedup` riêng từng agent). Bạn chạy 5 agent cho 5 project, mỗi cái tone + threshold + schedule + budget riêng, không cái nào đụng cái nào.

Trên hết là một **web dashboard** (FastAPI + HTMX/Streamlit): thấy danh sách agent + trạng thái (running/idle/error), cost vs budget từng agent, audit gần đây, **các Lớp B approval đang chờ (approve/reject ngay trên UI)**, xem/sửa config từng agent, **trigger một report on-demand**. Đồng thời v2 khai thác sâu LangGraph mà v1 MVP chưa dùng: **graph-native interrupts** cho human-in-the-loop, **streaming** để UI xem agent chạy live, **Postgres checkpointer + Store** cho state đa-process + cross-thread memory. Điều bất biến: **Action Gateway guardrail được GIỮ NGUYÊN, chỉ trở thành per-agent** — red line Lớp A vẫn hard-coded trước LLM, mọi write vẫn qua một cổng, giờ một cổng *cho mỗi agent*.

## 2. What changes vs v1

| Khía cạnh | v1 (as-built) | v2 (target) |
|---|---|---|
| Số agent / project | 1 agent, 1 project | **N agent, mỗi agent 1 project** |
| Config | 2 `@lru_cache` singleton (`get_reporting_config`, `get_settings`) đọc `.env` toàn cục | **`profile.md` per-agent, inject làm parameter** vào graph/gateway/store/tool |
| Persona / prompt | system prompt hardcode trong `src/llm/*` | **Markdown body của profile override** lớp prompt |
| Kích hoạt | CLI + cron | CLI + **worker** + **web dashboard** (M2) |
| Runtime | 1 process, chạy tay/launchd | **registry → coordinating service → N worker process** |
| Data | shared `.data/` (1 checkpoints/audit/budget/approvals/dedup) | **`.data/agents/<id>/` riêng từng agent**; `thread_id` chứa `agent_id` |
| Checkpointer | `SqliteSaver` (1 file) | **Postgres checkpointer** (multi-process) + **Store** (cross-thread memory) |
| Lớp B approval | gateway-level queue (`pending_approval` + `approval_store` + `cli approve`) | **graph-native interrupt** (pause→UI hỏi→resume, checkpoint-serialized) — augment/replace queue |
| Quan sát | đọc JSONL audit + `cli audit` | **web dashboard**: status, cost, audit, pending approvals, streaming live run |
| **Guardrail** | Action Gateway (Lớp A/B + audit + budget + dedup) | **GIỮ NGUYÊN — chỉ trở thành per-agent** (mỗi agent một gateway + một bộ store) |

> Guardrail **không** bị viết lại. Lớp A red-line, allowlist-default-deny, audit, budget cap, dedup reserve-before-execute — tất cả giữ. Thay đổi duy nhất: chúng được khởi tạo *per-agent* (path + config từ profile) thay vì từ singleton toàn cục.

## 3. The agent PROFILE (centerpiece)

Mỗi agent = **một file** `profiles/<agent-id>/profile.md`. YAML frontmatter giữ config có cấu trúc; Markdown body giữ persona (SOUL) override system prompt. Tokens **KHÔNG** nằm trong profile — frontmatter chỉ *tham chiếu tên env var* chứa token; giá trị thật ở env/secret store (xem §9 Risks).

### 3.1 `profile.md` ví dụ (copy-pasteable)

```markdown
---
# --- Identity ---
id: acme-web                      # unique, [a-z0-9-], = thư mục .data/agents/<id>/ + thread_id prefix
name: "ACME Web Platform"
enabled: true                     # registry bỏ qua agent disabled
model: minimax/minimax-m2.7       # override OpenRouter model cho riêng agent này

# --- Project bindings (1 agent = 1 project) ---
bindings:
  jira:
    project_key: ACME
    token_env: ACME_JIRA_TOKEN    # TÊN env var, không phải token; server đọc khi spawn
    mcp_dist: ~/workspace/jira-cloud-mcp-server/dist/index.js   # optional, default global
  github:
    repo: acme/web-platform       # owner/repo, dùng qua `gh`
  slack:
    report_channel: "#acme-standup"
    stakeholder_channel: "#acme-exec"      # external; route qua Lớp B
    external_channels: ["#acme-exec"]      # channel cần approval; stakeholder PHẢI nằm trong đây
    token_env: ACME_SLACK_BROWSER_TOKEN
  confluence:
    space_key: ACME
    space_id: "123456"
    token_env: ACME_CONFLUENCE_TOKEN
    okr_page_id: "557057"          # optional; OKR no-op nếu trống

# --- Thresholds (per-agent tuning; default = v1) ---
thresholds:
  pr_stale_days: 3
  blocker_label_substring: "blocker"
  okr_behind_threshold: 0.7
  resource_overload_ratio: 1.5
  labor_cost_per_issue: 0          # 0 ⇒ bỏ labor estimate

# --- Budget (per-agent hard-stop) ---
budget:
  monthly_usd: 50
  warn_ratio: 0.8

# --- Schedule (worker đọc; cron/scheduler nội bộ) ---
schedule:
  daily:    "0 9 * * *"            # 09:00 mỗi ngày
  weekly:   "0 17 * * 5"           # 17:00 thứ 6
  resource: "0 9 * * 1"            # 09:00 thứ 2

# --- Report kinds enabled ---
reports: [daily, weekly, okr, resource]

# --- Safety flags (per-agent override; default an toàn) ---
safety:
  dry_run: false
  write_disabled: false
---

# Persona — ACME Web Platform agent

Bạn là PM agent cho team ACME Web Platform. Giọng điệu: ngắn gọn, thực tế,
ưu tiên hành động. Khi viết report internal, dùng issue key + assignee thật.
Khi viết external (stakeholder), bỏ hết key/PR#/tên người, chỉ nói tiến độ
business-level và rủi ro ở mức "có thể trễ release Q3".

Quy ước riêng team:
- Coi label "p0" là blocker bất kể có chữ "blocker" hay không.
- Khi >2 PR treo cùng reviewer, gọi tên rủi ro "review bottleneck".

(Phần body này OVERRIDE/PREPEND vào system prompt mặc định ở src/llm/*.
Trống ⇒ dùng prompt mặc định v1 nguyên vẹn.)
```

### 3.2 Field-by-field

| Field | Vai trò | Map tới v1 |
|---|---|---|
| `id` | unique key — thư mục data + prefix `thread_id` + key trong registry | (mới) |
| `name`, `enabled` | hiển thị + bật/tắt ở registry | (mới) |
| `model` | OpenRouter model per-agent | `Settings.openrouter_model` |
| `bindings.jira/github/slack/confluence` | project bindings | `ReportingConfig` fields (`jira_project_key`, `github_repo`, `slack_*`, `confluence_*`) |
| `bindings.*.token_env` | **tên** env var chứa token (không phải giá trị) | `McpServerSpec.env` + `required_env_keys` |
| `bindings.*.mcp_dist` | override dist path per-agent | `McpServerSpec.dist_path` (default global) |
| `thresholds.*` | risk tuning | `ReportingConfig.pr_stale_days / blocker_label_substring / okr_behind_threshold / resource_overload_ratio / labor_cost_per_issue` |
| `budget.*` | hard-stop per-agent | `Settings.monthly_budget_usd / budget_warn_ratio` |
| `schedule.*` | worker scheduler đọc | (v1: launchd plists toàn cục) |
| `reports` | report kinds bật | (v1: CLI flag) |
| `safety.dry_run / write_disabled` | flag per-agent | `Settings.dry_run / write_disabled` |
| Markdown body | persona override prompt | (mới — v1 prompt hardcode) |

> Synthesis nguồn: frontmatter+body từ DeerFlow `SKILL.md` (YAML `name/description/allowed-tools` + body); bindings/id/model/heartbeat từ OpenClaw `openclaw.json` agents.list[]; per-profile isolation từ Hermes `~/.hermes/profiles/<name>/`. **Adapt, không copy.**

## 4. Architecture (target)

```
                         profiles/                      registry.yaml
                    ┌─ acme-web/profile.md ─┐        ┌─ agents:
                    ├─ beta-app/profile.md  ┤  ◀───  │   - id: acme-web  enabled: true
                    └─ ...                  ┘        │   - id: beta-app  enabled: true  ┘
                                                              │ đọc
                                            ┌─────────────────▼──────────────────┐
                                            │  Coordinating service               │
                                            │  - đọc registry, load mỗi profile   │
                                            │  - spawn 1 worker / agent enabled    │
                                            │  - scheduler (đọc schedule frontmatter)│
                                            │  - on-demand trigger (từ CLI/web)    │
                                            └───────┬───────────────┬─────────────┘
                                  spawn worker      │               │
              ┌──────────────────────────────────▼─┐   ┌──────────▼─────────────────────┐
              │  Worker(acme-web)                   │   │  Worker(beta-app)               │
              │  - load profile → config object     │   │  - load profile → config        │
              │  - build_*_graph(config, settings,  │   │  - build_*_graph(...)           │
              │     gateway, checkpointer)          │   │                                 │
              │  - thread_id = "acme-web:<kind>:<d>" │   │  thread_id = "beta-app:..."     │
              │                                     │   │                                 │
              │  per-agent ActionGateway            │   │  per-agent ActionGateway        │
              │   (Lớp A/B + audit + budget + dedup)│   │   (same guardrail, own stores)  │
              └───────┬─────────────────────────────┘   └──────────┬──────────────────────┘
                      │ read/write isolated                        │
        ┌─────────────▼──────────────┐              ┌──────────────▼──────────────┐
        │ .data/agents/acme-web/      │              │ .data/agents/beta-app/       │
        │   checkpoints.db (→Postgres)│              │   ... (own everything)       │
        │   audit/  budget/  dedup.db │              └──────────────────────────────┘
        │   approvals.db              │
        └─────────────────────────────┘
                      │                                            │
              ┌───────▼────────────────────────────────────────────▼───────┐
              │  Postgres (M2-P8): checkpointer (multi-process state)        │
              │                  + Store (cross-thread memory per-agent)     │
              └─────────────────────────────────────────────────────────────┘

   ┌──────────────────────────────────────────────────────────────────────┐
   │  Web dashboard (FastAPI + HTMX/Streamlit, M2)                          │
   │  đọc registry + per-agent .data/{audit,budget,approvals}              │
   │  - agent list + status   - cost vs budget   - recent audit            │
   │  - pending Lớp B approvals (approve/reject)  - config view/edit        │
   │  - trigger report on-demand  - streaming live run (SSE, M2-P6)         │
   └──────────────────────────────────────────────────────────────────────┘
```

Vị trí Postgres/Store: **M1 vẫn dùng SqliteSaver per-agent** (1 file / agent — đủ vì mỗi worker 1 process, không tranh chấp). **M2-P8** mới giới thiệu Postgres khi cần multi-machine hoặc cross-thread memory. Store sống cạnh checkpointer, namespace theo `agent_id`.

## 5. Milestone M1 — Multi-agent core (CLI/worker, no UI)

> Mục tiêu M1: chạy được **N agent / N project, isolated, qua CLI/worker** — giá trị thật trước khi có UI. Mỗi phase chạy được + có giá trị, không big-bang (nguyên tắc v1 giữ nguyên).

### P1 — Config-injection refactor (kill singletons) **[BREAKING]**

- **Goal**: bỏ 2 `@lru_cache` singleton; config trở thành object truyền vào làm parameter. Đây là nền cho mọi thứ sau.
- **Key changes**:
  - Giữ `ReportingConfig` + `Settings` (đã là `@dataclass(frozen=True)` — `reporting_config.py:59`, `settings.py:47`) nhưng **bỏ `@lru_cache`** (`reporting_config.py:102`, `settings.py:78`); chuyển thành builder nhận `dict`/profile thay vì đọc `.env` toàn cục.
  - Thread config qua param tới ~21 call site (đã verify, theo category):
    - **Tool fetchers (4 file)**: `jira_read.py` (3 call: :99/:135/:160), `github_read.py` (2: :97/:114), `okr_read.py` (:73), `confluence_read.py` (:82) — đổi sang nhận `cfg` param.
    - **Graph builders / deps (factory)**: `report_graph.py:70`, `okr_weekly_section.py` (:36/:64/:81), `resource_weekly_section.py` (:37/:40/:69/:83), `audience_delivery.py:33` — `default_*_deps(...)` nhận `config`+`settings`.
    - **Action writers (3 file)**: `confluence_write.py` (:78/:100), `slack_write.py` (:29/:59), `action_gateway.py` (:106/:108 external_channels — đã có param `external_channels` ở `__init__:122`, chỉ cần bắt buộc truyền).
    - **Storage (4 file)**: `checkpoint.py:32` (đã nhận `db_path`), `approval_store.py:37` (đã nhận `db_path`), `audit_log.py:52` (đã nhận `path`), `dedup_store.py:25` (đã nhận `db_path`) — bỏ default `get_settings().data_dir`, bắt buộc truyền path.
    - **Budget / LLM (2 file)**: `budget_tracker.py:38` (đã nhận `settings`), `client.py:54` (đã nhận `settings`) — bỏ fallback `get_settings()`.
    - **Entrypoints (2 file)**: `cli.py` (:22/:35/:60), `cron.py` (:64/:72) — đọc profile, build config, truyền xuống.
- **Files touched**: ~21 (6 graph/section, 4 tool, 3 action, 4 storage, 2 budget/llm, 2 entrypoint) + 2 config.
- **Acceptance**:
  - `grep -rn "get_reporting_config\|get_settings" src/` → **0 hit** (ngoài định nghĩa builder).
  - Toàn bộ 269 test pass sau khi đổi sang truyền config (test có thể cần update fixtures — chấp nhận, breaking allowed).
  - `ruff` clean.
- **Risks**: lan rộng (21 file) nhưng **logic graph không đổi** — chỉ plumbing. Risk = bỏ sót call site → runtime `NameError`. Mitigation: grep-driven, acceptance = 0 hit.
- **BREAKING**: ✅ v1 CLI signature đổi (`build_*_graph` thêm `config=`, `settings=`). Backward-compat KHÔNG yêu cầu (user xác nhận).

### P2 — Profile system (profile.md loader + persona override + `default` profile)

- **Goal**: parse `profile.md` → config object (P1's `ReportingConfig`+`Settings`) + persona string; persona override prompt layer; ship một `default` profile migrate y hệt hành vi v1.
- **Key changes**:
  - `src/profile/loader.py`: parse YAML frontmatter + Markdown body. Frontmatter → build `ReportingConfig`+`Settings`+budget/schedule. `token_env` → resolve từ `os.environ[name]` lúc spawn server (map vào `McpServerSpec.env`, dùng lại `required_env_keys` validation — `reporting_config.py:41`).
  - `src/profile/persona.py`: body string → inject vào lớp prompt (`src/llm/report_prompt.py` + `okr_/resource_` + `audience_external_prompts.py`). Body trống ⇒ prompt v1 nguyên vẹn (no-op).
  - `profiles/default/profile.md`: tái tạo `.env` v1 hiện tại (giá trị từ `config.example.env`).
- **Files touched**: new `src/profile/{loader,persona}.py`, `profiles/default/profile.md`; edit prompt modules để nhận persona param (5 prompt file).
- **Acceptance**:
  - Load `profiles/default/profile.md` → config bằng-byte với `.env` v1; chạy `cli report --daily` ra report **giống hệt** v1.
  - Persona body có nội dung → system prompt thực sự đổi (test: prompt chứa custom rule).
  - `token_env` resolve đúng; thiếu env → lỗi rõ ràng lúc spawn (không lúc load).
- **Risks**: persona override prompt có thể đè business-tone external (rò PII). Mitigation: persona **prepend** context, KHÔNG thay external-prompt sanitization (Lớp A privacy giữ — bài học Phase 5). Test: external report với persona vẫn zero key/PII.

### P3 — Registry + worker + per-agent isolation + per-agent gateway/budget/audit

- **Goal**: `registry.yaml` liệt kê agent; worker entrypoint load 1 profile, build graph + gateway + stores per-agent với data dir riêng; coordinating service spawn worker theo registry.
- **Key changes**:
  - `registry.yaml`: `agents: [{id, enabled}]` (đường dẫn = `profiles/<id>/profile.md`). Model = OpenClaw `openclaw.json` agents.list[].
  - `src/runtime/worker.py`: nhận `--agent-id`, load profile, build mọi store với path `.data/agents/<id>/{checkpoints.db,audit/,budget/,approvals.db,dedup.db}`, build per-agent `ActionGateway(settings, stores, external_channels)` từ profile.
  - `thread_id` = `"<agent_id>:<kind>:<date>"` (v1 hiện flat: `cli.py:35`="cli", `cron.py:72`="cron-{kind}-{audience}" — thêm prefix `agent_id`).
  - `src/runtime/service.py`: đọc registry, scheduler (đọc `schedule` frontmatter), spawn/giám sát worker. Pattern: OpenClaw registry + DeerFlow subagent executor (thread pool, per-thread state, timeout).
- **Files touched**: new `src/runtime/{worker,service}.py`, `registry.yaml`; reuse mọi store (đã nhận path từ P1).
- **Acceptance**:
  - 2 agent (acme-web + beta-app) chạy đồng thời, ghi vào 2 data dir riêng, audit/budget/dedup không lẫn.
  - Budget của agent A hit 100% **không** chặn agent B (budget per-agent).
  - Lớp B approval của A không xuất hiện trong queue của B (approval_store per-agent).
  - `thread_id` chứa agent_id → checkpoint của A và B không đụng.
- **Risks**:
  - **Resource cost**: 1 process/agent — N agent = N node subprocess spawn + N Python process (xem §9). Mitigation M1: worker on-demand/scheduled, không giữ N process thường trực.
  - Token isolation: 2 agent cùng project type cần 2 token khác nhau → `token_env` khác nhau per-profile (P2 đã lo).

### P4 — Multi-agent CLI (register / list / run)

- **Goal**: CLI quản lý nhiều agent thay cho CLI single-project v1.
- **Key changes**:
  - `mpm agent list` — đọc registry, in id/name/enabled/last-run.
  - `mpm agent register <id>` — scaffold `profiles/<id>/profile.md` từ template.
  - `mpm agent run <id> --report daily|weekly|okr|resource [--audience internal|external]` — chạy 1 report cho 1 agent qua worker.
  - `mpm agent approvals <id>` / `approve <id> <approval-id>` / `reject` — Lớp B per-agent (route tới approval_store của agent đó).
  - Giữ `audit` query nhưng thêm `--agent <id>`.
- **Files touched**: `src/entrypoints/cli.py` (rewrite dispatch quanh agent_id — **BREAKING** so với v1 CLI), reuse worker (P3).
- **Acceptance**: register 2 agent → list thấy cả 2 → run report từng cái → approvals/approve per-agent hoạt động end-to-end (DRY_RUN trước, rồi real write 1 agent).
- **Risks**: BREAKING CLI surface. Mitigation: `default` profile + `mpm agent run default ...` = đường tương đương v1 cho ai quen lệnh cũ.

**Exit M1**: nhiều agent / nhiều project, isolated hoàn toàn, chạy qua CLI/worker + scheduler. Guardrail per-agent. **Chưa có UI, chưa Postgres** — đó là M2.

## 6. Milestone M2 — Web UI + LangGraph upgrades

> Mục tiêu M2: web dashboard quản lý + 3 nâng cấp LangGraph (interrupt / streaming / Postgres+Store). Xây trên M1 đã chạy.

### P5 — Graph-native interrupts cho Lớp B (checkpoint-serialized)

- **Goal**: chuyển Lớp B approval từ gateway-queue sang **LangGraph interrupt** — graph pause tại node, UI hỏi, resume deterministic nhờ checkpoint.
- **Key changes**:
  - Hiện tại Lớp B **KHÔNG** phải graph interrupt: `action_gateway.py:193` gọi `needs_interrupt`, trả `pending_approval` + `approval_store` + `cli approve` (verified — graph không có `interrupt()`). P5 thêm node interrupt thật trong graph (LangGraph `interrupt()` + resume bằng `Command`).
  - Reference: DeerFlow `clarification_middleware.py` (interrupt qua `Command(goto=END)`) — adapt cho approve-to-execute.
  - Lớp A **không đổi** — vẫn hard-deny ở gateway trước LLM. Chỉ Lớp B chuyển sang interrupt.
- **Files touched**: graph builders (4) + gateway (Lớp B path) + một resume handler.
- **Acceptance**: external report → graph pause tại interrupt → state checkpoint → approve qua API → graph resume → Slack post live. Reject → graph dừng sạch, audited.
- **Risks**:
  - **Coexist vs replace** (open question §9): interrupt cần graph đang chạy để resume; approval async (người duyệt sau vài giờ) cần checkpoint bền + worker resume được. Mitigation: interrupt **augment** queue ở P5 (cả hai path tồn tại), quyết replace ở P8 khi Postgres checkpointer bền multi-process.
  - Resume xuyên process: cần checkpoint shared → phụ thuộc P8 Postgres cho production multi-machine. M2 sandbox: cùng worker resume từ SqliteSaver.

### P6 — Streaming + FastAPI service

- **Goal**: FastAPI backend; stream token/event của agent đang chạy ra UI qua SSE.
- **Key changes**:
  - `src/server/app.py` (FastAPI): routes `/api/agents`, `/api/agents/{id}/status`, `/api/agents/{id}/trigger`, `/api/agents/{id}/stream` (SSE).
  - LangGraph streaming (`graph.stream(...)` mode messages/events) → bridge sang SSE. Reference: DeerFlow `StreamBridge`/`thread_runs.py`.
- **Files touched**: new `src/server/{app,stream}.py`; reuse worker + registry.
- **Acceptance**: trigger report từ API → SSE phát event perceive→analyze→compose→deliver live; client thấy progress.
- **Risks**: SSE + worker process boundary — service phải đọc stream từ worker đang chạy (queue/pubsub nội bộ). Mitigation M2: service chạy graph in-process cho on-demand trigger (không qua subprocess) để stream trực tiếp; scheduled run vẫn qua worker.

### P7 — Web dashboard (HTMX hoặc Streamlit)

- **Goal**: dashboard surface mọi thứ ops cần.
- **Key changes** (surface):
  - Agent list + status (running/idle/error) — từ registry + worker heartbeat.
  - Cost vs budget per-agent — đọc `.data/agents/<id>/budget/`.
  - Recent audit — đọc per-agent audit JSONL (reuse `audit_log.query`).
  - **Pending Lớp B approvals — approve/reject ngay trên UI** (gọi P5 resume / approval_store).
  - Config view/edit — render frontmatter, save lại `profile.md` (validate trước khi ghi).
  - Trigger report on-demand — gọi `/api/agents/{id}/trigger`.
- **Files touched**: new `src/server/templates/` (HTMX) hoặc `src/server/dashboard.py` (Streamlit); reuse P6 API.
- **Acceptance**: từ UI thấy 2 agent, cost mỗi cái, approve 1 pending Lớp B → Slack post live, sửa 1 threshold → profile.md update → run kế tiếp dùng giá trị mới.
- **Risks**: HTMX vs Streamlit chưa chốt (§9). HTMX = nhẹ, server-rendered, hợp FastAPI; Streamlit = nhanh dựng nhưng state model riêng, khó nhúng SSE live. Mitigation: chọn theo P6 — nếu streaming live là must-have → HTMX + SSE; nếu chấp nhận poll → Streamlit nhanh hơn.

### P8 — Postgres checkpointer + Store (multi-process + cross-thread memory)

- **Goal**: thay SqliteSaver per-agent bằng Postgres checkpointer (state bền multi-process/multi-machine) + LangGraph Store (cross-thread memory per-agent).
- **Key changes**:
  - `src/agent/checkpoint.py`: thêm `CheckpointerType = sqlite|postgres` (config từ profile/env). Reference: DeerFlow `checkpointer_config.py` (memory|sqlite|postgres).
  - LangGraph Store namespace theo `agent_id` cho cross-thread memory (vd "nhớ quyết định sprint trước" xuyên report run). Reference: DeerFlow `runtime/store/provider.py`.
  - Resume interrupt (P5) qua Postgres → approval bền + worker bất kỳ resume được.
- **Files touched**: `checkpoint.py`, new `src/agent/store.py`, worker (chọn checkpointer theo profile).
- **Acceptance**: agent ghi memory ở report run 1, đọc lại ở run 2 (cross-thread). Worker restart → resume interrupt từ Postgres. SqliteSaver vẫn là default local (Postgres opt-in qua profile).
- **Risks**: **Postgres = infra dependency mới** (§9 — M1 hay M2?). Quyết: **M2-P8, opt-in**. SQLite đủ cho M1 (1 process/agent, không tranh chấp). Postgres chỉ cần khi multi-machine hoặc cross-thread memory thật sự dùng.

**Exit M2**: web dashboard quản lý N agent (status/cost/audit/approve/config/trigger), agent chạy live streaming, Lớp B qua graph interrupt, Postgres+Store opt-in cho scale.

## 7. What's PRESERVED from v1

- **Action Gateway guardrail** — Lớp A hard-deny (red line, trước LLM), allowlist-default-deny, Lớp B approve, audit immutable + secret redaction, budget cap, dedup reserve-before-execute. **Giữ nguyên logic, chỉ per-agent hóa** (path + config từ profile). `classify()` / `needs_interrupt()` không đổi.
- **Report graphs + analyzers** — `perceive→analyze→compose→deliver`; `risk_analyzer / okr_analyzer / resource_analyzer` (pure functions); audience-split internal/external + business-tone prompts. **Chỉ config-injected** (P1), logic không rewrite.
- **State primitive-only** — kỷ luật checkpointer-safe giữ nguyên (model nặng trong closure).
- **Test + journal discipline** — 269 test giữ + mở rộng; mỗi phase có exit criteria đo được; journal "Vấp & học được" tiếp tục.

## 8. Cross-cutting principles (giữ từ v1)

- Mỗi phase **chạy được + giá trị thật** trước phase sau (không big-bang).
- Không mở write authority mới khi guardrail chưa vững — v2 **không thêm** Lớp A/B action nào, chỉ per-agent hóa.
- Đo cost management cắt được (North Star PDR §3) — giờ per-agent.
- `default` profile = đường migrate an toàn từ v1.

## 9. Risks + open questions

1. **Secrets cho nhiều agent** — `token_env` (tên env var per-binding) là model P2. Đủ cho vài agent. **Open**: khi >10 agent, env var phình to → cần secret store (Vault/SOPS/`.env` per-agent)? Quyết khi P3 thấy số agent thực. v1 đã chấp nhận "Atlassian token pattern-undetectable" residual risk — model token vẫn ngoài profile, không đổi.
2. **Postgres — M1 hay M2?** Đề xuất **M2-P8, opt-in**. M1 dùng SqliteSaver per-agent (1 process/agent → không tranh chấp). Confirm: có use case multi-machine nào ở M1 không? Nếu không, hoãn Postgres là đúng (YAGNI).
3. **HTMX vs Streamlit** — chưa chốt (P7). HTMX nếu streaming live (P6 SSE) là must; Streamlit nếu dựng nhanh + chấp nhận poll. Quyết sau P6.
4. **Interrupt replace hay coexist với queue Lớp B?** P5 đề **augment** (cả hai), replace ở P8 khi Postgres bền resume xuyên process. Confirm: approval async (duyệt sau vài giờ) chấp nhận giữ graph paused + checkpoint, hay vẫn cần queue tách rời?
5. **Resource cost process-per-agent** — N agent = N Python process + N node MCP subprocess spawn/run. 5 agent OK; 50 agent cần worker pool / share. Quyết khi P3 đo RAM/process thật. Mitigation M1: worker on-demand/scheduled, không thường trực.
6. **Persona override an toàn** — body profile override prompt; phải KHÔNG đè được external-prompt sanitization (rò PII — bài học Phase 5). P2 acceptance test bắt buộc: external + persona vẫn zero key/PII.

---

> **Cook order**: M1 P1→P2→P3→P4 (mỗi cái chạy được), rồi M2 P5→P6→P7→P8. P1 BREAKING — cook trước hết. `default` profile (P2) là lưới an toàn migrate v1.
