# Changelog — my-project-manager

Version-by-version summary of what shipped. Each version was E2E-verified against real
Jira/GitHub/Slack/Confluence (and, from v6, a real Telegram bot) before being marked complete.
For the decision-by-decision narrative see [journals/](journals/).

Guardrail invariant held across every version: every write flows through the Action Gateway —
Lớp A hard-deny (never reaches the LLM) + Lớp B human approval. No version weakened it.

---

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
