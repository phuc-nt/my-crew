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

**XLSX report artifacts + email attachment (D3, v11)**:
- Resource/cost and OKR report kinds now export as `.xlsx` files (deterministic, no LLM). Built via `src/reporting/xlsx_export.py` from already-computed dataclass analyzers, written to `data_dir/artifacts/<kind>-<date>.xlsx` (a confined, internal-only artifact directory alongside `budget/` and `audit/`).
- When SMTP is configured, email delivery attaches the `.xlsx` file as a multi-part MIME attachment (stdlib `smtplib` only, no new dependencies). The attachment path rides the action dict as a **path string** (never bytes), staying out of audit log / approval store (defense-in-depth).
- **NEW Lớp A confinement red line** (P2): Attachment MUST be `.xlsx`, MUST exist, and MUST be inside `data_dir/artifacts` (verified via `Path.resolve()`, which dereferences symlinks to catch escape attempts). Checked by `confined_xlsx_path()` in `hard_block.py`; re-verified at send time in email handler (same check, so no drift). Fails hard-deny if violated (traversal, absolute path elsewhere, symlink escape, missing artifact_root).
- Email attachment is internal-only (audience="internal" only); no change to external audience or Slack/Confluence delivery (text-only, same as before).

**Unchanged invariant (restate)**: Every new write (Linear comment, email, email + attachment) stays behind Action Gateway — Lớp A hard-deny + default-DENY allowlist + Lớp B approve. New write tools deny by default until explicitly allowlisted. Config flows through all 3 entry points (worker/cron/cli) automatically. Backward-compat: no `integrations:` + no `smtp:` ⇒ byte-identical pre-P11 behavior (Slack+Confluence only). `classify()` / `needs_interrupt()` unchanged.

## 7. v12 Agent Office — Orchestrated team task execution + group chat + 3D office

**M27–M30 deliver orchestrated team task workflow with centralized office.** Coordinator (TICKER pseudo-kind) decomposes CEO task → plan hash bind (TOCTOU-proof) → sequential step dispatch DETACHED workers (per-agent isolation preserved). Artifacts handoff via `data_dir/artifacts/team-tasks/<id>/step-<n>.json` (internal, NO egress). Every step write vẫn Lớp B per-agent. Web search (Tavily/Brave snippets-only) fail-closed pattern-scan BEFORE egress. Office room (SQLite WAL+seq SSoT) events feed SSE store-tail (multi-subscriber, seq-cursored resume-safe) → OfficeRoom timeline + office-3d r3f wireframe (lazy chunk ~930KB, driven by real SSE only). Telegram mirrors milestone events (cursor-after-send, no spam).

**THE INVARIANT extended:**
- **Handoff = artifact inside data_dir** (KHÔNG egress, KHÔNG qua gateway). Per-step writes vẫn Lớp B per-agent.
- **office-pack allowlist wiring bắt buộc** (M8-class guard): `ActionGateway.execute(..., mcp_allowlist=pack.allowlist or None)`. Pack allowlist rỗng = default-deny; coordinator/step KHÔNG handler mặc định.
- **Role authz gate deterministic** (decompose-validation + dispatch): `assigned_to` ∈ company.yaml staff + CEO-confirmed plan hash.
- **PII firewall office events**: default-drop allowlist projection AT WRITE TIME (safe replay, cấm free-form body_json).

```
CEO giao việc (ops chat) → assign_team_task (admin ops agent, sync 1 LLM) → DecomposedTask (max 7, role-constrained)
   ├─► plan draft + content HASH → preview → CEO confirm (bind HASH, TOCTOU-proof)
   │
   ▼ set plan status = open
   
coordinator TICKER (short tick, no 600s-kill, lease reserve attempt_id+pid+lease_expires_at)
   ├─► next_pending_step → spawn DETACHED worker "team-step" (per-agent isolation)
   ├─► running: pid chết → failed/retry; lease > timeout → kill pid + escalate Telegram
   └─► reboot recovery = tick sau read store (không resume trigger riêng)

team_task_graph (perceive→work→deliver)
   ├─► perceive: brief + handoff artifact từ step trước
   ├─► work: LLM + persona + company-docs + web search (role Nghiên cứu)
   │   ├─ web search: Tavily/Brave snippets-only, fail-closed pattern-scan BEFORE egress
   │   └─ audit: redacted query only
   └─► deliver: atomic artifact + append office_room_store (PII projection AT WRITE TIME)

office_room_store (SQLite WAL+seq SSoT) ──► routes_office_stream (SSE store-tail, multi-subscriber)
   ├─► OfficeRoom.tsx (timeline)
   ├─► office-3d/office-scene (wireframe, tween by state, 2D fallback)
   └─► milestone_mirror_runner (store-poller, cursor-after-send, milestone→Telegram)
```

