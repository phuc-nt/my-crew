# v2 — Milestone M2: Web UI + LangGraph upgrades

> Quay lại [README](README.md) · trước: [roadmap-m1](roadmap-m1.md) · sau: [feature-proposals (M3)](feature-proposals.md).

## 6. Milestone M2 — Web UI + LangGraph upgrades

> Mục tiêu M2: web dashboard quản lý + 3 nâng cấp LangGraph (interrupt / streaming / Postgres+Store). Xây trên M1 đã chạy.

### P5 — Graph-native interrupts cho Lớp B (checkpoint-serialized) ✅ COMPLETE

**Status**: DONE (2026-06-24, committed a82dad5 / 85025cf / a01395a, 443 tests, E2E-verified real Slack post).

- **What shipped**: 
  - **New `approval_gate` node** in `src/agent/approval_gate.py` between compose & deliver in all 3 report graphs (report/okr/resource). For `audience="external"` calls `interrupt()` — graph pauses, state checkpoint-serialized per-agent SqliteSaver, resumes via `Command(resume="approve"|"reject")`. Approve → posts LIVE; reject → routes to END (nothing posted, audited).
  - **Approve path fix** via `ActionGateway.execute_approved()` — already-human-approved path skips re-queueing Lớp B, so post goes live immediately (Lớp A hard-deny + audit + dry-run + kill-switch + dedup ALL still apply).
  - **Operator surface** — `worker --resume --thread <id> --decision approve|reject` re-attaches to paused thread, rebuilds matching graph from thread_id, resumes. CLI: `mpm agent resume <id> <thread> --decision approve|reject`. External run exits with status=interrupted, records run-event.
  - **AUGMENT NOT REPLACE**: existing gateway queue path fully intact (pending_approval + ApprovalStore + cli/mpm approve) — one-shot worker subprocess & cli/cron unchanged. Interrupt path is the resume-capable addition. Replace happens at P8 (Postgres, cross-process durability).
- **Files touched**: `src/agent/approval_gate.py` (new), `src/agent/worker_resume.py` (new), `src/entrypoints/mpm_resume_cmd.py` (new), `src/actions/gateway.py` (execute_approved method).
- **Acceptance**: ✅ external report → graph pause at interrupt → state checkpoint → approve via CLI/UI → graph resume → Slack post live. Reject → graph stops clean, audited.
- **Risks**:
  - **Coexist vs replace** (resolved): interrupt AUGMENTS queue arity P5 (both paths live), replace at P8 Postgres. Resume within-process via SqliteSaver; multi-machine cross-process resume depends P8 Postgres durability.
  - **Thread isolation**: threads not matching agent_id are refused.

### P6 — Streaming + FastAPI service ✅ COMPLETE

**Status**: DONE (2026-06-25, committed 1aeb3f5 / 2c2aa4b / e69b76c / ac074ed, 490 tests, E2E-verified real Slack post).

- **What shipped**:
  - **FastAPI localhost service** (`src/server/app.py`): 4 routes:
    - `GET /api/agents` — list enabled agents (registry)
    - `GET /api/agents/{id}/status` — agent budget vs cap + pending-approval count
    - `POST /api/agents/{id}/trigger` — in-process graph run, returns `{run_id, thread_id}`
    - `GET /api/runs/{run_id}/stream` — SSE, live per-node progress (perceive→analyze→compose→deliver) + terminal event
  - **In-process streaming**: trigger runs build graph in-process (not subprocess); sync graph.stream runs in thread, bridged to asyncio queue; SSE emits one event per node. External reports surface approval_gate pause as terminal "interrupted" event carrying thread_id (resume stays via P5 `mpm agent resume`; stream does not block).
  - **PII firewall** (`summarize_node`): each node projects to non-PII fields only (risk_count, cost_usd, delivered bool + status) — persona/project/memory/per-assignee data never reach client.
  - **Concurrency**: one RunManager per process; same (agent, thread) running → 409 Conflict; global cap 4 → 503 Service Unavailable; different agents concurrent OK; single-drain stream (2nd concurrent attach to running run → 409; late attach after finish replays cached terminal).
  - **Security**: localhost-only (binds 127.0.0.1), NO auth (M2 single-operator sandbox; external exposure deferred to later phase). DRY_RUN default + per-agent guardrail (Lớp A/B + audit + budget + dedup) apply to every triggered run.
  - **Runtime**: `uv run python -m src.server.app` (PORT env, default 8765).
  - **Deps added**: fastapi, uvicorn, sse-starlette.
  - **Bonus (P5 fix)**: graphs previously kept fetched models in closure box, not checkpointed → resume KeyError/degraded; now Slack short checkpointed at compose node.
