# Codebase Summary — my-project-manager

> Bản đồ codebase, cập nhật khi code hình thành. Đọc để biết "cái gì ở đâu" nhanh.
> Status: **2026-07-01 — v3 M6 COMPLETE (hr-pack + generic seam patches).** 839 tests, ruff clean, pm-pack byte-identical pre-v3, HR output deterministic live.

## Trạng thái hiện tại (v2 COMPLETE: M1+M2+M3)

### M1: Multi-agent core (2026-06-24, 414 tests)
- **P1**: Config-injection refactor; 21 call sites parametrized, no more singletons.
- **P2**: Profile system (`profiles/<id>/` → 4 files + config + persona/project/memory injection).
- **P3**: Registry + per-agent worker + isolated stores + coordinating service (`registry.yaml`, worker subprocess per-agent, service daemon with croniter scheduler).
- **P4**: Multi-agent CLI (`mpm agent list/register/run/approvals/approve/reject/audit`); legacy `cli`/`cron` preserved.

### M2: Platform (2026-06-26, 545 tests)
- **P5**: LangGraph-native Lớp B interrupts (`approval_gate` node, pause/resume checkpoint flow).
- **P6**: FastAPI SSE streaming (localhost 4 routes: list/status/trigger/stream; live node-progress + terminal interrupt).
- **P7**: Web dashboard JSON API layer (5 GET endpoints: /api/{runs,cost,memory,automation,audit}/{id} + non-PII allowlist projection).
- **P8**: Postgres checkpointer + LangGraph Store + cross-thread agent memory (opt-in; SQLite default; MEMORY.md internal-only injection; Store namespace-scoped per-agent).
- **M4 (2026-06-28)**: React SPA replacing P7 HTMX (Vite+TypeScript, static assets committed to `src/server/static/app/`, served at `/`; ops JSON routes unchanged).

### M3: Extensibility (2026-06-27, 776 tests)
- **P10**: Skill system (5 bundled instruction-only skills, injectable LLM selector for internal-only prompt injection; red line: external gets no skills).
- **P9**: Cross-agent memory (sibling discovery + fact sharing via Store namespace `(sibling_id,"memory")`, RO-sibling/WO-self; injectable ranker; internal-only; red line: external gets nothing).
- **P11**: Integrations + multi-channel (config-driven extra MCP servers via `integrations:` block; Linear read + gated-write Lớp B; Email/SMTP delivery as new `email_send` action type, ALL email = Lớp B, internal-only; channel registry).
- **P12**: Automation + observability (opt-in LangSmith tracing B4, off=byte-identical; checkpoint-based replay B3 with safe-replay guard; READ-only workflow automation D3 via gateway, PROPOSE only, no auto-execute).

### M5: Domain-pack abstraction (2026-06-30, 816 tests)
- **S1-S6 slices**: Extract 3 coupling seams → generic core. PM becomes `domain-packs/pm-pack/` (graphs/tools/analyzers/allowlist/prompts/skills). PackRegistry loadable per domain. ToolProvider Protocol makes tool reads transport-agnostic. Config-driven allowlist stays pack-driven; Lớp A red line stays core-guarded. pm-pack output byte-identical pre-v3. Backward-compat: pre-v3 profiles default `domain: pm`.

### M6: Second domain (hr-pack) + generic seam patches (2026-07-01, 839 tests)
- **hr-pack lands**: Headcount report kind (count by employment status + department). Reads Confluence + Google Sheets via **gws CLI** (Google Workspace CLI, spawned like gh, independent auth). Writes via same Action Gateway (Lớp A/B unchanged). Config: HR_SHEET_ID / HR_SHEET_RANGE / HR_CONFLUENCE_PAGE_ID (env-only). Output PII-safe (aggregate counts, no employee names).
- **3 generic seam patches** (no domain logic; enable "git diff src/ = ∅" for future packs):
  - `discover_domains()` — filesystem-based pack discovery (domain-packs/<x>-pack/graphs.py marker), replaces hardcoded _KNOWN_DOMAINS.
  - `_ensure_pack_package()` — loads pack as importable domain_pack_<x> so pack modules can import siblings.
  - `all_report_kinds()` — kind validation unions all packs' kinds; failure-isolated per pack.

**Entry points**: Legacy `python -m src.entrypoints.cli`/`cron` (single-agent). Multi-agent: `python -m src.entrypoints.mpm agent {list,register,run,resume,replay,automate,approvals,approve,reject,audit}`. Runtime: `python -m src.runtime.worker`, `python -m src.runtime.service`.