**Web-search egress threat model:**
- **Stage 1 (fail-closed redaction)**: pattern-scan query before egress → no match = NO egress (FAIL-CLOSED).
- **Stage 2 (injection delimiting)**: 4-layer defense (delimiter markers / regex markers / ToolMessage sandbox / spotlight highlighting).
- **Stage 3 (snippets-only)**: Tavily/Brave return snippets; no page-fetch (reduces injection surface).
- **Stage 4 (ToolMessage audit)**: content-search result never assigned external write permission; audit logs redacted-only query.
- **Accepted residual risk**: regex KHÔNG bắt free-form secrets (composed inside query từ internal context) — same class accepted-risk as Atlassian tokens (pattern-undetectable). Mitigated by: snippets-only + fail-closed on known patterns + audit redacted.

**M33 consult đồng nghiệp**: `work` node có hook tùy chọn (`deps.ask_colleague`, off mặc định) cho phép step hỏi tối đa 2 đồng nghiệp/attempt TRƯỚC khi làm việc. Đây là RO role-play consultation đọc trực tiếp FILE `SOUL.md`+`PROJECT.md` của đồng nghiệp (`profile.loader.load_profile`) — **KHÔNG PHẢI hệ thống sibling-memory** (`sibling_memory`/LangGraph `Store`): Store rỗng trong detached worker (không có tác dụng), và sibling-memory bị `project_group` red line giới hạn scope hẹp hơn "hỏi bất kỳ ai trong roster" mà consult cần. Mỗi consult ghi 1 room event `kind=consult` (`{from, to, question_summary, answer_summary}`, mỗi field template-truncate ~120 ký tự tại CẢ writer lẫn `office_event_projection` allowlist — không bao giờ lộ nội dung file/câu trả lời thô). Consult fail (đồng nghiệp không tồn tại/file lỗi/LLM lỗi) → DEGRADE về rỗng, không raise, không tốn lượt rework.

## 8. v13 Team self-operation — Deep step graph, peer review, consult, parallel cap, full replan

**M31–M34 deliver orchestrated team self-operation.**

**M31 — Step graph LangGraph sâu**: `team_task_graph.py` v2 enhances perceive→work→deliver with **self-check loop**. Node `self_check` takes criteria from `step.acceptance` (metadata per-step, NOT in canonical hash — Decision A); outputs structured `CheckVerdict` (passed/failures/confidence). Conditional `route_after_check`: passed → deliver | rework_count<2 → rework → self_check (loop) | exhausted → deliver (with flag). **Rework counter ≤2 primitives in state** (reset per attempt — intentional; v12 semantics: retry=fresh attempt, no resume mid-graph). **KHÔNG checkpointer/SqliteSaver/migrate_state** — Decision B drops these; `.stream(stream_mode=["updates","custom"])` yields `(mode, chunk)` tuples; heartbeat fires only on `updates` mode. Attempt_id carries into room events to drop zombie-attempts. New artifacts include `version:=attempt_id` + `_read_handoff` deps-aware (read by DEPENDS, not seq-1).

```
perceive(brief + handoff[step-N-1.json]) → work(LLM + web-search) 
→ self_check(acceptance criteria from step.acceptance col) → route_after_check
   ├─ passed → deliver → step artifact
   ├─ rework_count < 2 → rework_prompt (prior output + failures via format_internal_content) → self_check (loop)
   └─ exhausted → deliver (flag self_check_failed, no block)
```

**M32 — Peer review tự chèn**: After content-step completes + `needs_review=1`, ticker (not LLM) invokes `pick_reviewer(author_id, roster)` → inserts review-step with `step_type=review, system_inserted=1`. Reviewer = peer ≠ author, id-contains kiem/qa/review preferred, else any peer tie-break by id; if no peer, SKIP review (room event "bỏ soát", no stall). `review_graph.py` new: locks artifact via `version(=attempt_id)` → structured `ReviewVerdict` (binary: passed/failures list) → deliver. Verdict KHÔNG steering — only returns passed/failures, never changes assignee or adds/removes steps. On "cần-sửa", ticker inserts rework-step (same author) via `review_round` counter; ≤2 rounds, then EXPLICIT stall+escalate (no auto-retry). 4 prompts wrap artifact content via `format_internal_content` red-line (self_check result_text / review failures / rework prior-output / consult question+answer).

