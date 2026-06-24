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

### P7 — Web dashboard (HTMX hoặc Streamlit)

- **Goal**: dashboard surface mọi thứ ops cần.
- **Key changes** (surface):
  - Agent list + status (running/idle/error) — từ registry + worker heartbeat.
  - Cost vs budget per-agent — đọc `.data/agents/<id>/budget/`.
  - Recent audit — đọc per-agent audit JSONL (reuse `audit_log.query`).
  - **Pending Lớp B approvals — approve/reject ngay trên UI** (gọi P5 resume / approval_store).
  - Config view/edit — render `profile.yaml` + xem 3 file Markdown; save lại (validate trước khi ghi). `MEMORY.md` read-only trên UI (agent tự ghi).
  - Trigger report on-demand — gọi `/api/agents/{id}/trigger`.
- **Files touched**: new `src/server/templates/` (HTMX) hoặc `src/server/dashboard.py` (Streamlit); reuse P6 API.
- **Acceptance**: từ UI thấy 2 agent, cost mỗi cái, approve 1 pending Lớp B → Slack post live, sửa 1 threshold → `profile.yaml` update → run kế tiếp dùng giá trị mới.
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

---

## Features chèn vào M2 (từ [feature-proposals](feature-proposals.md))

- **B2 Cost metrics API** → P6 (`GET /api/agents/{id}/metrics`, nền `budget_tracker`).
- **A2 Auto-extraction memory** → P8 (LLM trích fact → `MEMORY.md` qua Store; write gated qua gateway).

Phần lớn đề xuất còn lại (cross-agent memory, skill library, MCP gateway, workflow automation) → **M3**, xem [feature-proposals](feature-proposals.md).
