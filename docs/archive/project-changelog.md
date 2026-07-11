# Changelog — my-project-manager

Version-by-version summary of what shipped. Each version was E2E-verified against real
Jira/GitHub/Slack/Confluence (and, from v6, a real Telegram bot) before being marked complete.
For the decision-by-decision narrative see [journals/](journals/).

Guardrail invariant held across every version: every write flows through the Action Gateway —
Lớp A hard-deny (never reaches the LLM) + Lớp B human approval. No version weakened it.

---

## v13 — Đội ngũ tự vận hành (2026-07-10)

Deep step graph with self-check loop, peer review insertion, colleague consultation, parallel execution cap 2, and full replan. **M31–M34** deliver:
- **M31** Step graph LangGraph sâu: `perceive → work → self_check` with rework loop ≤2 counter in state (primitives, reset per attempt). CheckVerdict structured (`passed`/`failures`/`confidence`). `acceptance` metadata per-step NOT in `decomposition_content_hash` (lưu `team_steps.acceptance` col, round-trip self_check criteria). `confirmed_plan_hash` = DAG CEO-confirmed (hệ thống-inserted review/rework rows `system_inserted=1` loại khỏi verify); `version:=attempt_id` versioning + `_read_handoff` deps-aware (không seq-1); node phase events (dang-lam/tu-soat/dang-sua) qua `.stream(stream_mode=["updates","custom"])` → room append; attempt_id carry zombie-event drop. **KHÔNG checkpointer/SqliteSaver** — drop Decision B, retry=fresh attempt v12 semantics.
- **M32** Peer review tự chèn (ticker cứng, KHÔNG LLM steering): content-step done `needs_review=1` → review-step chèn (reviewer = pick_reviewer: peer ≠ author, id-contains kiem/qa/review preferred, else any, tie-break by id; không peer → SKIP+room "bỏ soát", KHÔNG stall). ReviewVerdict nhị phân (`passed`/failures). Rework ≤2 vòng via `review_round` col → hết vòng → EXPLICIT stall+escalate. Verdict KHÔNG steering (KHÔNG đổi assignee/step). Hash split Decision A: `system_inserted=1` loại khỏi `_verify_plan_hash`.
- **M33** Consult đồng nghiệp (ask_colleague ≤2/step in state): load colleague SOUL.md + PROJECT.md FILE RO (KHÔNG Store, KHÔNG sibling-memory — internal-only by construction). Question via `format_internal_content` → 1 LLM call → answer; fail=degrade no-raise. Room `consult` event template summary ~120-char (KHÔNG raw file). 4 artifact-consuming prompts (self_check/review/rework/consult) wrap `format_internal_content` red-line.
- **M34** Parallel cap 2 (config `team_task_concurrency`): v12 ĐÃ dispatch concurrent, v13 THÊM cap đếm running steps; cost headroom DERIVED từ steps `running` (KHÔNG ledger → không leak). **Full replan** `adjust_team_task` trên admin agent: amend LLM → preview DIFF → CEO confirm bind `base_plan_hash` full-DAG TOCTOU (SINGLE live draft, confirm CONSUMES, BEGIN IMMEDIATE) → swap pending-only (skip just-reserved). Amend only via CEO confirm-hash (Decision C). Coordinator escalate ĐỀ XUẤT text (constant template task_id-only, KHÔNG LLM-composed).
- **THE INVARIANT + 3 new clauses v13** (must stay intact): verdict không steering; amend chỉ qua CEO confirm-hash; consult RO internal-only (file, không sibling-memory). Handoff = artifact (KHÔNG egress). External write per-step vẫn Lớp B per-agent qua ActionGateway. Allowlist default-deny giữ. PII firewall office events + `phase`/`verdict`/`consult` closed-ENUM. Role authz deterministic (assigned_to ∈ staff both decompose-validate + dispatch).
- **E2E-verified live 2026-07-10**: peer review inserted (reviewer ≠ author picked, verdict cần-sửa), rework loop ≤2 rounds stalled+escalated, phase events streamed to room, full replan DIFF→confirm→pending-only swap with task continuing, parallel cap 2 active (2 running). 1644 backend + 158 FE tests. Two real bugs caught by E2E+review: decompose prompt now instructs needs_review/acceptance (else peer never fired); amend frozen-prefix excludes system_inserted (else valid amend stalled reviewed task).

