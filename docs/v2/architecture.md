# v2 — Architecture (target) + What's preserved from v1

> Quay lại [README](README.md) · liên quan: [profile-design](profile-design.md) · [roadmap-m1](roadmap-m1.md) · [roadmap-m2](roadmap-m2.md).

## 4. Architecture (target)

```
                         profiles/                          registry.yaml
              ┌─ acme-web/  {profile.yaml, SOUL.md,  ─┐   ┌─ agents:
              │             PROJECT.md, MEMORY.md}     │◀──│   - id: acme-web  enabled: true
              ├─ beta-app/  {…4 file…}                 ┤   │   - id: beta-app  enabled: true ┘
              └─ ...                                   ┘
                                                              │ đọc
                                            ┌─────────────────▼──────────────────┐
                                            │  Coordinating service               │
                                            │  - đọc registry, load mỗi profile   │
                                            │  - spawn 1 worker / agent enabled    │
                                            │  - scheduler (đọc schedule/profile.yaml)│
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
   │  Web dashboard (React SPA, Vite+TS over JSON APIs, M4)                 │
   │  Client-side rendering from committed Vite build; reads JSON API       │
   │  - agent timeline/runs  - cost vs budget chart  - memory/automation   │
   │  - guardrail verdict + audit table · pending Lớp B approvals UI       │
   │  - approve/reject on-UI (same gateway-routed path as CLI)             │
   │  - config view/edit · trigger on-demand · streaming live run (SSE)    │
   └──────────────────────────────────────────────────────────────────────┘
```

## 5. Persistence: Checkpointer + Store (M2-P8)

**Checkpointer** (LangGraph state durability):
- **Default**: `SqliteSaver` per-agent (1 `.db` file / agent — simple, no infra, works within-process).
- **Opt-in via profile**: `PostgresCheckpointer` via `profile.yaml` `runtime: { checkpointer_type: postgres, postgres_dsn: "..." }` or env `CHECKPOINTER_TYPE=postgres` + `POSTGRES_DSN`. Opens raw psycopg connection at process start (lifetime-scoped).
- **Selection**: `get_checkpointer(settings)` → right class chosen based on config; no-dsn → `ValueError`.
- **Deps for Postgres path**: `langgraph-checkpoint-postgres` + `psycopg[binary]`.

**Store** (cross-thread memory):
- **Default**: `InMemoryStore` (per-run, not persisted).
- **Opt-in via profile**: `PostgresStore` via same `postgres_dsn`.
- **Namespace**: per `agent_id`, so memory is isolated between agents.
- **Selection**: `get_store(settings)` → wired into all 4 builders' `compile(store=...)`.

**Agent Memory (M2-P8, internal-only)**:
- After an `INTERNAL` delivery (audience="internal"), LLM extractor pulls salient facts.
- Facts written to Store (deduped by content-hash) AND mirrored to `MEMORY.md`'s agent-managed section (`<!-- AGENT-MEMORY:START/END -->`; human edits preserved).
- Reads back via P2 internal-only `MEMORY.md` injection on next run.
- **Guardrail**: NOT gated by Action Gateway (memory is internal state, not an external mutation); NOT in external reports.

Vị trí Postgres/Store: **M1 vẫn dùng SqliteSaver per-agent** (1 file / agent — đủ vì mỗi worker 1 process, không tranh chấp). **M2-P8** giới thiệu Postgres khi cần multi-machine hoặc cross-thread memory thật sự dùng. Store sống cạnh checkpointer, namespace theo `agent_id`. Agent memory là internal state: mỗi agent tự ghi vào Store + MEMORY.md, không qua gateway.

**FastAPI service (M2-P6)** — thêm một localhost-only backend (`src/server/app.py`) phục vụ on-demand trigger + SSE streaming cho dashboard. Service này chạy graph in-process (không qua worker subprocess), stream live node events, và enforce PII firewall. Scheduled runs vẫn qua worker/scheduler (M1) — service là *augment*, không thay thế.


## 6. Integrations + multi-channel delivery (M3-P11)

**Config-driven extra MCP servers (C3)**:
- `ReportingConfig.extra_servers: dict[str, McpServerSpec]` lets `profile.yaml` `integrations:` block declare optional stdio MCP servers (name + mcp_dist + required_env NAMES; values from `os.environ`, never in YAML). **Concrete example**: Linear via community stdio MCP (`@tacticlaunch/mcp-linear`, `node dist/index.js`; note: official Linear MCP is HTTP/SSE remote-only, incompatible with stdio-spawn).
- Linear READ tools (`src/tools/linear_read.py`: `linear_getIssues`, `linear_searchIssues`, `linear_getProjects`) bypass Action Gateway like `jira_read`.
- Linear gated WRITE: only `linear_createComment` allowlisted in `hard_block._MCP_ALLOWLIST["linear"]`, classified Lớp B (queued for approval) + destructive tools (`linear_delete*`/`linear_archive*`) hit Lớp A red line via `_DATA_LOSS_TOOL_MARKERS`. Dispatch via `linear_write.py` + `linear` branch in `approved_dispatch.dispatch_approved_action`.

