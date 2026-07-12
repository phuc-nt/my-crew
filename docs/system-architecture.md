# System Architecture — my-crew

> Kiến trúc kỹ thuật (as-built, v27). Đọc cùng [project-overview-pdr](project-overview-pdr.md)
> (vì sao) + [action-gateway-explainer](action-gateway-explainer.md) (mô hình an toàn) +
> [codebase-summary](codebase-summary.md) (cái gì ở file nào).
> Cập nhật: 2026-07-12.

## 1. Nguyên tắc kiến trúc

1. **Một cửa ghi ra ngoài** — mọi mutation external qua Action Gateway (allowlist
   default-deny + Lớp A hard-block). Không đường tắt.
2. **Process isolation** — mỗi agent chạy trong subprocess riêng (data-dir/gateway
   riêng). KHÔNG orchestration graph xuyên process (khóa từ v12).
3. **Điều phối bằng ticker, không long-running orchestrator** — coordinator là một
   pseudo-kind chạy poll-ngắn/1-hành-động/thoát; trạng thái đội sống trong store + lease,
   không trong bộ nhớ một process dài hạn.
4. **State là SQLite (WAL), primitives** — không ORM; graph state chỉ chứa primitives
   (checkpoint-safe); retry = attempt mới, không resume mid-graph.
5. **Fail-degrade cho quan sát** — realtime events/heartbeat lỗi không bao giờ chặn
   pipeline chính.

## 2. Sơ đồ tổng thể

```
   CEO ──(web / Telegram)──►  FastAPI (src/server) ──► SQLite stores  ◄── Coordinator daemon
        giao việc/duyệt          routes_*.py              (.data/)          (src/runtime/service.py)
                                    │  SSE                    ▲                    │ mỗi phút: tick
                                    ▼                         │                    ▼
                              React SPA (web/)          team_tasks.sqlite3   spawn worker subprocess
                              màn Văn phòng 3D          office_room.sqlite3   (src/runtime/worker.py)
                                                        approvals/dedup.db          │
                                                                              LangGraph step graph
                                                                              (src/agent/*_graph.py)
                                                                                    │
                                                                          Action Gateway (src/actions)
                                                                                    │
                                                                     Jira · Confluence · Slack · Email
```

## 3. Các thành phần

### 3.1 Web server (`src/server/`)
FastAPI + 17 routers (`app.include_router`). Serve React SPA tĩnh từ
`static/app/`. SSE store-tail cho feed realtime (`routes_office_stream.py`). Auth
middleware: localhost + chưa đặt password ⇒ auth OFF; bind LAN bị từ chối trừ khi bật
web-auth (`assert_bind_safe`). `office_event_projection.py` = **PII firewall** (allowlist
theo kind AT WRITE TIME — room event không chứa nội dung tự do).

### 3.2 Coordinator daemon (`src/runtime/service.py`)
Vòng lặp mỗi phút: đọc registry, chạy scheduler (báo cáo định kỳ) + **team-tick**
(điều phối đội). Ghi `coordinator.heartbeat` mỗi vòng (health API + banner đỏ đọc file
này). Là process TÁCH BIỆT web app — web không tự dispatch việc.

### 3.3 Worker (`src/runtime/worker.py`)
Mỗi lần ticker cần chạy 1 bước việc → spawn 1 worker subprocess (`kind=team-step`) với
`--task-id --step-id --attempt-id`. Worker chạy LangGraph step graph rồi thoát. Isolation
per-agent (profile/data-dir/gateway riêng). Cũng chạy các kind khác: report, ops-alert,
milestone-mirror.

### 3.4 Team-task store + lease (`src/runtime/team_task_store.py`)
SQLite WAL, single source of truth cho state đội. **Reserve-before-spawn + lease**:
`reserve_step` cấp `attempt_id` UUID + ghi `child_pid`/`lease_expires_at`; ticker chỉ
re-reserve khi lease hết hạn AND chưa có outcome artifact. Terminal write mang `attempt_id`
→ một worker cũ (zombie) ghi trễ thành no-op, không corrupt attempt mới.

### 3.5 Agent graphs (`src/agent/`)
- `coordinator_graph.py` + `coordinator_nodes/` — ticker: chọn task, verify hash, dispatch
  bước sẵn sàng (cap song song 2), chèn soát chéo, escalate.
- `team_task_graph.py` — chạy 1 bước: `perceive → work → (self_check | recover→work) →
  (deliver | rework→self_check)`. Consult đồng nghiệp trong `work`.