## v12 — Agent Office (2026-07-10)

Orchestrated team task execution with group chat room + 3D office visualization. **M27–M30** deliver:
- **M27** Company setup (company.yaml name/coordinator/cap-$2, gitignored per-install; staff templates profiles/templates/ = wizard prefill, 6 roles incl 5 office roles VN personas; 1-click "Tạo trưởng phòng").
- **M28a** Team-task store (SQLite WAL+seq+lease) + task execution graph (perceive/work/deliver atomic handoff).
- **M28b** Coordinator pipeline (TICKER pseudo-kind, sequential dispatch DETACHED workers per-step with lease/pid/600s timeout, awaiting_approval pauses clock, reboot-safe) + web search (Tavily/Brave snippets-only, fail-closed query redaction, 4-layer injection defense, audit redacted-only).
- **M29** Office room (office_room_store SQLite WAL+seq SSoT, PII projection AT WRITE TIME, SSE store-tail multi-subscriber /api/office/rooms/{id}/stream, Telegram milestone-mirror store-poller cursor-after-send).
- **M30** Office 3D (r3f wireframe lazy chunk ~930KB isolated from main bundle, 2D fallback reduced-motion/mobile).
- **THE INVARIANT extended**: office-pack allowlist wiring, deterministic role authz gate (decompose + dispatch, admin/coordinator never assignable), PII write-time firewall.
- **E2E-verified live 2026-07-10**: real 6-step marketing-plan task through 4 agents (LLM OpenRouter), room + 3D in browser, real Telegram milestone DM; 1500 backend + 146 FE tests.

## v11 — MCP suite optimization + XLSX report export (2026-07-08 → 10)

Backend performance + reliability overhaul. **P1–P4** optimized 3 MCP servers (Slack/Confluence/Jira)
as a bundled suite with session pooling, caching, and npm distribution. A follow-on quick-win adds
deterministic XLSX export for resource/OKR reports with email attachment (internal-only, Lớp B
approval). 1257 tests green; unchanged invariant.

- **P1 — Slack cache + whoami**: Added `whoami` tool + classifySlackError for token-expired
  diagnosis; disk-cache channels/users (TTL 900s, SUPERSET-populate strategy); cold 363ms→warm 2ms.
  Removed pre-flight auth.test and 429-retry logic (slimmed ~4–5k LOC).
- **P2 — Confluence lazy-boot + Jira deps cleanup**: Confluence skips boot testConnection
  (default lazy, opt-in via `API_CONNECTION_TEST`); Jira dropped dead deps (axios, vestigial
  jira.js stub) — node_modules 122M→80M. Both shipped and tested live.
- **P3 — MCP session-reuse pool**: McpSessionPool owner-task design (anyio cancel-scope per-task)
  reuses 1 subprocess per server per run; fixed CancelledError handling (BaseException, not
  Exception); reduced weekly spawns 5→2 (−43%). Fixed 3 pre-commit findings on task lifecycle.
- **P4 — npm publish + installer hardening**: Bundled esbuild 3 servers, published to npm
  (v1.3.0/1.5.0/4.2.0). Install.sh enforces min version by default; added no-clobber MCP_DIST
  + migration warning + version comparison (sort -V); CLI flag `--mcp-dev` for local build.
- **XLSX report export + email attachment** (quick-win, 2026-07-10): Resource/cost and OKR
  reports export as deterministic `.xlsx` (no LLM, pure dataclass serialization), stored in
  `data_dir/artifacts/`. Email delivery attaches the `.xlsx` when SMTP is configured; the
  attachment rides as a path (never bytes → stays out of the audit/approval store) and is
  confined by a new Lớp A red line (must exist, be `.xlsx`, and resolve inside the artifact
  dir — symlink-safe). Internal-only (audience="internal"). All writes still Lớp B → human approval.

## v10 — Re-design UI + dual-mode + installer (2026-07-07)

Frontend-heavy polish for publish-readiness. Backend contracts unchanged (1206 tests green;
only one additive field).

