# v2 M4 — React visualization dashboard
2026-06-28 · ✅ Done

## Làm gì
- **S1 JSON API layer**: new `routes_visualize.py` (5 read-only endpoints: `/api/{runs,cost,memory,automation,audit}/{id}`) + helper functions (`run_event.read_run_events`, `budget_tracker.monthly_series`). Each projects to non-PII allowlist mirroring `summarize_node`. Memory internal-only via `?audience` gate (external → no facts). No guardrail change.
- **S2 React shell**: Vite + TypeScript SPA (`web/`, committed build to `src/server/static/app/`). Typed `api/client.ts`, react-router, agent-context. TS strict mode. Zero Node.js at serve time.
- **S3 Visual views**: Timeline, Cost (react-chartjs-2 line + budget cap), Guardrail (verdict doughnut + audit table), Memory (internal), Automation (internal). Chart.js only. Read-only.
- **S4 Ops surfaces**: `routes_ops_json.py` (approve/reject/config) calling identical `gw.approve(handler=dispatch_approved_action)` / `profile_editor` functions. Shared `ops_helpers.py` extracted. React UI with two-step confirm. No new write path; approve runs real gateway (audit, dedup, Lớp A→403).
- **S5 Wiring + cleanup**: App.py serves SPA at `/` via catch-all (index.html + client deep-links) with `/api/*` + `/static` precedence (mounted LAST). DELETED: `routes_dashboard.py`, `routes_approvals.py`, `routes_audit.py`, `routes_profile.py` (HTML routers), `src/server/templates/`, htmx static + 5 htmx tests. Coverage guard: every unique edge-case re-asserted in JSON test first. `tests/test_m4_e2e_offline.py` (e2e + grep guard: no Jinja2/TemplateResponse code remains).

## Lằn ranh đỏ (The Invariant)
M4 is a UI/observability layer only. Action Gateway, `classify()`, `needs_interrupt()`, Lớp A/B, audit, budget, dedup, and every write path **UNTOUCHED**. React only READS (JSON, allowlisted) + triggers actions through EXISTING gateway-routed endpoints (approve still `gw.approve(handler=dispatch_approved_action)`). Memory/automation internal-only. FastAPI stays localhost-only/no-auth (auth deferred; JSON API auth-middleware-ready). E2E verified: 785 pytest green, vitest 11, ruff clean.

## Quyết định & vì sao

| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| Commit Vite build to static/ | Zero Node.js at serve time; SPA fully cacheable; avoid build-at-deploy | Larger `.git` size; rebuild only when code changes |
| Chart.js only (no D3) | Lightweight, no force-direct deps, sufficient for budget/timeline/doughnut | No advanced custom visualizations (acceptable, can add later) |
| Ops JSON routes call same dispatcher fns | Eliminate dispatcher copy; one code path for CLI + UI approvals | Tighter coupling (acceptable, both are internal) |
| Delete htmx entirely, not coexist | Clean break; htmx latent bug (config yaml-500) dies; SPA is canonical | No gradual migration (acceptable, all surfaces ported) |
| Internal-only memory/automation views | Prevent external audience leaking per-agent secrets/internal analysis | Dashboard less useful for external reporting (acceptable, external has read-only JSON) |

## Vấp & học được
- **Live-key E2E deferred**: tested JSON endpoints + React surfaces + gateway path via offline/test data; real Linear/SMTP/LangSmith integration still manual. Plan S5 final commit once e2e manual smoke passes.
- **Htmx yaml-500 latent bug**: Config POST that sent YAML form-data triggered 500 on invalid YAML. Died with htmx route; no JSON API equivalent (JSON-only).
- **Coverage guard worked**: Mapped every unique htmx edge (approve/reject/config valid/invalid) to a JSON test before deletion. Zero coverage loss.

## Mở / sang sau
- **Live-key E2E for React SPA**: manual browser smoke (approve flow, config edit, SSE trigger) once S5 lands. Automation welcome.
- **Auth + remote**: still deferred (localhost-only + no-auth). JSON API design is ready; add auth middleware without rewrite.
- **Advanced visualizations**: Dashboard sufficient for MVP; D3/custom layouts deferred pending product feedback.

## Kết quả
✅ 5 slices, all committed (S1 1c0bd75, S2 4c770fb, S3 39713fb, S4 4f025f0, S5 <pending>). 785 pytest green, vitest 11, ruff clean. React SPA fully replaces htmx; guardrail + gateway path byte-stable. Memory/automation internal-only respected. M4 closes the dashboard modernization; next = integrations or multi-user auth.