- `task_decomposition.py` — chia việc ≤7 bước; validate (acyclic/authz/PIC); hash canonical.
- `review_graph.py` — soát chéo (peer review).
- `ops_*.py` — lệnh CEO: giao việc (`ops_assign_team_task`), chỉnh việc
  (`ops_adjust_team_task`), chat quản trị (`ops_chat`).

### 3.6 Action Gateway (`src/actions/`)
`action_gateway.py` = cửa duy nhất. `hard_block.py` = Lớp A (chặn cứng, không duyệt được).
Lớp B = chờ CEO duyệt (`approval_store.py` + trust ladder `auto_approve_policy.py`).
`*_write.py` = handler cụ thể (jira/confluence/slack/email) — đều gọi qua gateway.

### 3.7 Domain packs (`domain-packs/`)
Kiến trúc pluggable: `pm-pack` (mặc định), `hr-pack`, `office-pack`, `admin-pack`. Mỗi
pack = graphs + tools + analyzers + write_handlers + allowlist. `src/packs/registry.py`
discover pack từ filesystem. Lõi (`src/`) không chứa logic domain.

### 3.8 Memory provider seam (`src/memory/`, v19)
`resolve_memory_text(loaded)` là MỘT cửa mọi prompt path lấy memory text (thay 6 call-site
đọc `loaded.memory`). Provider chọn qua `memory:` block trong profile.yaml: `static`
(MEMORY.md verbatim, mặc định, byte-identical) | `kioku` (my-kioku subprocess — HOÃN v19.5,
chọn nay raise rõ). Memory tiếp tục vào INTERNAL user-msg qua `build_context_block`
(external nhận 0 byte — red line giữ). Workspace mỗi agent thêm `vault/` (reserved kioku)
+ `skills/` (per-agent, body wrap `format_internal_content`, không shadow pack skill).
Capability block auto-gen (`capability_block.py`) cũng INTERNAL-only cùng path.

### 3.9 AgentRuntime backends (`src/runtime_backends/`, v20–v28)
Tách agent-LOOP khỏi điều phối + an toàn. `resolve_runtime(loaded)` chọn backend theo
`agent_runtime:` (native|create_agent|deep_agent; default native, kill-switch
`RUNTIME_FORCE_NATIVE`). `NativeGraphRuntime` = graph hiện tại byte-identical.
`ToolCallingRuntime` = tool-calling loop (`create_agent` từ langchain.agents, v28 migrate từ
`langgraph.prebuilt.create_react_agent`) NHƯNG swaps chỉ `run_work` nên deliver (ghi artifact
nội bộ) giữ native; toolset positive read-allowlist + classify shim mọi tool + audience-aware.
**v28 DRY**: `community_loop_core.py` tách `record_loop_result` (post-invoke tail: text +
`sum_usage_metadata` + `estimate_cost` + telemetry.record) + `invoke_capped` (cap recursion +
catch `GraphRecursionError`→degrade empty + `_tracing_off()` context manager tắt LangSmith
tracing bằng env-blank, không `callbacks=[]`).

**Ghi chú egress team-step (đính chính, 2026-07-11)**: team-step deliver hiện CHỈ ghi artifact
nội bộ (`step-<n>.json`) — hook `external_write` để step ghi ra ngoài công ty (Slack/Jira) đã
thiết kế nhưng CHƯA nối (`deps.external_write=None`). Egress công ty ĐANG đi qua **report graph**
(daily/weekly/okr/resource) vốn wire ActionGateway đầy đủ. Vậy ToolCalling/Native team-step KHÔNG
egress → "invariant #1 giữ" đúng theo nghĩa team-step không có đường ra ngoài, KHÔNG phải "output
đi qua gateway". Nối `external_write→gateway` là tính năng để step tự egress (kế hoạch v20.5).