- **M24 — Theme light/dark + diện mạo**: two-layer design tokens (`:root` light + `[data-theme=dark]`)
  with role-split status colors so both themes pass WCAG AA; light/dark/auto switch (persisted,
  OS-following, no flash-of-unstyled-content); self-hosted Be Vietnam Pro font (no CDN); subtle
  motion gated behind `prefers-reduced-motion`.
- **M25 — Dual-mode low/high tech**: a global "Chế độ nâng cao" toggle — low keeps the 4-item
  CEO nav, high surfaces the 7 technical views (fully translated to Vietnamese). The Trigger form
  now offers each agent's own report kinds (additive `report_kinds` on `/api/agents`); the live
  run stream distinguishes a normal end from a dropped connection.
- **M26 — Installer hardening + system-health panel**: `deploy/install.sh` gains a fail-loud
  preflight, restart-only-on-change (a no-change re-run never kills a running agent or drops web
  sessions), a temp-build + atomic swap for the SPA, MCP-path awareness, and a final health gate;
  it's portable to the macOS default bash. Settings shows a live system-health checklist with
  copy-paste fix commands.

## v9 — UX / i18n polish (2026-07-07)

Production-ready for a non-technical Vietnamese CEO: full Vietnamese UI, a readable trust surface
(approval dialogs summarize each action in plain Vietnamese and flag anything leaving the company),
design tokens meeting WCAG AA, and a responsive mobile card-list so you can read + approve on a phone.

## v8 — Ops-trust (2026-07-04)

Real-operation trust features. **M21** CEO-observability: an agent that dies silently now pings the
CEO on Telegram. **M22** multi-project rollup: a fleet-wide summary (report content stays
internal-only, never leaked to the status API). **M23** trust ladder: opt-in auto-approve for
Lớp B actions with a per-day cap — the CEO turns it on by hand, it is never auto-earned, and Lớp A
/ allowlist / kill-switch are always checked first.

## v7 — Zero-friction (2026-07-04)

Install once, use without a manual. **M17** browser setup wizard (self-locking after finish).
**M18** run-an-agent-now from Telegram + a unified agent page. **M18b** knowledge as a form (not raw
files) + skills. **M19** Company Docs library (hard red line: external audience reads nothing).
**M20** CEO-first navigation reduced to 4 destinations.

## v6 — Virtual-staff company (2026-07-03/04)

"A company with one CEO". **M13** each virtual staffer gets its own Telegram identity. **M14** CEO
chat-ops (talk to the admin agent to run things). **M15** assign work in three shapes (watch / report-QA
/ task-board). **M16** authentication + go-live.

## v5 — Scale out & up (2026-07-02)

**M8** an "admin" agent that fleet-watches every other agent (read-only). **M12** chat-command → Lớp B
approval queue. Pack graphs must wire their allowlist into the gateway (default-deny holds).

## v3 — Domain packs + low-tech UI (2026-06-30 → 07-02)

**M5** the domain-pack abstraction (a new domain is a dropped-in folder, zero core edits). **M6** an HR
pack proving it (reads Google Sheets via the `gws` CLI). **M7** a low-tech web UI (daily operation is
100% web; infra setup stays a one-time technical step). **M9** model fallback chain. **M11** an
ask-the-agent inbox.

## v2 — Multi-agent platform (2026-06-24 → 27)

**M1** N agents / N projects, fully isolated, run via CLI/worker + scheduler. **M2** graph-native
Lớp B interrupts, a FastAPI SSE service, a web dashboard, and an opt-in Postgres checkpointer/store.
**M3** a skill system, cross-agent memory, config-driven integrations (Linear, Email/SMTP), and
opt-in observability (LangSmith tracing, checkpoint replay). Later replaced the HTMX dashboard with a
React SPA (M4).

## v1 — Reporting + guardrail (Phases 0–5, 2026-06-21 → 22)

The foundation: daily/weekly/OKR/resource reports read from Jira/GitHub and posted to Slack/Confluence
on a schedule, all behind the Action Gateway (allowlist + Lớp A hard-deny, the two-layer guardrail),
with a $50/month budget cap, an append-only redacted audit log, dedup, and audience-split reporting
(internal vs external via human approval).
