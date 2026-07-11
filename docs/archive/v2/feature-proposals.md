# v2 — Feature Proposals (từ research 3 repo) + Milestone M3

> Quay lại [README](README.md) · nền: [roadmap-m1](roadmap-m1.md), [roadmap-m2](roadmap-m2.md).
>
> Đề xuất tính năng rút từ khảo sát **DeerFlow 2.0 + Hermes-agent + OpenClaw/Pi.dev** (cùng phương pháp
> đã dùng khi thiết kế bộ file profile). Mỗi đề xuất gắn **[effort]** + **milestone phù hợp**. Những cái
> easy/M1-M2 đã chèn vào roadmap M1/M2; phần lớn (cross-agent, MCP gateway, workflow) gom thành **M3 mới**.

## Cách đọc

- Đã verify cơ chế từ source 3 repo (path + mechanism trong [research notes](../research/)).
- Nguyên tắc giữ nguyên từ v1: **YAGNI** — PM agent dọc, KHÔNG biến thành personal assistant đa năng.
  Mỗi nhóm có cả "BỎ" (over-engineering) lẫn "lấy".

## Nhóm A — Memory / Knowledge

**Tham chiếu:** DeerFlow LLM-extract→JSON per-user/agent + inject top-15 vào `<memory>` tag (debounced
queue 30s); Hermes "memory dreaming" = background-review fork mỗi turn; OpenClaw = agent tự gọi `memory` tool.

| Đề xuất | Effort | Phase | Lý do |
|---|---|---|---|
| **A1. Memory injection vào report preamble** — đọc `MEMORY.md` → inject top-K fact liên quan vào `<pm_context>` trước khi compose | easy | **M1-P2** (đã có trong profile loader) | Report giữ nhất quán với quyết định cũ; "quên đã chốt X" giảm. |
| **A2. Per-project auto-extraction** — sau mỗi report run, LLM trích fact (categories: `stakeholder_preference`/`project_risk`/`blocker`/`deadline`/`team_context`), append `MEMORY.md` qua Store | medium | **M2-P8** (cần Store + write gated qua gateway) | Bắt quyết định organically, không cần tag tay. |
| **A3. Cross-agent memory share** — 2 agent cùng project đọc fact của nhau (RO sibling, WO self) | hard | **M3** | Nhất quán team; chỉ giá trị nếu thật sự N-agent/1-project. |

**BỎ (YAGNI):** Vector DB (JSON fact + LLM semantic match đủ cho PM); "memory dreaming" mỗi turn (PM agent
không cần tự-phản-tỉnh liên tục — extract lúc tạo report là đủ).

## Nhóm B — Observability / Cost / Tracing

**Tham chiếu:** DeerFlow `RunEventStore` (memory/jsonl/sql) + dual LangSmith+Langfuse + `TokenUsageMiddleware`
(tiktoken/char fallback); Hermes structured JSON log; OpenClaw per-workspace history.

| Đề xuất | Effort | Phase | Lý do |
|---|---|---|---|
| **B1. Structured run-event log (.jsonl)** — mỗi run ghi event `{ts, event_type: perceive\|analyze\|compose\|deliver, metadata}` vào `.data/agents/<id>/runs.jsonl` | easy | **M1-P3** (cạnh audit per-agent) | Debug "report bỏ sót X vì sao"; nền cho cost + replay. Zero dep ngoài. |
| **B2. Per-agent cost metrics API** — token counter (tiktoken + char fallback kiểu DeerFlow) → `GET /api/agents/{id}/metrics` (total tokens, cost, by-model) | easy→medium | **M2-P6** (cạnh FastAPI) | "Report project X tốn bao nhiêu?" — câu hỏi thật của org. Đã có `budget_tracker` làm nền. |
| **B3. Run replay / time-travel** — click "replay run" → re-execute với checkpoint state, edit prompt giữa chừng | hard | **M3** | Debug "vì sao parse sai Jira ticket"; phức tạp vì PM agent pull live data (cần mock/re-fetch). |
| **B4. Tracing (LangSmith/Langfuse) opt-in** — callback ở graph root | easy | **M3 (opt-in)** | Chỉ thêm khi cần trace LLM sâu; YAGNI cho M1/M2 (run-event log đủ). |

**BỎ:** Dual-provider tracing mặc định (overkill); real-time metrics dashboard (M3 — structured event đủ cho M1/M2).

## Nhóm C — Tool / Skill / Plugin Extensibility

**Tham chiếu:** DeerFlow SKILL.md (YAML frontmatter `name/description/allowed-tools` + slash activation +
ZIP installer validate path) + deferred-tool MCP promotion; Hermes plugin discovery (`register(ctx)` scan dir);
OpenClaw plugin-sdk + channel-contract.