- **Files touched**: new `src/server/{app.py,stream.py}`, new `src/server/models/` (Pydantic schemas); reuse worker + registry.
- **Acceptance**: trigger report via API → SSE streams live node events → approve_gate pause shows terminal event with thread_id → resume via P5 CLI → stream closes, Slack post live.
- **Risks** (resolved): SSE + worker process boundary. Mitigation: service runs graph in-process on-demand (no subprocess, stream direct); scheduled runs stay via worker (§ architecture unchanged).

### P7 — Web dashboard (HTMX + Jinja2) ✅ COMPLETE

**Status**: DONE (2026-06-26, committed 15f881b / d86e1a5 / 89650f7 / 7883710, 545 tests, E2E-verified real Slack post).

- **What shipped**:
  - **Server-rendered HTML dashboard** (`src/server/templates/` Jinja2 templates) on the existing P6 FastAPI app; vendored htmx 2.x for no-CDN sandbox.
  - **6 ops surfaces**:
    1. **Agent list + status** — reads registry, shows running/idle/error per-agent.
    2. **Cost vs budget** — per-agent budget cap and current spend (read-only).
    3. **On-UI Lớp B approve/reject** — lists pending approvals, two-step confirm (operator sees channel + message before POST), reject one-click. POST builds per-agent gateway + calls `gw.approve(id, handler=dispatch_approved_action)` = the SAME real-post path as CLI. Response handling: `HardBlockedError → 403`, bad id `→ 400`, post failure `→ 502` with approval reverted to pending.
    4. **Recent per-agent audit** — reads `AuditLog.query(limit clamped)`, shows last N events per agent.
    5. **Config view + EDIT (S3)** — render `profile.yaml` + `SOUL.md` / `PROJECT.md` editable; `MEMORY.md` READ-ONLY (agent self-writes, no save route). Edit path: VALIDATE config using existing `load_profile()` builders (raises on bad YAML/stakeholder-channel/threshold); if valid, atomic byte-replace; if invalid, return exact error and leave original byte-unchanged.
    6. **Trigger on-demand + live SSE view** — form POSTs existing `/api/agents/{id}/trigger`, streams existing SSE live (same as P6 streaming).
  - **Dispatcher refactored**: extracted `src/actions/approved_dispatch.py` (was duplicated in cli + mpm, now single source).
  - **Security**: localhost-only (127.0.0.1), NO auth (single-operator sandbox), existing guardrail (Lớp A + audit + budget) applies.
  - **Deps**: jinja2; existing fastapi, uvicorn, sse-starlette unchanged.
- **Files touched**: new `src/server/templates/` (Jinja2), new `src/server/dashboard_routes.py` (dashboard POST/GET handlers), `src/actions/approved_dispatch.py` (extracted), `src/server/app.py` (mount dashboard routes).
- **Acceptance**: ✅ list 2+ agents with costs, approve 1 pending Lớp B from UI → Slack post live, edit 1 threshold in profile.yaml → next run uses new value.
- **Risks** (resolved): HTMX vs Streamlit (§9 open question) → **RESOLVED: HTMX+Jinja2 chosen** — lightweight, server-rendered, native SSE integration on FastAPI, no-CDN vendored htmx.

### P8 — Postgres checkpointer + Store + cross-thread agent memory ✅ COMPLETE

**Status**: DONE (2026-06-25, committed 304fc72 / 57b6973 / 9106073, 518 tests, offline-verified with selection tests + no-dsn → ValueError).

