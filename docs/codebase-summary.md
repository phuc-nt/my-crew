# Codebase Summary — my-project-manager

> Bản đồ codebase, cập nhật khi code hình thành. Đọc để biết "cái gì ở đâu" nhanh.
> Status: **2026-06-27 — v2 COMPLETE (M1+M2+M3).** 776 tests, ruff clean, final live E2E verified.

## Trạng thái hiện tại (v2 COMPLETE: M1+M2+M3)

### M1: Multi-agent core (2026-06-24, 414 tests)
- **P1**: Config-injection refactor; 21 call sites parametrized, no more singletons.
- **P2**: Profile system (`profiles/<id>/` → 4 files + config + persona/project/memory injection).
- **P3**: Registry + per-agent worker + isolated stores + coordinating service (`registry.yaml`, worker subprocess per-agent, service daemon with croniter scheduler).
- **P4**: Multi-agent CLI (`mpm agent list/register/run/approvals/approve/reject/audit`); legacy `cli`/`cron` preserved.

### M2: Platform (2026-06-26, 545 tests)
- **P5**: LangGraph-native Lớp B interrupts (`approval_gate` node, pause/resume checkpoint flow).
- **P6**: FastAPI SSE streaming (localhost 4 routes: list/status/trigger/stream; live node-progress + terminal interrupt).
- **P7**: Web dashboard (HTMX+Jinja2, 6 surfaces: agent list/cost, on-UI approve/reject, audit, config view/edit with atomic replace, trigger+SSE).
- **P8**: Postgres checkpointer + LangGraph Store + cross-thread agent memory (opt-in; SQLite default; MEMORY.md internal-only injection; Store namespace-scoped per-agent).

### M3: Extensibility (2026-06-27, 776 tests)
- **P10**: Skill system (5 bundled instruction-only skills, injectable LLM selector for internal-only prompt injection; red line: external gets no skills).
- **P9**: Cross-agent memory (sibling discovery + fact sharing via Store namespace `(sibling_id,"memory")`, RO-sibling/WO-self; injectable ranker; internal-only; red line: external gets nothing).
- **P11**: Integrations + multi-channel (config-driven extra MCP servers via `integrations:` block; Linear read + gated-write Lớp B; Email/SMTP delivery as new `email_send` action type, ALL email = Lớp B, internal-only; channel registry).
- **P12**: Automation + observability (opt-in LangSmith tracing B4, off=byte-identical; checkpoint-based replay B3 with safe-replay guard; READ-only workflow automation D3 via gateway, PROPOSE only, no auto-execute).

**Entry points**: Legacy `python -m src.entrypoints.cli`/`cron` (single-agent). Multi-agent: `python -m src.entrypoints.mpm agent {list,register,run,resume,replay,automate,approvals,approve,reject,audit}`. Runtime: `python -m src.runtime.worker`, `python -m src.runtime.service`.

## Cây thư mục (v2 complete state)

```
src/
├── agent/        # LangGraph graph + nodes + state — LÕI (M1)
├── tools/        # *_read.py: jira/github/slack/confluence (READ)
├── actions/      # action_gateway.py + *_write.py (WRITE, qua guardrail)
├── llm/          # provider config + prompts (P2: accepts persona/project/memory params)
├── config/       # Settings, ReportingConfig (P1: no singletons); config_builders
├── profile/      # [M1-P2] Profile loader + context injection
├── runtime/      # [M1-P3] Worker + service + registry + scheduler
├── audit/        # audit log (append-only)
├── server/       # [M2-P6] FastAPI + SSE + HTMX dashboard (P7)
├── skills/       # [M3-P10] Bundled instruction-only skill library + loader
├── automation/   # [M3-P12] Workflow automation engine + LangSmith tracing config
└── entrypoints/  # cli.py, cron.py (legacy); mpm.py (M1-P4: multi-agent)
                  # mpm_resume_cmd.py, mpm_replay_cmd.py, mpm_automate_cmd.py (M3)

profiles/         # Agent configs (gitignored except default/)
├── default/      # v1 migration template (empty SOUL/PROJECT/MEMORY; profile.yaml)
│   ├── profile.yaml
│   ├── SOUL.md
│   ├── PROJECT.md
│   └── MEMORY.md
└── .../<id>/     # Per-agent profile (same 4-file structure)

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
| **[NEW P2] Load profile** | `src/profile/loader.py::load_profile()` — parse `profiles/<id>/profile.yaml` + SOUL/PROJECT/MEMORY |
| **[NEW P2] Profile → config** | `src/profile/loader_mapping.py` — map profile.yaml fields to P1's Settings/ReportingConfig dicts |
| **[NEW P2] Prompt injection** | `src/profile/context.py::ProfileContext` — persona (system msg), project+memory (user msg, internal only) |
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
| Cách đọc Jira | `src/tools/jira_read.py` (get_open_issues, parse_issue); adapter MCP ở `src/adapters/mcp_adapter.py` |
| Cách đọc GitHub | `src/tools/github_read.py` (get_open_prs, get_recent_ci); adapter CLI `src/adapters/cli_adapter.py` |
| Models | `src/tools/models.py` (Issue, PullRequest, CiRun, Risk, Sprint) |
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

- **Unit tests**: `uv run pytest` — 776 tests pass (M1-P1..P4 + M2-P5..P8 + M3-P10/P9/P11/P12 coverage).
- **Linting**: `uv run ruff check src tests` — clean.
- **E2E**: Final live (2026-06-27): Jira 21 issues read, real Confluence page created (id 2064385), Slack post approved live (ts 1782532805), Postgres checkpointer+store verified, 20 facts stored, B3 replay (dedup, refuse unsafe), D3 automation proposals (Lớp B only). Red lines verified: Action Gateway on every write, external channel Lớp B, replay/automation via gateway, all memory internal-only.

## Deferred (future phases)

- **Live-key integration E2E:** Linear/SMTP/LangSmith with real credentials (skipped M3; scheduled separately).
- **Advanced workflow:** Boolean `when` conditions, schedule-triggered automation (deferred D3 expansion).
- **Replay re-fetch:** Safe re-fetch in replay (currently frozen-state safe-replay guard; future: selective re-fetch with audit).