## Cây thư mục (v3 M5 state with domain-packs)

```
src/
├── agent/        # LangGraph graph + nodes + state — LÕI (M1)
├── tools/        # *_read.py: generic models (Task/Event) used by packs
├── actions/      # action_gateway.py + approved_dispatch.py (WRITE, qua guardrail; handler lookup via pack)
├── llm/          # provider config + LLM builder logic (P2: accepts persona/project/memory params)
├── config/       # Settings + domain: field, ReportingConfig (P1); config_builders
├── profile/      # [M1-P2] Profile loader + context injection; [M5] parse domain: field
├── runtime/      # [M1-P3] Worker + service + registry + scheduler; [M5] worker dispatches via PackRegistry
├── audit/        # audit log (append-only)
├── server/       # [M2-P6] FastAPI + SSE + JSON API; [M4] React SPA (static/app/)
├── packs/        # [M5] PackRegistry loader + ToolProvider Protocol
├── automation/   # [M3-P12] Workflow automation engine + LangSmith tracing config
└── entrypoints/  # cli.py, cron.py (legacy); mpm.py (M1-P4: multi-agent)
                  # mpm_resume_cmd.py, mpm_replay_cmd.py, mpm_automate_cmd.py (M3)

domain-packs/    # [M5] Domain implementations (pluggable)
├── pm-pack/     # PM domain: graphs/tools/prompts/skills/allowlist
│   ├── pack.yaml             # manifest: id, report_kinds, required bindings
│   ├── graphs.py             # report_kind builders (daily/weekly/okr/resource)
│   ├── tools.py              # ToolProvider wrapping jira/github/confluence reads
│   ├── write_handlers.py     # allowlist + handler dispatch for slack/confluence
│   ├── models.py             # Issue↔Task mapping (lossless) + generic Task/Event
│   ├── prompts/              # 8 PM system prompts (dynamic-loaded)
│   └── skills/               # 5 bundled PM skills
└── hr-pack/     # [M6] HR domain: headcount reports via Google Sheets + Confluence
    ├── pack.yaml             # manifest: id, report_kinds (headcount)
    ├── graphs.py             # headcount report builder
    ├── tools.py              # ToolProvider: Confluence read + gws CLI (Google Sheets)
    ├── write_handlers.py     # allowlist (slack/confluence writes)
    ├── analyzers.py          # headcount analyzer (count/group_by)
    └── prompts/              # HR-specific system prompts

profiles/         # Agent configs (gitignored except default/)
├── default/      # v1 migration template (SOUL/PROJECT/MEMORY; profile.yaml; domain: pm implicit)
│   ├── profile.yaml
│   ├── SOUL.md
│   ├── PROJECT.md
│   └── MEMORY.md
└── .../<id>/     # Per-agent profile (same 4-file structure; domain: field optional)

registry.yaml     # [NEW P3] agents: [{id, enabled}]

.data/
└── agents/       # [NEW P3] Per-agent stores (were .data/ in v1)
    ├── default/  # Migrated v1 stores (single-agent compat)
    │   ├── checkpoints.db
    │   ├── audit/
    │   ├── budget/
    │   ├── approvals.db
    │   └── dedup.db
    └── <id>/     # Per-agent isolation
        └── (same structure)
```

## Bản đồ "tìm gì ở đâu"