- **What shipped (two opt-in halves + internal-only guardrail)**:
  - **Postgres checkpointer (S1)**: `get_checkpointer(settings)` → selects `SqliteSaver` (default, unchanged, byte-identical per-agent file) or `PostgresCheckpointer` (opt-in via new `profile.yaml` `runtime:` block: `checkpointer_type: postgres`, `postgres_dsn`, + env override `CHECKPOINTER_TYPE` / `POSTGRES_DSN`). No infra dependency for common case (SQLite stays default). Postgres path opens raw psycopg connection (process-lifetime). Deps: `langgraph-checkpoint-postgres` + `psycopg[binary]`.
  - **LangGraph Store (S2)**: `get_store(settings)` → `InMemoryStore` (default) or `PostgresStore` (opt-in). Threaded into `compile(store=...)` on all 4 builders; wired in worker/cron/cli. Namespace per `agent_id` for cross-thread memory.
  - **Cross-thread agent memory (S3)**: After a real `INTERNAL` delivery (audience="internal" only), an injectable LLM extractor pulls salient facts → written to Store (namespaced by `agent_id`, content-hash keyed for dedup) AND mirrored into `MEMORY.md`'s agent-managed section (between `<!-- AGENT-MEMORY:START -->` / `<!-- AGENT-MEMORY:END -->` markers; human content preserved). A later run reads them back via existing P2 internal-only `MEMORY.md` injection.
  - **GUARDRAIL: internal-only, no Action Gateway**: memory is INTERNAL agent state — it does NOT flow through the Action Gateway (which governs external mutations only), and it NEVER reaches an external audience. External reports have no memory node; MEMORY.md injection is internal-reports-only.
  - **Verification**: unit = SQLite + InMemoryStore fully tested + Postgres selection logic (right class reached; no-dsn → ValueError). **E2E (2026-06-25) = the opt-in Postgres path RUN against a real throwaway Postgres** — `checkpoints` + `store` tables populated, cross-thread memory persisted, the C1 conn-leak fix held on a live connection. Remaining for production Postgres: a connection pool for concurrency + a long-lived-saver lifecycle decision (infra-gated, not blocking the opt-in default).
- **Files touched**: `src/agent/checkpoint.py` (get_checkpointer refactor), new `src/agent/store.py` (get_store), `src/agent/builders.py` (Store threading), `src/agent/memory_extractor.py` (new, LLM fact extraction), `src/agent/approval_gate.py` (memory node added post-deliver for internal runs), worker/cron/cli (get_store call sites).
- **Acceptance**: 
  - ✅ SQLite default path: agent ghi checkpoint locally, resume interrupt within-process, memory empty (no cross-thread read). 
  - ✅ Postgres checkpointer wiring: config → right class selected, no-dsn raises ValueError. 
  - ✅ Store wiring: builders accept store param, compile calls respect it.
  - ✅ Internal delivery → memory extracted + mirrored to MEMORY.md + survives restart. External delivery (audience=external) skips memory node.
- **Risks** (addressed):
  - **Multi-process resume (P5 + P8)**: P5 resume within-process via SqliteSaver; multi-machine cross-process resume now possible with Postgres (P8 opt-in) — both paths work, user picks infra.
  - **Memory durability**: Store writes are deduped by content-hash; MEMORY.md mirror survives human edits (human content between markers preserved, agent section replaced).

**Exit M2**: v2 multi-agent platform **FULLY COMPLETE** (M1 core + M2 P5/P6/P7/P8 all shipped). Backend (multi-agent + interrupts + streaming + optional Postgres) + **web dashboard (HTMX+Jinja2, 6 ops surfaces)** all in. Postgres + Store opt-in for scale; SQLite default for local dev. Cross-thread memory internal-only, audit guardrail preserved.

---

## Features chèn vào M2 (từ [feature-proposals](feature-proposals.md))

- **B2 Cost metrics API** → P6 (`GET /api/agents/{id}/metrics`, nền `budget_tracker`).
- **A2 Auto-extraction memory** → P8 (LLM trích fact → `MEMORY.md` qua Store; write gated qua gateway).

Phần lớn đề xuất còn lại (cross-agent memory, skill library, MCP gateway, workflow automation) → **M3**, xem [feature-proposals](feature-proposals.md).

---

## M3 — Skill system + advanced agent orchestration

### P10 — Skill system (bundled PM guidance) ✅ COMPLETE

**Status**: DONE (2026-06-26, committed S1 8e6de3d / S2 3413261 / S3 ab5c9b7, 592 tests).

- **What shipped**:
  - **Bundled skills** (`skills/*.md`): 5 instructional skill files (flag-risk, prioritize-blockers, estimate-effort, fetch-jira-epics, parse-github-labels) — each with YAML frontmatter (name, description, applies_to; `allowed-tools` parsed-and-ignored) + markdown PM guidance body.
  - **Skill loader** (`src/skills/skill_loader.py`): scans `skills/` → `Skill` objects. Malformed files skipped (graceful).
  - **Skill pool** (`src/skills/skill_pool.py`): `load_skill_pool(names)` filters declared names → matching Skill objects. `build_skill_context(loaded, settings)` returns `((), None)` when empty (no LlmClient allocation) or `(pool, selector)` when skills declared. No-skills path byte-identical to pre-P10.
  - **Skill selector** (`src/skills/skill_selector.py`): injectable LLM picker `SkillSelector` — chooses relevant skills for a report kind (daily/weekly/okr/resource). Default impl via `make_llm_selector(LlmClient)` or injectable fake for tests. Failure graceful → [].
  - **Selection + injection**: `select_skill_text(context, audience, kind=...)` runs selector, renders chosen skill bodies to `<pm_skills>` block. **RED LINE: internal-only** — returns "" for external audience + checked at compose node + each builder's external branch early-returns.
  - **Wiring**: `profile.yaml` `skills: [flag-risk, ...]` → graph-build entry points (worker/cron/cli in `src/runtime/worker.py`, `src/entrypoints/cron.py`, `src/entrypoints/cli.py`) → `build_skill_context()` + inject into `ProfileContext` → compose nodes call `select_skill_text()`.
