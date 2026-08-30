# Control-plane API (v1)

`POST/GET /api/control-plane/*` — a stable HTTP contract for a caller **outside** the
web SPA: a script, a cron job, a CLI, or another agent. One door for "giao việc / xem
trạng thái / xem toàn cảnh đội" without depending on any SPA-internal route shape.

Every response carries a top-level `"v": 1`. A future breaking change bumps this
number — a caller pinning `v == 1` is safe from silent field drift.

The same logic is also reachable **in-process** (no HTTP) via `mpm crew assign|status|
overview` — see [CLI](#cli-mpm-crew). Both surfaces call the exact same functions
(`my_crew/agent/ops_assign_team_task.py`'s `preview_assign_team_task`/
`run_assign_team_task`, and `my_crew/server/control_plane_views.py`'s
`build_task_status`/`build_overview`), so they cannot drift apart in behavior — only in
transport.

**Auth**: `/api/control-plane/*` is under `/api/*`, which `AuthMiddleware` protects
whenever web auth is enabled (`WEB_AUTH_PASSWORD_HASH` set) — same posture as the SPA,
no separate credential. On a bare localhost dev install (auth disabled), it is open
exactly like every other `/api` route.

**Read-only** except `POST /delegate`. No route here opens a SQLite file directly —
every read goes through `my_crew/server/control_plane_views.py`, which itself only
calls existing store APIs (`TeamTaskStore`, `CaptureStore`, `ApprovalStore`, the
registry, `agent_state_reader`, `integration_health`).

## `POST /api/control-plane/delegate`

Giao việc cho đội. Hash-bind: một preview mint một `plan_hash` gắn với đúng nội dung kế
hoạch đó; confirm chỉ thành công khi hash CÒN khớp (TOCTOU-proof — kế hoạch bị đổi hoặc
đã xác nhận rồi thì confirm trả 409, không âm thầm chạy kế hoạch cũ).

Two call shapes:

### 1. Preview (step 1 of the default 2-step flow)

Request:

```json
{ "brief": "Viết báo cáo tuần cho khách hàng ACME", "room_id": "optional-room-id" }
```

Response `200`:

| Field | Type | Meaning |
|---|---|---|
| `v` | int | Contract version (`1`) |
| `task_id` | string | Minted task id — echo back to confirm |
| `plan_hash` | string | Minted plan hash — echo back to confirm |
| `preview_text` | string | Human-readable plan preview |
| `confirmed` | bool | `true` only if company-wide autopilot already auto-confirmed inside preview |
| `route_mode` | string | Routing decision (e.g. `sprint`, `graph`) |

```bash
curl -s -X POST http://localhost:8765/api/control-plane/delegate \
  -H 'content-type: application/json' \
  -d '{"brief": "Viết báo cáo tuần cho khách hàng ACME"}'
```

### 2. Confirm (step 2 of the default 2-step flow)

Request:

```json
{ "task_id": "t-...", "plan_hash": "...", "confirm": true }
```

Response `200`: `{ "v": 1, "task_id": "...", "confirmed": true, "text": "..." }`

```bash
curl -s -X POST http://localhost:8765/api/control-plane/delegate \
  -H 'content-type: application/json' \
  -d '{"task_id": "t-abc123", "plan_hash": "h-abc123", "confirm": true}'
```

### 3. One-step (`confirm: true` on the first call — no `task_id`)

Request: `{ "brief": "...", "confirm": true }` — preview THEN immediately confirm the
just-minted hash in the same request. Response is the union of the preview and confirm
fields above (`confirmed: true`, `text` present).

```bash
curl -s -X POST http://localhost:8765/api/control-plane/delegate \
  -H 'content-type: application/json' \
  -d '{"brief": "Viết báo cáo tuần cho khách hàng ACME", "confirm": true}'
```

### Errors

| Status | When |
|---|---|
| `400` | empty/missing `brief`, `brief` over 4000 chars, `task_id` given without `plan_hash`, or the preview itself rejects the brief (e.g. no route staff available) |
| `409` | confirm called with a stale/mismatched `plan_hash` (plan changed or already confirmed) |

### Audit

Every confirm (2-step or 1-step) appends one row to the shared hash-chained audit trail
(`team_tasks_root()/audit/audit.jsonl` — the same file `mpm agent audit --team verify`
checks), tagged `actor: "control_plane_api"`, `action_type:
"control_plane_delegate"`, `tool: "control_plane:delegate:confirm"` or `:one_step`.
Best-effort: an audit-append failure never blocks the underlying dispatch, which has
already committed.

## `GET /api/control-plane/tasks/{task_id}`

Trạng thái hợp nhất một việc — state, steps, cost, delivery, route.

```bash
curl -s http://localhost:8765/api/control-plane/tasks/t-abc123
```

Response `200`:

| Field | Type | Meaning |
|---|---|---|
| `v` | int | `1` |
| `task_id`, `title` | string | Task identity |
| `state.status` | string | `open`/`running`/`done`/`stalled`/... |
| `state.pic_id` | string | Người phụ trách (PIC) |
| `state.room_id`, `state.created_at` | string | |
| `steps[]` | array | `step_id`, `title`, `assigned_to`, `status`, `step_type`, `deps`, `cost_usd` |
| `cost.total_cost_usd`, `cost.total_input_tokens`, `cost.total_output_tokens` | number | |
| `cost.steps[]` | array | per-step cost/token breakdown |
| `delivery.status`, `delivery.attempts`, `delivery.final_summary` | | |
| `route.mode`, `route.source`, `route.reason` | string | |

`404` when the task id does not exist.

## `GET /api/control-plane/overview`

4-block fleet snapshot. **Each block fail-degrades independently** — one broken store
(a corrupt approvals db, a dead integration probe) only empties its own block, never
sinks the other three.

```bash
curl -s http://localhost:8765/api/control-plane/overview
```

Response `200`:

| Field | Type | Meaning |
|---|---|---|
| `v` | int | `1` |
| `registry.agents[]` | array | `agent_id`, `enabled`, `name`, `domain`, `last_run` |
| `health.coordinator_ok` | bool | Coordinator heartbeat alive |
| `health.integrations[]` | array | `id`, `label`, `ok` per configured integration |
| `queue.depth` | int | Dispatchable tasks |
| `queue.running` | int | Of those, currently running |
| `queue.stalled` | int | Stalled tasks |
| `approvals.pending_total` | int | Total pending approvals across all agents |
| `approvals.pending_by_agent` | object | `{ agent_id: count }` |

## CLI: `mpm crew`

Same logic, in-process (no HTTP round-trip, no auth needed — it runs as the local
user):

```text
mpm crew assign "<mô tả việc>" [--room <room_id>] [--yes]
mpm crew assign --confirm <task_id> <plan_hash>
mpm crew status <task_id>
mpm crew overview
```

- `mpm crew assign "<brief>"` — preview only (2-step default); prints the exact
  `mpm crew assign --confirm <task_id> <plan_hash>` command to run next.
- `mpm crew assign "<brief>" --yes` — one-step: preview then immediately confirm.
- `mpm crew assign --confirm <task_id> <plan_hash>` — step 2 of the 2-step flow.
- `mpm crew status <task_id>` — prints the unified status (state/steps/cost/delivery).
- `mpm crew overview` — prints the 4-block fleet snapshot.

`mpm crew init [crew]` (pre-existing onboarding command, unrelated to this contract)
still works unchanged.

## Design notes

- **No database merge.** This is a thin read-only aggregation + a delegate wrapper over
  the SAME stores/functions the SPA already uses — not a new source of truth. See
  `plans/reports/architecture-gap-brainstorm-260830-1311-zalo-business-fleet-report.md`
  (decision D2).
- **Backend identifiers are English**; user-facing strings (error details, CLI output)
  are Vietnamese, matching the rest of the product.
- Route overlap with equivalent SPA endpoints (`routes_office_assign.py`,
  `routes_outputs.py`) is accepted for now (YAGNI) — this contract exists for callers
  that cannot depend on SPA-internal route shapes, not to replace them.