**M33 — Consult đồng nghiệp (colleague advice)**: Work node hook `ask_colleague(agent_id, question)` ≤2/step. Loads colleague SOUL.md + PROJECT.md FILE RO via `profile.loader.load_profile()` (KHÔNG Store, KHÔNG sibling-memory — internal-only by design, M3-P9 red line intact). Question + colleague context → 1 LLM call → answer cached in state; fail = degrade no-answer (doesn't raise, doesn't burn rework round). Question wrapped via `format_internal_content`. Room `consult` event: template-truncate {from, to, question_summary, answer_summary} each ~120-char AT WRITE TIME in `office_event_projection` allowlist (never raw file or answer text).

**M34 — Parallel cap 2 + full replan**: v12 already dispatched concurrent across ticks (per-step workers in parallel); v13 **adds cap** (config `team_task_concurrency`, default 2). Coordinator tick counts `running` steps; if at cap, defer next pending. Cost headroom **DERIVED** from `Σ estimate over steps status='running'` (no ledger, no reserve/finalize/release) — overshoot intra-graph bounded per step. Awaiting-approval KHÔNG hold headroom.

**Full replan** (`adjust_team_task` on admin agent): CEO/coordinator proposes mid-execution adjustment → amend LLM (context=id/title/assigned_to/status only; done/running FROZEN) → preview DIFF (keep/drop/add + cost delta) → CEO confirm via `base_plan_hash` full-DAG TOCTOU re-validate (subsume completed-prefix + pending-set + inserted-steps + amend-over-amend). SINGLE live draft/task; confirm CONSUMES draft; verify+swap within `BEGIN IMMEDIATE` txn vs ticker. Coordinator escalate: ĐỀ XUẤT text (CONSTANT template task_id-only interpolation, KHÔNG LLM-composed — anti-steering Decision C). Swap updates pending-only; skip just-reserved steps; done/running immutable.

**THE INVARIANT + v13 amendments (must stay intact)**:
- **Handoff = artifact** `/data_dir/artifacts/team-tasks/<id>/step-<n>.json` (internal, KHÔNG egress).
- **Every external write per-step vẫn Lớp B per-agent** via `ActionGateway.execute()` + per-agent isolation.
- **Allowlist default-deny** (unchanged).
- **New (v13 Clause 1) — Verdict no-steering**: review verdict = binary (passed/failures); KHÔNG đổi assignee, KHÔNG add/remove steps. Only ticker (hardcoded rules) inserts review/rework — not LLM.
- **New (v13 Clause 2) — Amend CEO-confirm-hash**: `adjust_team_task` no auto-apply. Preview DIFF → CEO confirm binds `base_plan_hash` full-DAG (TOCTOU re-validate). Single draft, confirm consumes, BEGIN IMMEDIATE.
- **New (v13 Clause 3) — Consult RO-internal-only**: colleague context = SOUL.md + PROJECT.md FILE-only, KHÔNG Store, KHÔNG sibling-memory (M3-P9 red line intact).
- **PII firewall office events**: closed-ENUM `phase`/`verdict`/`consult` (template-summary consult ~120-char at WRITE TIME). Role authz deterministic (assigned_to ∈ company staff, decompose-validate + dispatch both checked).

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

- **Observability JSON API layer** (`src/server/routes_visualize.py`): 5 read-only endpoints (`/api/{runs,cost,memory,automation,audit}/{id}`) each projecting to a non-PII allowlist mirroring `summarize_node`. Memory internal-only (external → no facts; `?audience` gated). No guardrail change.
- **Ops JSON routes** (`src/server/routes_ops_json.py`): approve/reject/config reads calling the identical `gw.approve(handler=dispatch_approved_action)` / `profile_editor` functions; shared `ops_helpers.py` extracted from CLI dispatcher.
- **React surfaces**: Timeline, Cost (react-chartjs-2), Guardrail (verdict + audit), Memory (internal), Automation (internal). Read-only; approvals trigger via the existing gateway-routed endpoint (no new write authority).
- **What's deleted**: `routes_dashboard.py`, `routes_approvals.py`, `routes_audit.py`, `routes_profile.py` (HTML routers), `src/server/templates/`, htmx static + 5 htmx tests. Coverage guard: every unique edge-case re-asserted in a JSON test first.
- **M4 is shipped**: 5 slices (S1 JSON API, S2 React shell, S3 visual views, S4 ops surfaces, S5 wiring), 785 pytest green, vitest 11, ruff clean.

