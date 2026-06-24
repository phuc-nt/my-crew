# Codebase Summary — my-project-manager

> Bản đồ codebase, cập nhật khi code hình thành. Đọc để biết "cái gì ở đâu" nhanh.
> Status: **2026-06-24 — v2 M1-P1 + P2 + P3 + P4 COMPLETE.** Multi-agent core (config injection + profile-based load + registry + per-agent worker + isolated stores) + multi-agent CLI (list/register/run/manage). 414 tests, ruff clean.

## Trạng thái hiện tại (v2 M1-P4 COMPLETE)

- **v2 M1-P1 DONE**: Config-injection refactor; 21 call sites parametrized, no more singletons.
- **v2 M1-P2 DONE**: Profile system (`profiles/<id>/` → 4 files + config + persona/project/memory injection).
  - `cli report --daily [--profile default]` loads config from profile, not `.env` directly.
  - `profiles/default/` ships v1-equivalent behavior (empty SOUL/PROJECT/MEMORY, profile.yaml from config.example.env).
- **v2 M1-P3 DONE**: Registry + per-agent worker + isolated stores + coordinating service.
  - `registry.yaml` lists agents (id, enabled).
  - `python -m src.runtime.worker --agent-id <id> --report <kind>` loads profile, builds isolated stores at `.data/agents/<id>/`, runs report.
  - `python -m src.runtime.service` reads registry, spawns workers on schedule (croniter), supervises with 600s timeout + concurrency cap 4.
  - Per-agent stores (audit, budget, approvals, dedup, checkpoints) under `.data/agents/<id>/` — no cross-agent pollution.
  - `thread_id` now `<agent_id>:<kind>:<audience>` for cross-agent checkpoint isolation.
- **v2 M1-P4 DONE**: Multi-agent CLI (dispatch + registry mgmt + worker spawn + per-agent Lớp B management).
  - `python -m src.entrypoints.mpm agent list` — list agents (id/name/enabled/last-run).
  - `python -m src.entrypoints.mpm agent register <id>` — scaffold `profiles/<id>/` (4-file template).
  - `python -m src.entrypoints.mpm agent run <id> --report <kind> [--audience] [--dry-run]` — spawn worker subprocess, wait, print exit code.
  - `python -m src.entrypoints.mpm agent {approvals,approve,reject,audit} <id>` — per-agent Lớp B management (routes to agent's own approval_store).
  - cli.py/cron.py kept as **legacy single-agent entrypoints** (backward-compat).
  - 414 tests pass, ruff clean, E2E verified.
- **Entry points (legacy)**: `python -m src.entrypoints.cli` / `cron` (single-agent, still work). **New (multi-agent)**: `python -m src.entrypoints.mpm`. **Runtime**: `python -m src.runtime.worker`, `python -m src.runtime.service`.

## Cây thư mục (v2 M1-P3 state)

```
src/
├── agent/        # LangGraph graph + nodes + state — LÕI
├── tools/        # *_read.py: jira/github/slack/confluence (READ)
├── actions/      # action_gateway.py + *_write.py (WRITE, qua guardrail)
├── llm/          # provider config + prompts (P2: accepts persona/project/memory params)
├── config/       # Settings, ReportingConfig (P1: no singletons); config_builders
├── profile/      # [NEW P2] Profile loader + context injection
│   ├── loader.py         # Load profiles/<id>/ → LoadedProfile (yaml + 3 MD files)
│   ├── loader_mapping.py # Map profile.yaml → P1 dicts (Settings, ReportingConfig)
│   └── context.py        # ProfileContext (persona/project/memory) + prompt helpers
├── runtime/      # [NEW P3] Worker + service + registry + scheduler
│   ├── worker.py         # python -m src.runtime.worker --agent-id <id> --report <kind>
│   ├── service.py        # Coordinating daemon: reads registry, spawns/supervises workers
│   ├── registry.py       # Load registry.yaml, validate agents
│   ├── agent_paths.py    # Per-agent data dir paths + thread_id generation
│   ├── legacy_migration.py # Once-only move of v1 .data/ → .data/agents/default/
│   ├── scheduler.py      # croniter due-check; fires internal audience only
│   └── run_event.py      # B1 runs.jsonl per agent
├── audit/        # audit log (append-only)
└── entrypoints/  # cli.py, cron.py (legacy single-agent, P2: accept --profile flag)
    │                    # mpm.py (P4: multi-agent dispatcher)
    │                    # mpm_*.py (P4: registry/run/manage subcommands)

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

## Key M1-P3 Changes vs v1

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

- **Unit tests**: `uv run pytest` — 414 tests pass (P1/P2/P3/P4 coverage: config injection, profile loading, registry, worker, service, mpm CLI).
- **Linting**: `uv run ruff check src tests` — clean.
- **E2E**: P4 verified: `mpm agent list` shows default; `mpm agent run default --dry-run` spawned real worker; `mpm agent approvals default` reads per-agent store (slices 94604b7, ed2ed02, 8be3e71).

## Next Steps (M2)

- **M2**: Web dashboard + Postgres + streaming + LangGraph interrupts.