**DeepAgentRuntime (v20.5–v27)**: `create_deep_agent` chạy shell CHỈ trong sandbox (`fake` test |
`docker` self-hosted, token-free, không mount host). Loop cap `runtime_loop_limit` per-runtime.
**V27 hardening**: (1) **Input sanitization** — 5 channels (persona/project/memory/capability/
handoff) được SANITIZED qua LLM pass trước sandbox để loại token/issue-key/tên-người/secret; nếu
sanitize fail → network OFF (fail-closed AND-gate với opt-in network). (2) **Container hardening**
— cap_drop=ALL, no-new-privileges, non-root user=nobody, network-off-default, mem_limit/pids_limit/
read_only/tmpfs (HARD group fail-closed, DEGRADABLE group với warning). (3) **Reaper** — new
`sandbox_reaper.py` runs mỗi tick để xóa container orphaned (SIGKILL'd worker), tuổi > lease_TTL
+ grace. (4) **Cost robustness** — `estimate_cost` reject nan/inf prices (→None, never poison budget
cap). Sanitizer là trust boundary cho network-safe deep_agent; wizard emits `{kind, sandbox:{provider}}`.

**Guardrail phân tầng (v20.5–v27)**: độ-tự-do LLM ↔ độ-cách-ly nghịch nhau — Native (0 tool, chặt
nhất) < ToolCalling (read-only loop + classify shim) < DeepAgent (shell tự do nhưng trong Docker
sandbox cách ly + SANITIZE). Team-step egress công ty qua `external_write → ActionGateway` (Lớp A/B).
User chọn runtime khi tạo agent; role template có `recommended_runtime` prefill.

### 3.10 Telemetry capture + unified cost (v26)
Mỗi team-step attempt ghi telemetry vào `captures.sqlite3` (17 columns: attempt_id, task_id,
step_id, agent_id, engine, status, step_type, review_round, cost_usd, cost_source, input_tokens,
output_tokens, started_at, ended_at, duration_ms, error, ts). WAL+busy_timeout tương tự
team_task_store. Hook `run_team_step` thu thập lúc step kết thúc (best-effort, log WARNING
nếu fail, không tắc quy trình). **INTERNAL state — không qua gateway** (`capture_db_path()` trong
team_task_paths.py). Unified cost across 3 engines: create_agent + deep_agent dùng
`config/model_prices.yaml` (mô hình đặt giá chỉnh sửa được, ví dụ placeholders minimax/qwen),
estimate cost = Σ tokens × per-model price, column `cost_source = 'estimated' | 'exact'`.
Remember-node extends team-step: deliver→remember→END (CostedMemoryExtractor ghi facts vào
MEMORY.md, gộp cost LLM vào captured step cost), gated on delivered + internal + not-dry-run.
Modules: `src/runtime/capture_store.py`, `src/llm/model_pricing.py`, `src/runtime/step_telemetry.py`.

### 3.11 Frontend (`web/src/`)
React 19 + Vite. Màn chính **Văn phòng** (`views/office-unified/`): 3 cột phòng-việc /
hoạt-động / kết-quả + panel 3D (`views/office-3d/`, react-three-fiber). Reducer sự kiện
(`agent-office-state.ts`) biến SSE stream → trạng thái bàn. Build dist commit vào
`src/server/static/app/`.

## 4. Luồng dữ liệu chính: giao 1 việc

1. CEO gõ `@noi-dung <việc>` → `routes_office_assign` → `ops_assign_team_task.preview` →
   1 LLM call phân rã → validate code-side → lưu draft (status `planning`) + hash.
2. CEO xác nhận (hoặc auto-confirm) → `confirm_plan(hash)` TOCTOU-proof → task `open`.
3. Coordinator daemon tick kế: đọc task, `_verify_plan_hash` (chống tamper), dispatch
   bước sẵn sàng → spawn worker.
4. Worker chạy step graph → `deliver` ghi artifact `step-<n>.json` + append office event.
5. SSE đẩy event → SPA cập nhật feed/3D realtime. Bước done `needs_review` → ticker chèn
   soát chéo. Bước cuối (PIC) xong → task done.
6. Bước "ghi ra ngoài" (nếu có) → Action Gateway → Lớp B chờ CEO duyệt ở tab Duyệt.

## 5. Lưu trữ

| File (.data/) | Nội dung |
|---|---|
| `team_tasks.sqlite3` | Task đội + steps + lease state |
| `office_room.sqlite3` | Office events (feed realtime, projected PII-safe) |
| `captures.sqlite3` | Team-step telemetry: attempt_id, task_id, step_id, agent_id, engine, cost_usd, tokens (WAL, INTERNAL-only) |
| `approvals.db` | Hàng đợi Lớp B |
| `dedup.db` | Chống gửi trùng |
| `checkpoints.db` | LangGraph checkpoint (report graphs; team graph KHÔNG checkpoint) |
| `artifacts/team-tasks/<id>/step-<n>.json` | Kết quả bàn giao từng bước (artifact viewer đọc) |

User-data (gitignored): `.data/`, `registry.yaml`, `company.yaml`, `profiles/<id>/`
(gồm `vault/` + `skills/` per-agent, v19), `company-docs/`.

## 6. Bất biến an toàn (đừng phá khi refactor)

Xem [codebase-summary.md](codebase-summary.md) "THE INVARIANT" + HANDOVER §5. Tóm tắt:
gateway-only egress · Lớp A/B · PII firewall write-time · hash-bind confirm · process
isolation · registry user-data.