- **Files**: new `src/skills/{models,skill_loader,skill_pool,skill_selector}.py` + new `skills/` dir (5 bundled .md files) + wire into all builders + all graph-build entry points.
- **Acceptance**: ✅ profile declares `skills: [flag-risk]` → skill loaded + selected for report kind → instruction injected into INTERNAL compose prompt. External audience omits skills (tested). No skills declared → no LlmClient constructed (tested).
- **Risks** (resolved): internal-only red line verified in depth (external path returns before skills accessed; each builder checks audience).

**Exit M3-P10**: ✅ ĐẠT. Agent skill system (instruction-only, internal-only, allocated-on-demand) shipped — verified offline (fake selector) + live-key E2E: selector LLM thật chọn `[prioritize-blockers, flag-risk, parse-github-labels]` cho daily, lằn ranh đỏ giữ (internal inject `<pm_skills>`, external `""` cả ở select lẫn compose prompt), compose call thật OK (dry_run → không post). Foundation for M3 advanced orchestration features.

### P9 — Cross-agent memory share (A3) ✅ COMPLETE

**Status**: DONE (2026-06-26, committed S1 10a60f1 / S2 ba046af / S3 1512e5a, 628 tests).

- **What shipped**:
  - **Sibling grouping** (`profile.yaml` `project: <slug>` → `LoadedProfile.project_group`): agents sharing a project slug are siblings; no `project:` ⇒ no siblings (backward-compat).
  - **Sibling read helper** (`src/agent/sibling_memory.py`): `enumerate_siblings` (same-group enabled registry agents, self excluded, broken sibling warned+skipped — never crashes the reader) + `read_sibling_facts` (per-sibling Store namespace `(id,"memory")` via namespace-scoped `store.search`, no wildcard — works InMemory + Postgres; capped at MAX_SIBLING_FACTS) + `build_sibling_context` (no-op `((), None)` without LlmClient when no group/siblings/facts).
  - **Sibling-fact ranker** (`src/agent/sibling_selector.py`): injectable `SiblingFactSelector` ranks facts to the relevant subset for a report kind; failure → [] (drop, never break a run); filters output back to the input set (hallucination guard).
  - **Injection + red line**: `select_sibling_text(context, audience, kind, project_group)` renders a labeled block `--- Bộ nhớ agent khác (project: <slug>) ---` into the INTERNAL compose prompt of all builders. **Internal-only** — external returns "" + each builder folds sibling text after its external early-return.
  - **WO-self / RO-sibling**: `memory_node._assert_self_namespace` raises if a write targets any namespace other than `(self_id,"memory")` (fail loud). Cross-agent is read-only.
  - **Wiring**: worker/cron/cli build the sibling context and thread ONE store instance (sibling READ + remember WRITE share state); the M2-P6 server path inherits via worker.
- **Acceptance**: ✅ two agents with the same `project:` — B reads A's stored facts into B's INTERNAL prompt; external omits them; no-project byte-identical + allocation-free (tested, offline e2e ×3 kinds).
- **Risks** (resolved): internal-only red line verified in depth; broken-sibling-profile isolation (S1 review HIGH → fixed); widened secret-exposure threat-model documented (architecture §6.2).

**Exit M3-P9**: ✅ ĐẠT. Cross-agent memory share shipped — verified offline (fake selector) + **FULL live-key E2E trên Postgres shared**: 2 agent cùng `project: e2e-acme`, B chạy report thật (Jira SCRUM 21 issue + LLM compose) → extractor LLM thật sinh 5 fact → ghi Postgres; A đọc 5 fact qua connection RIÊNG (chứng minh cross-process), selector LLM thật chọn → 5/5 fact + label `project:` vào prompt INTERNAL của A; A `--audience external` → 0 leak (red line giữ live). Dọn sạch (profile + container + data) sau chạy; DSN không vào file commit. **Lưu ý vận hành**: đọc-chéo hiệu lực thật CHỈ với `store: postgres` (default InMemoryStore per-process → A3 degrade sạch về no-siblings ở multi-process) — đã xác nhận live.