| Cần tìm | Ở |
|---|---|
| **[M5] Domain pack load** | `src/packs/registry.py::PackRegistry.load(domain)` — importlib-load `domain-packs/<domain>-pack/` modules; return Pack object |
| **[M5] ToolProvider interface** | `src/packs/tool_provider.py::ToolProvider` Protocol — `read(name: str) -> list[Task/Event]`; transport-agnostic |
| **[M5] Pack allowlist** | `domain-packs/pm-pack/write_handlers.py` — contributes `ALLOWLIST` dict; loaded by `hard_block.py` (Lớp A red line stays core) |
| **[M5] Profile domain field** | `src/config/settings.py::Settings.domain` — defaults `"pm"` if absent (backward-compat); loaded by profile.py |
| **[M6] Discover packs (filesystem)** | `src/packs/registry.py::discover_domains()` — finds `domain-packs/<x>-pack/` folders with graphs.py marker (replaces hardcoded _KNOWN_DOMAINS) |
| **[M6] Pack package registration** | `src/packs/registry.py::_ensure_pack_package()` — loads domain-packs/<x>-pack/ as importable domain_pack_<x> (enables pack self-imports) |
| **[M6] Kind validation union** | `src/packs/registry.py::all_report_kinds()` — unions all packs' report_kinds for early typo detection; failure-isolated per pack |
| **[M6] HR gws adapter** | `domain-packs/hr-pack/tools.py::_gws_sheet_rows()` — spawns gws CLI (Google Workspace CLI), parses JSON, mirrors gh CLI pattern |
| **[M6] HR analyzer** | `domain-packs/hr-pack/analyzers.py` — headcount aggregator (count/group_by employment status + department) |
| **[NEW P2] Load profile** | `src/profile/loader.py::load_profile()` — parse `profiles/<id>/profile.yaml` + SOUL/PROJECT/MEMORY + domain field |
| **[NEW P2] Profile → config** | `src/profile/loader_mapping.py` — map profile.yaml fields to P1's Settings/ReportingConfig dicts + domain |
| **[NEW P2] Prompt injection** | `src/profile/context.py::ProfileContext` — persona (system msg), project+memory (user msg, internal only) |
| **[M5 UPDATE] Worker dispatch** | `src/runtime/worker.py::build_graph_for()` — calls `PackRegistry().load(domain).report_kinds[kind]` instead of if/elif |
| **[M5 UPDATE] Hard-block load** | `src/actions/hard_block.py` — `allowlist` loaded from pack; Lớp A red-line markers (`_DATA_LOSS_TOOL_MARKERS`, etc.) stay core-only |
| **[M5 UPDATE] Dispatch handlers** | `src/actions/approved_dispatch.py` — handler lookup via pack registry; write-handler dispatcher LOGIC stays core (slack/linear/email shared) |
| **[P2 UPDATE] CLI entry (legacy)** | `src/entrypoints/cli.py` — now accepts `--profile` (default `default`); calls `load_profile()` + passes config downstream |
| **[P2 UPDATE] Cron entry (legacy)** | `src/entrypoints/cron.py` — now accepts `--profile`; scheduler loads profile per agent-run |
| **[NEW P4] Multi-agent CLI** | `src/entrypoints/mpm.py` — dispatcher for `mpm agent {list,register,run,approvals,approve,reject,audit}` |
| **[NEW P4] Registry cmds** | `src/entrypoints/mpm_registry_cmds.py` — `run_list()`, `run_register()` |
| **[NEW P4] Run cmd** | `src/entrypoints/mpm_run_cmd.py` — `run_agent()` spawns worker subprocess |
| **[NEW P4] Manage cmds** | `src/entrypoints/mpm_manage_cmds.py` — `run_manage()` for approvals/approve/reject/audit per-agent |
| **[NEW P3] Worker entry** | `src/runtime/worker.py::main()` — CLI: `python -m src.runtime.worker --agent-id <id> --report <kind> [--audience] [--dry-run]` |
| **[NEW P3] Service entry** | `src/runtime/service.py::main()` — daemon: reads registry.yaml, spawns/supervises workers, respects schedule + timeout/cap |
| **[NEW P3] Registry** | `registry.yaml` + `src/runtime/registry.py::load_registry()` — list agents (id, enabled) |
| **[NEW P3] Per-agent paths** | `src/runtime/agent_paths.py` — `agent_data_dir(id)` = `.data/agents/<id>/`, `agent_thread_id(id, kind, audience)` = `<id>:<kind>:<audience>` |
| **[NEW P3] Per-agent isolation** | Each agent's stores (checkpoints, audit, budget, dedup, approvals) isolated under `.data/agents/<id>/`; `thread_id` contains agent_id for checkpoint safety |
| **[NEW P3] V1 migration** | `src/runtime/legacy_migration.py` — once-only idempotent move of v1 `.data/` → `.data/agents/default/` (triggered on first worker run) |
| **[NEW P3] Scheduler** | `src/runtime/scheduler.py` — pure croniter due-check; reads `schedule:` in profile.yaml; fires internal audience only |
| **[NEW P3] Run events** | `src/runtime/run_event.py` — B1 runs.jsonl per agent (one entry per worker run, records outcome) |
| Flow agent (graph) | `src/agent/report_graph.py` (perceive→analyze→compose→deliver) + injectable deps with config/settings |
| Cách đọc Jira | `src/tools/jira_read.py` — hoạt động qua pack ToolProvider (`pm-pack/tools.py`); adapter MCP ở `src/adapters/mcp_adapter.py` |
| Cách đọc GitHub | `src/tools/github_read.py` — hoạt động qua pack ToolProvider; adapter CLI `src/adapters/cli_adapter.py` |
| **[M5] Generic data model** | `src/tools/models.py::Task/Event` — cross-domain; `pm-pack/models.py::issue_to_task/task_to_issue` (lossless mapping) |
| Models (v2 PM-specific) | `src/tools/models.py::Issue, PullRequest, CiRun, Risk, Sprint` — PM-only; analyzers still consume Issue (byte-identical) |
| Risk phát hiện | `src/agent/risk_analyzer.py` (pure: overdue/blocker/stale_pr/ci_failure) |
| **[P1 UPDATE] Config reporting** | `src/config/reporting_config.py` + `src/config/settings.py` (no `@lru_cache` singletons; parametrized builders) |
| Cách agent ghi/post | `src/actions/action_gateway.py` (MỌI mutation; per-agent isolation in P3) |
| Post Slack | `src/actions/slack_write.py` (deliver_report + build_slack_short) |
| Tạo page Confluence | `src/actions/confluence_write.py` (create_report_page via gateway) |
| Guardrail allow/deny | `src/actions/hard_block.py` (allowlist + Lớp A/B + per-agent in P3) |
| Guardrail giải thích | `docs/v1/action-gateway-explainer.md` — safety model (giữ nguyên từ v1) |
| Lớp B duyệt người | `src/actions/approval_store.py` (queue SQLite) + gateway `approve/reject` |
| Dedup bền | `src/actions/dedup_store.py` (SQLite, reserve-before-execute) |
| Xem audit | `cli audit [--tool/--verdict/--since/--limit]` |
| Phát hiện/redact secret | `src/actions/secret_patterns.py` |
| Report prompt | `src/llm/report_prompt.py` (P2: accepts persona/project params) |
| OKR Confluence read | `src/tools/confluence_read.py` |
| OKR epic progress | `src/tools/okr_read.py` |
| OKR analyzer | `src/agent/okr_analyzer.py` |
| Resource analyzer | `src/agent/resource_analyzer.py` |

