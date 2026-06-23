# v2 — Agent Profile Design

> Centerpiece của v2. Mỗi agent = một thư mục `profiles/<id>/` gồm 4 file tách concern.
> Quay lại [README](README.md) · liên quan: [architecture](architecture.md) · [roadmap-m1](roadmap-m1.md).

## 3. The agent PROFILE (centerpiece)

Mỗi agent = **một thư mục** `profiles/<agent-id>/` gồm **4 file tách concern** (theo đúng mô hình thật của OpenClaw + Hermes — cả hai dùng *thư mục nhiều file*, KHÔNG nhồi vào một file). Quyết định này thay cho ý "1 file `profile.md`" ở bản nháp đầu — tách concern đúng đắn hơn, dễ sửa từng phần.

| File | Vai trò | Ai viết | Load khi nào |
|---|---|---|---|
| `profile.yaml` | **Config có cấu trúc**: id, bindings (jira/github/slack/confluence), model, thresholds, budget, schedule, reports, safety flags | Người (sửa khi đổi project/threshold) | startup |
| `SOUL.md` | **Persona**: giọng điệu, hành vi, quy ước riêng team → override/prepend system prompt | Người | mỗi run (fresh) |
| `PROJECT.md` | **Context dự án**: team, milestone, quy ước nghiệp vụ ("label p0 = blocker"), nền cho phân tích — TÁCH khỏi persona | Người | mỗi run (đưa vào context) |
| `MEMORY.md` | **Bộ nhớ agent tự ghi**: "sprint trước trễ vì X", "reviewer Y hay nghẽn" → nhớ xuyên report | **Agent tự maintain** (gated qua Action Gateway, xem P8) | mỗi run (đọc); ghi qua Store (M2-P8) |

> Mô hình tham chiếu (verify từ máy): OpenClaw 1 agent = 9-10 file (`SOUL/USER/MEMORY/IDENTITY/AGENTS/TOOLS/HEARTBEAT/DREAMS/WORKFLOW_AUTO.md` + `openclaw.json` registry). Hermes = `SOUL.md` (persona, "loaded fresh each message") + `memories/{MEMORY,USER,IDENTITY}.md` + `config.yaml`. Ta **lấy 4 file cốt lõi, BỎ phần thừa cho PM agent hẹp** (xem phần YAGNI cuối file).

Tokens **KHÔNG** nằm trong profile — `profile.yaml` chỉ *tham chiếu tên env var* (`token_env`); giá trị thật ở `.env` (giữ mô hình env như v1 — user chốt: chưa làm secret store riêng, xem [risks](risks-open-questions.md)).

### 3.1 `profile.yaml` ví dụ (copy-pasteable)

`profiles/acme-web/profile.yaml`:
```yaml
# --- Identity ---
id: acme-web                      # unique, [a-z0-9-], = thư mục .data/agents/<id>/ + thread_id prefix
name: "ACME Web Platform"
enabled: true                     # registry bỏ qua agent disabled
model: minimax/minimax-m2.7       # override OpenRouter model cho riêng agent này

# --- Project bindings (1 agent = 1 project) ---
bindings:
  jira:
    project_key: ACME
    token_env: ACME_JIRA_TOKEN    # TÊN env var (trong .env), không phải token; server đọc khi spawn
    mcp_dist: ~/workspace/jira-cloud-mcp-server/dist/index.js   # optional, default global
  github:
    repo: acme/web-platform       # owner/repo, dùng qua `gh`
  slack:
    report_channel: "#acme-standup"
    stakeholder_channel: "#acme-exec"      # external; route qua Lớp B
    external_channels: ["#acme-exec"]      # channel cần approval; stakeholder PHẢI nằm trong đây
    token_env: ACME_SLACK_BROWSER_TOKEN
  confluence:
    space_key: ACME
    space_id: "123456"
    token_env: ACME_CONFLUENCE_TOKEN
    okr_page_id: "557057"          # optional; OKR no-op nếu trống

# --- Thresholds (per-agent tuning; default = v1) ---
thresholds:
  pr_stale_days: 3
  blocker_label_substring: "blocker"
  okr_behind_threshold: 0.7
  resource_overload_ratio: 1.5
  labor_cost_per_issue: 0          # 0 ⇒ bỏ labor estimate

# --- Budget (per-agent hard-stop) ---
budget:
  monthly_usd: 50
  warn_ratio: 0.8

# --- Schedule (worker đọc; cron/scheduler nội bộ) ---
schedule:
  daily:    "0 9 * * *"            # 09:00 mỗi ngày
  weekly:   "0 17 * * 5"           # 17:00 thứ 6
  resource: "0 9 * * 1"            # 09:00 thứ 2

# --- Report kinds enabled ---
reports: [daily, weekly, okr, resource]

# --- Safety flags (per-agent override; default an toàn) ---
safety:
  dry_run: false
  write_disabled: false
```

