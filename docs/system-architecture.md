# System Architecture — my-crew

> Kiến trúc kỹ thuật (as-built, v50). Đọc cùng [project-overview-pdr](project-overview-pdr.md)
> (vì sao) + [action-gateway-explainer](action-gateway-explainer.md) (mô hình an toàn) +
> [codebase-summary](codebase-summary.md) (cái gì ở file nào).
> Cập nhật: 2026-07-16.

## 1. Nguyên tắc kiến trúc

1. **Một cửa ghi ra ngoài (autonomy-first + audit, v30)** — mọi mutation external qua Action Gateway:
   - **Default (autonomous):** hành động ngay → audit rationale "trust_mode=autonomous". Speed-first.
   - **Opt-in guarded:** Lớp B queue chờ duyệt. Control-first.
   - **Lớp A (unbreakable):** mất dữ liệu / lộ bí mật → CHẶN cứng, không toggle.
   - Allowlist default-deny (cưỡng chế ở guarded; autonomous chạy như đã-được-duyệt + audit) + PII firewall write-time. Không đường tắt (single-door).
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

### 3.2a Integration health (`src/server/integration_health.py`, v47)
**Health check Docker chủ động** (`_docker_check`): probe `docker info` giới hạn 5s, báo ✓/✗ sạch khi daemon tắt/offline — panel Sức khỏe noti lỗi TRƯỚC khi giao việc deep_agent (no-shell step chạy 0-Docker qua `create_agent`, chỉ needs_shell→deep_agent thì dùng Docker).
**Warm image opt-in** (`prepull_sandbox_image` + `mpm sandbox prepull`): tự tìm `SANDBOX_DEFAULT_IMAGE` ("python:3.12-slim"), present-check no-op → else pull không raise khi daemon tắt.

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

### 3.6 Action Gateway (`src/actions/`, v30–v31)
`action_gateway.py` = cửa duy nhất. `hard_block.py` = Lớp A (chặn cứng, không duyệt được).
Lớp B = phụ thuộc `safety.trust_mode` per-agent:
- **autonomous** (mặc định): tự chạy ngay → audit log rationale "trust_mode=autonomous".
- **guarded** (opt-in): chờ CEO duyệt (`approval_store.py` + `auto_approve_policy.py` chỉ dùng khi guarded).
**Native action types (v31)**: `schedule_update` (agent đổi lịch báo cáo chính mình), `team_task_create`/`team_task_move` (kanban), `gws_write` (Google Sheets/Docs append+create), `academic_search` (read-only). Các handler `*_write.py` khác (jira/confluence/slack/email) — đều gọi qua gateway, không lối tắt.

**Agent creation (v32)**: Template-based create-from-template / crew bootstrap (`src/server/template_create.py`) both build spec server-side from `profiles/templates/`, then go through the same `agent_create.create_agent(spec)` door as wizard — no bypass, new agents land DISABLED (CEO sets .env tokens, then enables on Team page).

### 3.6a Fleet activity audit (v31, v46, v50 UI)
**Hậu kiểm đội**: mọi hành động qua gateway ghi vào `audit.jsonl` (per-agent), `runs.jsonl` (lịch sử chạy), `captures.sqlite3` (chi phí). **Web surface** (`routes_visualize.py` + `visualize_views.py`): GET `/api/company/activity` trả audit rows (allowlist-projected, KHÔNG raw args chứa dữ liệu nhạy), phân trang, filter theo agent/loại. **Ops-chat command** (`ops_company_activity.py`): readonly lệnh mới `company_activity` (LLM tóm tắt hành động đội tuần này → gửi chat nội bộ, KHÔNG external).
**v46 — Actor attribution**: mỗi `AuditEntry` ghi field `actor` (agent `profile_id` hoặc `""` cho lệnh CLI) — 1 choke point `_record` stamp actor trên MỌI outcome branch (allow/deny/dry/dedup). `approvals.actor` (sqlite ALTER migrate-free) cho phép query filter "ai duyệt gì".
**v50 — UI surface**: AuditTable column "Ai thực hiện" render `actor` (or "—" nếu rỗng); CompanyActivity tag "[bởi {actor}]" khi actor≠log-owner (điều phối).

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

### 3.9 AgentRuntime backends (`src/runtime_backends/`, v20–v45)
Tách agent-LOOP khỏi điều phối + an toàn. Backend được chọn PER-STEP qua
`resolve_step_runtime(loaded, step)` (v45 — xem "Định tuyến per-step" cuối §3.9); `resolve_runtime(loaded)`
(chọn theo `agent_runtime:` của cả agent — native|create_agent|deep_agent; default native, kill-switch
`RUNTIME_FORCE_NATIVE`) vẫn là nền cho report + fallback. `NativeGraphRuntime` = graph hiện tại byte-identical.
`ToolCallingRuntime` = tool-calling loop (`create_agent` từ langchain.agents, v28 migrate từ
`langgraph.prebuilt.create_react_agent`) NHƯNG swaps chỉ `run_work` nên deliver (ghi artifact
nội bộ) giữ native; toolset positive read-allowlist + classify shim mọi tool + audience-aware.
**v45**: tier này thêm **file-scratch trong graph-state** (deepagents `StateBackend` +
`FilesystemMiddleware`, tool `execute` bị STRIP + fail-loud guard → tuyệt đối no-shell, KHÔNG host FS,
KHÔNG Docker) để một bước no-shell tự viết/tinh chỉnh báo cáo .md rồi read-back vào kết quả — chạy nhanh,
không cần container.
**v28 DRY**: `community_loop_core.py` tách `record_loop_result` (post-invoke tail: text +
`sum_usage_metadata` + `estimate_cost` + telemetry.record) + `invoke_capped` (cap recursion +
catch `GraphRecursionError`→degrade empty + `_tracing_off()` context manager tắt LangSmith
tracing bằng env-blank, không `callbacks=[]`).