## Key v2 Changes vs v1

| Aspek | v1 | v2 M1-P3 |
|---|---|---|
| **Config source** | `.env` (singleton `get_settings()`) | `profiles/<id>/profile.yaml` (parametrized loader) |
| **Entry point (CLI)** | `cli report --daily` | `cli report --daily [--profile default]` |
| **Entry point (worker)** | N/A | `python -m src.runtime.worker --agent-id <id> --report <kind>` |
| **Entry point (service)** | Per-report launchd plists | `python -m src.runtime.service` (one daemon, reads registry) |
| **Token storage** | ENV values in `.env` | Profile refs ENV var NAME; token resolved at spawn |
| **Persona/project/memory** | Hardcoded prompts | Profile SOUL/PROJECT/MEMORY files → injected at prompt time |
| **External report** | PII scrub at prompt time | Same (persona/project/memory NOT injected to external path — safety preserved) |
| **Data isolation** | All data in `.data/` | Per-agent under `.data/agents/<id>/` (v1 `.data/` migrated to `.data/agents/default/` once) |
| **Multi-agent** | Single agent hardcoded | Multiple agents via registry.yaml (enabled/disabled) |
| **Default profile** | N/A | `profiles/default/` = v1 replica (empty MD, yaml from config.example.env) |
| **Thread safety** | `thread_id` = kind + audience | `thread_id` = agent_id + kind + audience (checkpoint isolation) |

## Testing

- **Unit tests**: `uv run pytest` — 816 tests pass (M1-P1..P4 + M2-P5..P8 + M3-P10/P9/P11/P12 + M5 pack/dispatch/red-line coverage).
- **Linting**: `uv run ruff check src tests` — clean.
- **Byte-identity**: pm-pack output (report text, Slack mrkdwn, Confluence XHTML) diff vs pre-v3 = empty (2026-06-30).
- **E2E Red-line suite** (M5 verified live, 2026-06-30): pack allowlist loaded; Lớp A hard-deny refuses destructive unplugged tools; default-DENY preserves invariant. `default` profile (no domain field) routes to pm-pack; M1-style e2e (Jira read, Confluence create, Slack post) re-runs without code change.

## Next Phase

**M7 (admin-pack):** Third domain to validate "git diff src/ = ∅" gate (M6 seam patches should suffice). Candidate: billing/cost-center reports via API integrations.

## Deferred

- **Live-key integration E2E:** Linear/SMTP/LangSmith with real credentials (skipped M3/M5; scheduled separately).
- **Advanced workflow:** Boolean `when` conditions, schedule-triggered automation (deferred D3 expansion).
- **Replay re-fetch:** Safe re-fetch in replay (currently frozen-state safe-replay guard; future: selective re-fetch with audit).
