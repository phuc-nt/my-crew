# v2 — Milestone M2: Web UI + LangGraph upgrades

> Quay lại [README](README.md) · trước: [roadmap-m1](roadmap-m1.md) · sau: [feature-proposals (M3)](feature-proposals.md).

## 6. Milestone M2 — Web UI + LangGraph upgrades

> Mục tiêu M2: web dashboard quản lý + 3 nâng cấp LangGraph (interrupt / streaming / Postgres+Store). Xây trên M1 đã chạy.

### P5 — Graph-native interrupts cho Lớp B (checkpoint-serialized)

- **Goal**: chuyển Lớp B approval từ gateway-queue sang **LangGraph interrupt** — graph pause tại node, UI hỏi, resume deterministic nhờ checkpoint.
- **Key changes**:
  - Hiện tại Lớp B **KHÔNG** phải graph interrupt: `action_gateway.py:193` gọi `needs_interrupt`, trả `pending_approval` + `approval_store` + `cli approve` (verified — graph không có `interrupt()`). P5 thêm node interrupt thật trong graph (LangGraph `interrupt()` + resume bằng `Command`).
  - Reference: DeerFlow `clarification_middleware.py` (interrupt qua `Command(goto=END)`) — adapt cho approve-to-execute.
  - Lớp A **không đổi** — vẫn hard-deny ở gateway trước LLM. Chỉ Lớp B chuyển sang interrupt.
- **Files touched**: graph builders (4) + gateway (Lớp B path) + một resume handler.
- **Acceptance**: external report → graph pause tại interrupt → state checkpoint → approve qua API → graph resume → Slack post live. Reject → graph dừng sạch, audited.
- **Risks**:
  - **Coexist vs replace** (open question §9): interrupt cần graph đang chạy để resume; approval async (người duyệt sau vài giờ) cần checkpoint bền + worker resume được. Mitigation: interrupt **augment** queue ở P5 (cả hai path tồn tại), quyết replace ở P8 khi Postgres checkpointer bền multi-process.
  - Resume xuyên process: cần checkpoint shared → phụ thuộc P8 Postgres cho production multi-machine. M2 sandbox: cùng worker resume từ SqliteSaver.

### P6 — Streaming + FastAPI service

- **Goal**: FastAPI backend; stream token/event của agent đang chạy ra UI qua SSE.
- **Key changes**:
  - `src/server/app.py` (FastAPI): routes `/api/agents`, `/api/agents/{id}/status`, `/api/agents/{id}/trigger`, `/api/agents/{id}/stream` (SSE).
  - LangGraph streaming (`graph.stream(...)` mode messages/events) → bridge sang SSE. Reference: DeerFlow `StreamBridge`/`thread_runs.py`.
- **Files touched**: new `src/server/{app,stream}.py`; reuse worker + registry.
- **Acceptance**: trigger report từ API → SSE phát event perceive→analyze→compose→deliver live; client thấy progress.
- **Risks**: SSE + worker process boundary — service phải đọc stream từ worker đang chạy (queue/pubsub nội bộ). Mitigation M2: service chạy graph in-process cho on-demand trigger (không qua subprocess) để stream trực tiếp; scheduled run vẫn qua worker.

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