| Đề xuất | Effort | Phase | Lý do |
|---|---|---|---|
| **C1. PM skill library (bundled SKILL.md)** — 3-5 skill: `fetch-jira-epics`, `parse-github-labels`, `estimate-effort`, `flag-risk`. Markdown instructions, agent activate `/skill` hoặc auto-load theo context | easy | **M3** | Chuẩn hoá cách agent tiếp cận task PM; bớt prompt-engineering, agent nhất quán. |
| **C2. Custom skill upload per project** — user nâng `.skill` ZIP (template Jira label scheme, risk taxonomy riêng), validate path/symlink, extract `.data/agents/<id>/skills/custom/` | medium | **M3** | Tuỳ biến org-specific không cần fork (vd "team dùng RISK-L1/L2/L3"). |
| **C3. MCP tool gateway cho PM integrations** — Linear/Asana/Monday đăng ký làm MCP server; deferred-tool promotion (`tool_search`) | hard | **M3** | v1 chỉ Jira/GitHub; v2 nên integrations-agnostic qua MCP contract. |

**BỎ:** Plugin SDK đầy đủ (quá rộng — skill ZIP đủ); skill version-control/rollback (audit run-event là đủ).

## Nhóm D — Channel / Scheduling / Automation

**Tham chiếu:** DeerFlow `Channel` abstract + `ChannelManager`/`MessageBus` (7 kênh, event-driven, no cron);
Hermes `cronjob_tools` (agent tạo/pause/trigger job) + threat-scan cron prompt; OpenClaw **heartbeat per-agent**
(`heartbeat.every` + `HEARTBEAT.md` = markdown task list, "workflow as data").

| Đề xuất | Effort | Phase | Lý do |
|---|---|---|---|
| **D1. Per-agent scheduler (cron từ `profile.yaml`)** — `schedule:` đã có trong profile; service đọc + trigger run theo lịch | easy | **M1-P3** (đã trong service spec) | "Weekly standup tự động" — use case lõi. Thay launchd plist toàn cục của v1. |
| **D2. Multi-channel report delivery** — sau report, chọn kênh (Slack/Confluence/GitHub Discussion/email) per project | medium | **M3** | PM report cho người; engineering dùng Slack, exec dùng email. Adapt subset của DeerFlow ChannelManager. |
| **D3. Workflow automation (state machine YAML)** — "on new p0 bug: fetch detail → analyze impact → flag stakeholder → create follow-up" express `automation.yaml`, agent interpret | hard | **M3** | Org có workflow lặp; YAML đơn giản hơn DSL. Cẩn trọng: đây là **write authority mở rộng** → mọi action phải qua Lớp A/B (xem [risks](risks-open-questions.md)). |

**BỎ:** Workflow DSL kiểu Airflow DAG (PM agent nhẹ — markdown task list/YAML đủ); inbound webhook (v1 không cần;
M3 nếu integration ngoài đòi). Multi-channel inbound (cần Slack bot app — đã defer ở roadmap v1).

## Top recommendations (xếp hạng value/effort cho roadmap)

1. **A1 Memory injection** [easy, M1-P2] — report tham chiếu context cũ; ~ít logic thêm. **HIGH.**
2. **B1 Run-event log** [easy, M1-P3] — nền debug + cost + replay; zero dep. **HIGH.**
3. **D1 Per-agent scheduler** [easy, M1-P3] — đã trong profile `schedule`; "auto weekly standup". **HIGH.**
4. **B2 Cost metrics API** [easy-medium, M2-P6] — "report tốn bao nhiêu"; có `budget_tracker` làm nền. **MEDIUM.**
5. **A2 Auto-extraction memory** [medium, M2-P8] — bắt quyết định organically; cần Store. **MEDIUM.**
6. **C1 PM skill library** [easy, M3] — chuẩn hoá; 5 file SKILL.md. **MEDIUM.**
7. **C3 MCP PM-integration gateway** [hard, M2-M3] — Linear/Asana future-proof. **LOW giờ, HIGH sau.**

## Milestone M3 — Extensibility + automation (phác thảo)

> Sau M1 (multi-agent core) + M2 (UI + LangGraph). M3 = mở rộng năng lực, KHÔNG mở write-authority mà không
> qua Action Gateway. Chỉ phác thảo — chi tiết hoá khi M1/M2 xong.

- **P9 — Memory hoàn chỉnh**: A2 auto-extraction (cần Store P8) + A3 cross-agent share (RO sibling).
- **P10 — Skill system**: C1 bundled PM skill library + C2 custom skill upload (validate path/symlink).
- **P11 — Integrations**: C3 MCP gateway cho PM tool (Linear/Asana/Monday) + D2 multi-channel delivery.
- **P12 — Automation + observability**: D3 workflow `automation.yaml` (mọi action qua Lớp A/B) + B3 run replay + B4 tracing opt-in.

**Nguyên tắc M3 (bất biến):** mọi tính năng mở rộng action (workflow, MCP write) phải qua Action Gateway —
Lớp A red-line + Lớp B approve không nới. Đây là điểm v2 không được phá (xem [architecture §preserved](architecture.md)).