**Ghi chú egress team-step (v20.5)**: team-step deliver ghi artifact nội bộ (`step-<n>.json`); hook
`external_write` để step tự ghi ra ngoài công ty (Slack/Jira) ĐÃ nối qua Action Gateway khi agent bật
`team_step_egress` (mặc định None ⇒ chỉ ghi artifact nội bộ, không egress). Mọi egress công ty — team-step
lẫn report graph — đều đi qua ActionGateway (Lớp A/B + audit); không module nào gọi write-API trực tiếp.

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

**Guardrail phân tầng**: độ-tự-do LLM ↔ độ-cách-ly nghịch nhau — Native (0 tool, chặt nhất) <
ToolCalling (read-only loop + classify shim + graph-state scratch, KHÔNG shell) < DeepAgent (shell
tự do NHƯNG chỉ trong Docker sandbox cách ly + SANITIZE). Role template có `recommended_runtime` prefill.

**Định tuyến per-step (v45, v50 UI) — Docker chỉ khi CẦN shell**: một team-step mặc định chạy
**create_agent** (nhanh, 0 Docker); CHỈ bước khai báo `needs_shell=true` mới leo lên **deep_agent**
(Docker sandbox). `resolve_step_runtime(loaded, step)`:
- `needs_shell=true` → deep_agent; nếu agent không có sandbox config → raise `SandboxUnavailableForShellStep`
  (fail-closed, KHÔNG chạy shell-less ngầm, KHÔNG bao giờ chạy shell trên host).
- `needs_shell=false` trên agent deep_agent-pinned → DROP xuống create_agent (không trả giá container
  cho việc không cần shell).
- còn lại → giữ kind của agent; `None`/kill-switch → native.
- **Fail-closed 2 chiều**: tier nhẹ KHÔNG có shell, nên `needs_shell` do decompose-LLM đặt (như
  `needs_review`) mà bị injection lật: ép `false` chỉ làm một bước-cần-shell FAIL (không RCE); ép `true`
  chỉ leo lên sandbox (an toàn). Không đường nào cấp shell/host mà bước đó chưa được định tuyến tới.
  `needs_shell` được bind vào `decomposition_content_hash` (có điều kiện — chỉ emit khi True → DAG
  all-no-shell hash byte-identical pre-v45) nên CEO-confirm phủ luôn tư thế shell của kế hoạch.
  **v50 UI**: board card `steps_needs_shell` (count bước cần sandbox) trả từ GET `/api/team-tasks/board`, kanban hiện badge "🔒 N sandbox".

**Triết lý moat (chốt qua research v45)**: **shell thật CHỈ chạy trong Docker sandbox**; việc no-shell
(đại đa số: suy luận + đọc + viết báo cáo) chạy **Docker-free** trên create_agent. **Bác host-exec +
shell-approval** (mô hình Hermes/OpenClaw/Claude Code): 3 harness kia an toàn vì CÓ NGƯỜI duyệt lệnh
real-time (con người = sandbox); MPM là fleet **autonomous** (chạy nền, không ai duyệt lúc 3h sáng) +
input **injectable** (web-scrape/handoff) → approval-cho-shell là category-error (write LEGIBLE nên duyệt
được; shell KHÔNG legible). Đo thật: Docker cold-start ~0.4s/step (rẻ, KHÔNG phải nút thắt) → bỏ Docker =
all-cost-no-speed. Egress công ty vẫn CHỈ qua `external_write → ActionGateway` (Lớp A/B).

**deep_team (v43, v50 wizard toggle)**: trong 1 step deep_agent, agent có thể giao trợ lý con IN-SANDBOX qua tool
`task` (`deep_team: true`, cap `deep_team_max_calls` mặc định 3) cho các sub-câu-hỏi ngữ cảnh lớn riêng
biệt; trợ lý con kế thừa CÙNG sandbox backend (không thoát host), token gộp đủ vào chi phí step. Fan-out
RỘNG (nhiều nhánh độc lập) thì dùng native team (decompose→DAG→PIC→review), không phải deep_team.
**v50 UI**: create-wizard IdentityStep toggle "Điều phối trợ lý con" (only shown runtime=deep_agent);
passes `deep_team` + `deep_team_max_calls` → `agent_create` guarded passthrough.

### 3.9b Watcher (wake-gate, v31, perceive-only)
**Không LLM poll — chỉ khi nội dung đổi:** `watchers:` block trong profile.yaml (jira/github/sheets sources). Service mỗi 5 phút poll → normalize → hash. Nội dung KHÔNG đổi = 0 LLM (measured capture store). Đổi → wake 1 lần: dispatcher tạo 1 step team-task pre-built (không LLM phân rã), assigned agent chính nó. **Alerts**: fail ×3 → CEO Telegram báo; no-change >24h → stale alert. Modules: `src/runtime/watcher_store.py`, `watcher_normalize.py`, `watcher_runner.py`, `operator_notify.py`.

### 3.10 Telemetry capture + unified cost (v26, v50 UI)
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
**v50 UI**: GET `/api/team-tasks/{id}/cost` (read-only, allowlist-projected) trả per-step-attempt cost + task total; TeamTaskCost component lazy-expand "Chi phí" trên kanban card.

**v48 — MCP session pool wrapping team-step**: team-step call_tool (mcp_tool) giờ chạy TRONG `_run_with_mcp_pool` (như report/inbox/tasks branches) — 1 subprocess MCP/server dùng lại qua step thay vì spawn node mới per-call. Eliminate spawn-per-call overhead cho office cross-synth (92s→faster).

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