### 11.1 Design system & theming layer (v9 M3–M4, v10 M24–M25)

**v9 P3 — Design tokens (CSS-only)**:
- **`:root` CSS variables** — semantic colors (text/muted/primary/danger/ok/warn), spacing (space-1..5), radius, shadow, type scale. 112+ usages → zero hardcoded hex. WCAG AA verified: all roles ≥4.5:1 contrast light + dark.
- **Status colors role-split**: `--color-{status}` (text/border) + `-solid` (white-on-fill) + `-bg` (tint) + `--color-on-{status}` → separate tokens per role, not 1-value-fits-all (prerequisite for both-themes AA).
- **Be Vietnam Pro woff2** self-hosted (8 files, 96KB total, no CDN, offline safe, unicode-range subset).
- **Motion**: transitions 120–180ms gated by `prefers-reduced-motion: no-preference`; reduce mode strips all.

**v10 M24 — Dark mode system**:
- **Two-layer tokens**: `:root` (light defaults) + `[data-theme="dark"]` selector (dark values). Same token names, different computed values.
- **Anti-FOUC**: inline script in `index.html` reads `localStorage['theme']` → sets `<html data-theme>` + `theme-color` meta BEFORE React mounts (zero flicker).
- **`theme-context.tsx`**: React context manages theme state (light|dark|auto), resolves auto → `prefers-color-scheme`, persists to localStorage. ThemeToggle component (3-state button).
- **`color-scheme: light/dark`**: native controls (select/input/scrollbar) auto-follow theme.
- **Chart theme-aware** (`chart-theme.ts`): `getComputedStyle()` reads token colors at render time; `key={resolvedTheme}` remounts charts on theme change.

**v10 M25 — Dual-mode UI toggle**:
- **`ui-mode-context.tsx`**: global state (low|high), persists to `localStorage['ui-mode']`.
- **Low mode** (default, CEO): 4-item nav (Team/Chạy tay/Cài đặt/Tài liệu).
- **High mode**: nav + 7 advanced views (Overview/Timeline/Cost/Memory/Guardrail/Config/Advanced runs); all i18n Vietnamese.
- **Settings → Chế độ hiển thị** toggle; no auth change (view-layer only, routes still auth-gated).
- **7 advanced views + 5 components i18n**: labels.ts centralized, zero English leak verified E2E.

**v10 M26 — Installer hardening + health panel**:
- **IntegrationHealthPanel** DRY: Settings + wizard first-run reuse same component (team view + new context).
- **Health checks**: env vars present (OPENROUTER_API_KEY), MCP dist paths exist, `gh auth` status (parsed stdout), `gws` CLI availability (HR pack).
- **Backtick → `<code>`**: hint text `` `command` `` rendered as copy-pasteable code blocks (guard backtick lones → no XSS).

### 11.2 Responsive design (v9 M4)

- **Mobile card-list** (`@media (max-width: 640px)`): CEO tables (Team/Tasks/Approvals) → cards (tr→div, td→flex with data-label prefix).
- **Advanced tables** (AuditTable/RunList/Overview): `.table-scroll` overflow-x (technical persona expects horizontal scroll, not card collapse).
- **Touch-friendly**: `min-height: 44px` buttons; `font-size: ≥16px` inputs (iOS Safari zoom prevention).
- **Wrap**: nav, quick-action chips, approval lists responsive wrap on mobile.

### 11.3 i18n & trust surface (v9 M1)

- **`labels.ts`**: centralized enums (RUN_STATUS, KIND, VERDICT) → Vietnamese labels; formatDateTime, formatCron helpers.
- **`action-summary.ts`**: tóm tắt tiếng Việt per action type (Jira/Slack/Confluence/Linear/GitHub/Email) — reads field-shape from backend JSON, safe for external class flag.
- **ConfirmDialog**: Vietnamese title/buttons/summary, external class highlight (red/bold + "Gửi RA NGOÀI công ty" warning), JSON audit in `<details>`.
- **E2E verified**: 0 English leak across CEO + advanced views + all surfaces.

## 13. Low-Tech Agent Creation & Lifecycle (v3 M7, 2026-07-02)

**v3 M7 adds non-technical web surfaces for agent creation, configuration, and lifecycle management.** Positions "technical setup" (uv, MCP builds, `.env` tokens) as one-time infrastructure; "day-to-day agent ops" (create/pause/resume/delete) entirely via web — zero terminal/YAML/secrets exposure.