`profiles/acme-web/SOUL.md` (persona — người viết; trống ⇒ prompt v1 nguyên vẹn):
```markdown
# Persona — ACME Web Platform agent

Bạn là PM agent cho team ACME Web Platform. Giọng điệu: ngắn gọn, thực tế, ưu tiên hành động.
Internal report: dùng issue key + assignee thật. External (stakeholder): bỏ hết key/PR#/tên người,
chỉ nói tiến độ business-level + rủi ro ở mức "có thể trễ release Q3".

(OVERRIDE/PREPEND vào system prompt ở src/llm/*. KHÔNG đè được lớp PII-sanitization của external —
bài học Phase 5, xem P2 risk.)
```

`profiles/acme-web/PROJECT.md` (context dự án — người viết; nền cho phân tích, tách khỏi persona):
```markdown
# ACME Web Platform — Project Context

- Team: 6 dev, 1 SM (Phúc), release theo quý.
- Milestone gần: Q3 launch (2026-09-30) — ưu tiên cao nhất.
- Quy ước nghiệp vụ:
  - Label "p0" = blocker bất kể tên label (analyzer coi như blocker).
  - >2 PR treo cùng 1 reviewer ⇒ gọi rủi ro "review bottleneck".
- Stakeholder external: CEO + nhà đầu tư (chỉ nhận business summary).
```

`profiles/acme-web/MEMORY.md` (agent TỰ ghi — khởi tạo rỗng; tích luỹ qua các run, ghi qua Store ở M2-P8):
```markdown
# Memory — acme-web (agent-maintained)

<!-- Agent tự append: quyết định/pattern đáng nhớ xuyên report. Vd: -->
- 2026-06-20: Sprint 4 trễ vì phụ thuộc API team Payment — theo dõi cross-team dependency.
- Reviewer "minh-le" thường là điểm nghẽn review PR backend.
```

### 3.2 Field-by-field

| Field | Vai trò | Map tới v1 |
|---|---|---|
| `id` | unique key — thư mục data + prefix `thread_id` + key trong registry | (mới) |
| `name`, `enabled` | hiển thị + bật/tắt ở registry | (mới) |
| `model` | OpenRouter model per-agent | `Settings.openrouter_model` |
| `bindings.jira/github/slack/confluence` | project bindings | `ReportingConfig` fields (`jira_project_key`, `github_repo`, `slack_*`, `confluence_*`) |
| `bindings.*.token_env` | **tên** env var chứa token (không phải giá trị) | `McpServerSpec.env` + `required_env_keys` |
| `bindings.*.mcp_dist` | override dist path per-agent | `McpServerSpec.dist_path` (default global) |
| `thresholds.*` | risk tuning | `ReportingConfig.pr_stale_days / blocker_label_substring / okr_behind_threshold / resource_overload_ratio / labor_cost_per_issue` |
| `budget.*` | hard-stop per-agent | `Settings.monthly_budget_usd / budget_warn_ratio` |
| `schedule.*` | worker scheduler đọc | (v1: launchd plists toàn cục) |
| `reports` | report kinds bật | (v1: CLI flag) |
| `safety.dry_run / write_disabled` | flag per-agent | `Settings.dry_run / write_disabled` |
| `SOUL.md` (file) | persona override prompt | (mới — v1 prompt hardcode) |
| `PROJECT.md` (file) | context dự án đưa vào phân tích | (mới) |
| `MEMORY.md` (file) | bộ nhớ agent tự ghi, xuyên report | (mới — cần Store M2-P8) |

> Synthesis nguồn (verify từ máy): `profile.yaml` config = OpenClaw `openclaw.json` agents.list[] (id/model/bindings); `SOUL.md` = Hermes/OpenClaw SOUL.md (persona freeform); `PROJECT.md` + `MEMORY.md` = tách concern kiểu OpenClaw `USER.md`/`MEMORY.md`. **Adapt cho PM-agent hẹp, không copy nguyên.**

### 3.4 YAGNI — file của reference mà ta KHÔNG lấy

OpenClaw 1 agent có 9-10 file; ta chỉ lấy 4. Bỏ (over-engineering cho PM agent dọc):
- `USER.md` (facts về người dùng) — PM agent không cần persona hoá quanh 1 người; gộp ý vào `PROJECT.md` nếu cần.
- `IDENTITY.md` (tên/avatar/origin-story agent) — gộp vào `SOUL.md`.
- `AGENTS.md` (bootstrap instructions kiểu CLAUDE.md) — không cần; worker biết cách load.
- `TOOLS.md` (tham chiếu script/CLI) — ta dùng tool cố định (MCP+gh), không cần.
- `HEARTBEAT.md` / `DREAMS.md` / `WORKFLOW_AUTO.md` — cơ chế polling/dreaming của personal assistant; ta dùng `schedule` trong `profile.yaml`.