**Multi-channel delivery: Email/SMTP (D2)**:
- New `ActionGateway` mutation type `email_send` (added to `_MUTATING_TYPES`) routes all outbound email through gateway (dry-run/kill-switch/dedup/audit + Lớp A/B apply). Never a side path.
- ALL email = **Lớp B** (locked policy): `needs_interrupt` returns True; real send only via approved dispatch. `_hard_deny_email` (Lớp A) scans recipient/subject/body for secrets, rejects empty recipient or body.
- `SmtpConfig` (`src/config/smtp_config.py`): host/user/from_addr/port=587/use_tls/recipients. Password is ENV-ONLY (`SMTP_PASSWORD` at send-time), never a config field. `src/actions/email_write.py` + `email_send` branch in `approved_dispatch`.
- **Channel registry** (`src/agent/channel_registry.py`): `resolve_channels(config)` returns extra channels (email when SMTP configured; `()` otherwise). `deliver_extra_channels` is gateway-routed; channel failure logged+skipped, never breaks core Slack+Confluence. Misconfigured SMTP (host set, no recipients) **FAILS LOUD** at config-build.
- Wired into all 3 report graphs uniformly via `audience_delivery.deliver_extra_channels_and_summarize`. **Internal-only red line**: email skipped when `audience="external"` (email body is full report detail incl. per-assignee names/costs; external reports withhold that — same red line as resource graph's external link-stripping).

**Unchanged invariant (restate)**: Every new write (Linear comment, email) stays behind Action Gateway — Lớp A hard-deny + default-DENY allowlist + Lớp B approve. New write tools deny by default until explicitly allowlisted. Config flows through all 3 entry points (worker/cron/cli) automatically. Backward-compat: no `integrations:` + no `smtp:` ⇒ byte-identical pre-P11 behavior (Slack+Confluence only). `classify()` / `needs_interrupt()` unchanged.

## 7. What's PRESERVED from v1

- **Action Gateway guardrail** — Lớp A hard-deny (red line, trước LLM), allowlist-default-deny, Lớp B approve, audit immutable + secret redaction, budget cap, dedup reserve-before-execute. **Giữ nguyên logic, chỉ per-agent hóa** (path + config từ profile). `classify()` / `needs_interrupt()` không đổi.
- **Report graphs + analyzers** — `perceive→analyze→compose→deliver`; `risk_analyzer / okr_analyzer / resource_analyzer` (pure functions); audience-split internal/external + business-tone prompts. **Chỉ config-injected** (P1), logic không rewrite.
- **State primitive-only** — kỷ luật checkpointer-safe giữ nguyên (model nặng trong closure).
- **Test + journal discipline** — 269 test giữ + mở rộng; mỗi phase có exit criteria đo được; journal "Vấp & học được" tiếp tục.

## 8. Automation + observability (M3-P12)

**B4 — LangSmith tracing opt-in**:
- `invoke_config(thread_id, settings)` at the graph invoke seam (worker/cron/server paths) attaches an optional `LangChainTracer` callbacks list. **DEFAULT OFF** ⇒ no `callbacks` key, byte-identical pre-P12 behavior. Gated by BOTH profile flag (`runtime.tracing: true` → `Settings.tracing`) AND env signal (`LANGCHAIN_TRACING_V2` or `LANGSMITH_API_KEY`). Shared env check `tracing_env_on()` ensures worker/cli (Settings path) + server (`invoke_config_env`, env-only) agree.
- Tracer failure degrades gracefully (untraced run, never breaks execution); lazy import keeps OFF path langsmith-free. **Observability-only** — no Action Gateway interaction, never touches guardrail logic or write authority.

**B3 — Run replay / time-travel**:
- `src/runtime/replay.py`: `mpm agent replay <id> <thread> [--checkpoint <id>]`. Without `--checkpoint`, LISTS checkpoint history (structural summary only, no PII); each row flagged `[replayable]`/`[needs-earlier-data]`. With `--checkpoint`, REPLAYS from the saved checkpoint using FROZEN stored state (graph.invoke with checkpoint-pinned config) — NO re-fetch of live Jira/GitHub.
- **Safe-replay guard**: only checkpoints pending `deliver` or `approval_gate` nodes (or terminal) are replayable; earlier nodes (perceive/analyze/compose) are REFUSED — they rebuild fetched-data closure boxes that are not checkpointed, so replay would degenerate. Time-travel state edits and re-fetch toggles deferred.
- Replay re-runs the existing graph — any write re-enters the same gateway Lớp A/B + dedup chain. No replay bypass.

**D3 — Workflow automation (READ-ONLY + PROPOSE)**:
- `src/automation/` package (schema/prompts/propose/engine): `mpm agent automate <id> <automation.yaml> [--dry-run]`. Flat YAML with 3 step types (`read`/`analyze`/`propose`); single `when: field == value` condition; named-prompt `analyze` only (no free-text in YAML).
- Engine chains WHITELISTED reads (jira.issues/github.prs/linear.issues/confluence.page — bypass gateway by design), runs `analyze` via agent LLM (named prompts from `src/automation/prompts.py`), builds action dict for each `propose` (whitelist: slack.post/linear.comment).
- Routes proposals through `ActionGateway.execute()` WITHOUT a handler ⇒ Lớp B action ENQUEUES (`pending_approval`), non-Lớp-B no-ops (`skipped`). **NEVER auto-executes** a write; never calls `execute_approved`/`approve`. `--dry-run` builds+prints each proposal without touching the gateway.
- Fail-closed schema (unknown step/tool/target/prompt → parse error; `when` is single `==`, no boolean ops). Example: `docs/v2/examples/automation-blocker-stakeholder-note.yaml`.

**THE INVARIANT (unchanged by all of P12)**:
- D3 proposes through the gateway (Lớp B, never auto-execute); B3 replay re-runs gateway-routed graphs (no bypass); B4 tracing is observability-only (no action path).
- The Action-Gateway red line — Lớp A hard-deny + allowlist default-DENY + Lớp B approve, `classify()`/`needs_interrupt()` unchanged — is **untouched**.
- Backward-compat: tracing OFF + no automation invoked ⇒ byte-identical pre-P12.

## 9. Cross-cutting principles (giữ từ v1, unchanged by M3-P12)

- Mỗi phase **chạy được + giá trị thật** trước phase sau (không big-bang).
- Không mở write authority mới khi guardrail chưa vững — v2 **không thêm** Lớp A/B action nào, chỉ per-agent hóa.
- Đo cost management cắt được (North Star PDR §3) — giờ per-agent.
- `default` profile = đường migrate an toàn từ v1.

## 10. Harness conformance (đây là một harness đầy đủ, không chỉ skills + tools)

"Harness" (dây cương) = toàn bộ môi trường quanh model giúp agent đi đúng hướng và làm
việc giỏi hơn. Một harness thực sự bắt buộc có **security gate + guardrails + observability**,
không chỉ gắn tools/skills. `my-project-manager` xây đủ cả tầng đó cho PM-agent của nó —
mỗi node dưới đây là cơ chế có thật trong `src/`, đã verify live (E2E 2026-06-27):

| Harness node | Cơ chế trong sản phẩm | File |
|---|---|---|
| **Scheduler** (cron / heartbeat) | service daemon đọc `schedule:` (croniter, cap 4, timeout 600s) + cron entrypoint | `runtime/scheduler.py`, `runtime/service.py`, `entrypoints/cron.py` |
| **Memory** (working / internal / external / long-term) | extractor→Store + `MEMORY.md` mirror (internal) + cross-agent sibling + Postgres Store | `agent/memory_node.py`, `agent/memory_mirror.py`, `agent/sibling_memory.py`, `agent/store.py` |
| **Provider / Model** | OpenRouter client + budget gating + cost accounting | `llm/client.py`, `llm/budget_tracker.py`, `llm/cost.py` |
| **Tools** (built-in / MCP / CLI) | stdio MCP adapter + `gh` CLI adapter + read tools (Jira/GitHub/Confluence/Linear/OKR) | `adapters/mcp_adapter.py`, `adapters/cli_adapter.py`, `tools/*_read.py` |
| **Skills** | 5 bundled instruction-only skills + injectable LLM selector (internal-only inject) | `skills/*.md`, `src/skills/skill_selector.py` |
| **Hooks** | PII firewall (`summarize_node`) + `approval_gate` interrupt node trên graph | `server/sse_events.py`, `agent/approval_gate.py` |
| **Security gate** | **Action Gateway** — cửa DUY NHẤT, BẮT BUỘC cho mọi mutation (no module writes directly) | `actions/action_gateway.py` |
| **Guardrails → Blocks** | Lớp A hard-deny: `DATA_LOSS` / `CREDENTIAL` / `SECURITY` / `NOT_ALLOWLISTED` (default-DENY allowlist) | `actions/hard_block.py`, `actions/secret_patterns.py` |
| **Guardrails → Filters** | Lớp B approve-interrupt + secret redaction + dedup (reserve-before-execute) + rate-limit (10/60s) + kill-switch + dry-run | `actions/action_gateway.py`, `actions/dedup_store.py`, `actions/approval_store.py` |
| **Observability → Logs** | audit JSONL **immutable** (no-audit ⇒ no-write) + structured run-event log per run | `audit/audit_log.py`, `runtime/run_event.py` |
| **Observability → Traces** | LangSmith tracing opt-in (B4) + run replay / time-travel (B3) | `runtime/run_config.py`, `runtime/replay.py` |
| **Observability → Analytics** | budget/cost-token tracker + JSON API (reads) + React SPA views (M4) | `llm/budget_tracker.py`, `server/routes_visualize.py`, `web/` |

**Điểm vượt mức tối thiểu:** guardrail không phải bolt-on mà là **bất biến kiến trúc** — mọi
write authority (kể cả các action mới M3: Linear comment, email, workflow proposal) đều
nằm sau cùng một Action Gateway; `classify()`/`needs_interrupt()` không đổi qua suốt v2.
Verify live: external post bị chặn chờ duyệt, D3 workflow chỉ propose (không tự execute),
secret bị Lớp A deny. Đây là "harness engineering" đúng nghĩa — model bị đeo cương để đi
đúng hướng, autonomous về tốc độ nhưng không bao giờ về accountability.

**Khác biệt backend so với sơ đồ harness phổ biến:** external/long-term memory dùng
Confluence + `MEMORY.md` + Postgres Store (thay cho Notion/Obsidian) — cùng vai trò, khác
backend. Không node nào của định nghĩa harness bị thiếu.

## 11. React Dashboard (M4) — UI-only observability layer

**M4 ships a Vite + TypeScript React SPA** replacing the M2-P7 HTMX server-rendered dashboard. Built as static assets committed to `src/server/static/app/`, served at `/` by FastAPI's catch-all (zero extra process, zero Node.js at serve time). **The invariant holds**: M4 is a window only.

- **New JSON API layer** (`src/server/routes_visualize.py`): 5 read-only endpoints (`/api/{runs,cost,memory,automation,audit}/{id}`) each projecting to a non-PII allowlist mirroring `summarize_node`. Memory internal-only (external → no facts; `?audience` gated). No guardrail change.
- **Ops JSON routes** (`src/server/routes_ops_json.py`): approve/reject/config reads calling the identical `gw.approve(handler=dispatch_approved_action)` / `profile_editor` functions; shared `ops_helpers.py` extracted from CLI dispatcher.
- **React surfaces**: Timeline, Cost (react-chartjs-2), Guardrail (verdict + audit), Memory (internal), Automation (internal). Read-only; approvals trigger via the existing gateway-routed endpoint (no new write authority).
- **What's deleted**: `routes_dashboard.py`, `routes_approvals.py`, `routes_audit.py`, `routes_profile.py` (HTML routers), `src/server/templates/`, htmx static + 5 htmx tests. Coverage guard: every unique edge-case re-asserted in a JSON test first.
- **M4 is shipped**: 5 slices (S1 JSON API, S2 React shell, S3 visual views, S4 ops surfaces, S5 wiring), 785 pytest green, vitest 11, ruff clean.

## 12. Domain-pack abstraction (v3 M5 + M6)

**v3 M5 (2026-06-30, 816 tests) extracts PM into pluggable `domain-packs/pm-pack/`, leaving core generic.** PM runs byte-identical to pre-v3. Three coupling seams unplugged:

**1. Report-kind dispatch:**
- **Old**: `worker.py` if/elif kind → graph builder (hardcoded daily/weekly/okr/resource).
- **New**: `PackRegistry().load(domain).report_kinds[kind]` routes via pack registry. `pm-pack/graphs.py` registers 4 builders. **M6 hr-pack registers own kinds** (e.g., `headcount`) without lõi changes.

**2. Tool providers:**
- **Old**: graph builders import `jira_read`, `github_read` directly; transport baked in.
- **New**: graph accepts `tools: ToolProvider` (Protocol in `src/packs/tool_provider.py`). PM ToolProvider wraps jira/github/confluence reads. **M6 plugs Google Sheets via gws CLI adapter** (HTTP spawned process, mirrors gh CLI pattern — not stdio MCP).

**3. Config-driven allowlist + handlers:**
- **Old**: `hard_block._MCP_ALLOWLIST` + `approved_dispatch.dispatch_approved_action` hardcode PM tool whitelist + handler branches (if/elif server).
- **New**: `pm-pack/write_handlers.py` contributes `ALLOWLIST` dict + handler map. Core `classify()` / `needs_interrupt()` unchanged. **RED-LINE INVARIANT HELD**: Lớp A markers (DATA_LOSS/CREDENTIAL/SECURITY) stay in `src/actions/hard_block.py` — pack cannot override red line, only *add* permitted tools (default-DENY preserved).

**M6 seam patches (v3 M6, 2026-07-01, 839 tests):** HR-pack landing proved M5 abstraction but surfaced 3 generic core seams initially missed. One-time fixes, no domain logic:
- `src/packs/registry.py::discover_domains()` — pack discovery from filesystem (`domain-packs/<x>-pack/graphs.py` marker), replacing hardcoded `_KNOWN_DOMAINS`. Adding a pack folder now requires zero core edits.
- `src/packs/registry.py::_ensure_pack_package()` — loads each pack as importable `domain_pack_<x>` so a pack's modules can import siblings (PM never needed this; HR does).
- `src/packs/registry.py::all_report_kinds()` — kind validation now unions all packs' kinds instead of hardcoded PM set. Failure-isolated: one broken pack doesn't block validation for all.

**Backward-compatibility:** Pre-v3 profiles omit `domain:` field → default `"pm"` → auto-load pm-pack. Byte-identical behavior.

**Pack structure** (`domain-packs/{pm,hr}-pack/`):
```
{pm,hr}-pack/
├── pack.yaml             # manifest: id, report_kinds, required bindings
├── graphs.py             # report_kind builders (PACK_MARKER: proves valid pack)
├── tools.py              # ToolProvider (transport-specific adapters)
├── write_handlers.py     # allowlist + dispatcher handlers (if domain writes)
├── analyzers.py          # domain-specific metric analyzers (optional)
├── models.py             # domain model (optional; PM: Issue↔Task mapping)
├── prompts/              # system prompts (dynamic-loaded)
└── skills/               # bundled instruction-only skills (optional)
```
**M6 HR-pack specifics:**
- **Headcount report kind**: `count/group_by(employment_status, department)` on Google Sheet rows.
- **Tools**: Confluence table (reused `src.tools.confluence_read`) + Google Sheets via **gws CLI** (`gws sheets spreadsheets values get ...`, Google Workspace CLI auth independent of core).
- **Config**: HR_SHEET_ID / HR_SHEET_RANGE / HR_CONFLUENCE_PAGE_ID (env-only; pack reads own env).
- **Analyzer**: headcount aggregations (pure Task→count logic).
- **Allowlist**: HR writes (Slack+Confluence) via same Action Gateway; same Lớp A/B apply.
- **PII safety**: output is aggregate counts, never employee names rendered (design-verified).

**Analyzers** (`src/agent/`): `risk_analyzer.py`, `okr_analyzer.py`, `resource_analyzer.py` stay core. Pure functions; no domain coupling. Packs write own (PM on `Issue`, HR on `Task`).

**Core modules** (`src/packs/`):
- `registry.py`: `PackRegistry` (importlib-load, discover_domains, all_report_kinds, _ensure_pack_package).
- `tool_provider.py`: `ToolProvider` Protocol — `read(name: str)` returns list of `Task`/`Event`.

**Files modified** (M5 + M6 patches):
- `src/profile/loader.py`: parse `domain:` field (default `"pm"`).
- `src/config/settings.py`: `Settings.domain` field.
- `src/runtime/worker.py`: call `PackRegistry().load(settings.domain)` for kind dispatch.
- `src/actions/hard_block.py`: load allowlist from pack; verify Lớp A not overridable.
- `src/actions/approved_dispatch.py`: handler lookup via pack.
- `src/entrypoints/mpm_run_cmd.py`, `src/server/routes_runs.py`: kind validation via `all_report_kinds()` (union across packs, failure-isolated).

**Tested invariants:**
- Red-line suite green (hard_block tests verify Lớp A not loosened).
- `git diff src/ = ∅` when adding a domain (M5 design + M6 patches enable this).
- PM output byte-identical to pre-v3; HR output deterministic (live E2E: 10 people → 10 total, 7 Active, 4 Engineering, Slack+Confluence posted).
- Replay + automation routed through pack allowlist (no bypass).