### M7 Backend (4 new modules, ~450 LOC)

**`src/runtime/registry_edit.py`** — shared registry mutations (CLI + API reuse):
- `scaffold_agent(id)`: create `profiles/<id>/` with default `profile.yaml`, `SOUL.md`, `PROJECT.md`, `MEMORY.md`
- `append_registry(agent_id, ...)`: validate-before-replace (build in-memory, parse-check, atomic write) — never corrupt
- `toggle_agent_enabled(id, enabled)`: set registry enabled flag
- `remove_agent(id)`: keep profile dir as archive (safety), refuse to delete `default`

**`src/server/agent_create.py`** — wizard backend:
- `list_available_packs()`: read from `domain-packs/*/pack.yaml` (no import — broken pack doesn't 500 the picker)
- `create_agent_from_request(request)`: build profile.yaml from wizard input, validate using **exact same config builders** that `load_profile` uses before writing (fail-fast, never write invalid config)

**`src/server/integration_health.py`** — health check panel:
- Boolean presence: env vars (`OPENROUTER_API_KEY` set?), MCP dist paths exist, `gh auth status` (parsed via stdout), `which gws` (for hr-pack users)
- **Never returns secret values**, cache 30s
- Used by `/api/health/integrations` endpoint

**`src/server/routes_agents_admin.py`** — 5 new config-only endpoints (all localhost, no auth, validate-before-replace, atomic):

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/packs` | GET | List available domain packs from `pack.yaml` manifests |
| `/api/agents/create` | POST | Create new agent: body = `{domain, agent_id, name, persona, report_kinds, schedule, bindings}` → validates, scaffolds, returns 201 on success or 400/409 (id exists) |
| `/api/agents/{agent_id}/enabled` | PATCH | Toggle enabled flag in registry; returns `{effective_enabled}` = registry AND profile both enabled (UX clarity) |
| `/api/agents/{agent_id}` | DELETE | Mark agent disabled in registry; keeps `profiles/{agent_id}/` as archive for audit; refuses to delete `default` |
| `/api/health/integrations` | GET | Return boolean map of integration presence (no secret values) |

### M7 Frontend (wizard + Team view)

**Create-Agent wizard** (`web/src/wizard/`):
- **Step 1 — Domain**: Select pm, hr, or future custom pack
- **Step 2 — Identity**: Enter agent ID (regex validated client=server), human name, optional persona paragraph
- **Step 3 — Reports & Schedule**: Pick report kinds available for the selected domain, build cron via visual `ScheduleBuilder` (pick day+time → 5-field cron string, displayed for transparency)
- **Step 4 — Bindings**: Fill project/repo/channel/space fields; **ScheduleBuilder** renders cron visually
- **Step 5 — Review**: Show all fields, render `.env` variable-name template ("Copy these names to your tech operator, they'll fill values"), confirmation button

**Team view** (`web/src/views/Team.tsx`):
- Table: agent ID, name, status (enabled/paused), budget usage, pending approvals count
- **Actions per row**: Pause/Resume (PATCH `/api/agents/{id}/enabled`), Delete (with confirm), drill-down to full Config
- **IntegrationHealthPanel**: health status (env presence, MCP dist, gh auth, gws availability) at top; hint text for non-technical users ("GitHub auth missing — ask your operator to run `gh auth login`")

### Invariants Held

- **Config-only writes** (no external mutations): all routes mutate `profiles/` + `registry.yaml` only, never call Jira/GitHub/Slack → no Action Gateway involvement (gateway is for external writes; local config is internal safety gate)
- **Validate-before-replace + atomic**: request failure never leaves registry/profile corrupt; if parse fails, rollback
- **No secret exposure**: POST/PATCH/DELETE never accept or return token values; health endpoint returns only boolean presence
- **Localhost-only, no-auth**: M2 posture maintained (auth layer deferred)
- **CLI reuses API code**: `mpm agent register` imports `registry_edit.scaffold_agent` + `append_registry` — single DRY path for both UI and CLI

### v3 M7 Test Coverage

- **pytest 863** (up from 776): new `test_registry_edit.py`, `test_agent_create.py`, `test_integration_health.py`, `test_routes_agents_admin.py`
- **vitest 30** (new): wizard steps, ScheduleBuilder, persona template, env template, Team view
- **E2E live**: create agent via POST → verify GET /api/agents lists it → PATCH pause → DELETE → registry.yaml byte-identical after round-trip
- **ruff clean**, **tsc no errors**

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
