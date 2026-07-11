# Codebase Summary — my-project-manager

> Bản đồ codebase, cập nhật khi code hình thành. Đọc để biết "cái gì ở đâu" nhanh.
> Status: **2026-07-11 — v19 COMPLETE.** ~1730 backend + 177 FE tests, ruff/tsc clean.
> Product usable single-user tới v19 (agent office, team-task, màn 3D command-center,
> registry user-data, memory seam + workspace protocol). Bản đồ code + quyết định kiến trúc
> theo mốc bên dưới. Đọc cùng
> [system-architecture](system-architecture.md), [project-overview-pdr](project-overview-pdr.md),
> [project-roadmap](project-roadmap.md).

## Trạng thái hiện tại (v2 COMPLETE: M1+M2+M3)

### M1: Multi-agent core (2026-06-24, 414 tests)
- **P1**: Config-injection refactor; 21 call sites parametrized, no more singletons.
- **P2**: Profile system (`profiles/<id>/` → 4 files + config + persona/project/memory injection).
- **P3**: Registry + per-agent worker + isolated stores + coordinating service (`registry.yaml`, worker subprocess per-agent, service daemon with croniter scheduler).
- **P4**: Multi-agent CLI (`mpm agent list/register/run/approvals/approve/reject/audit`); legacy `cli`/`cron` preserved.

### M2: Platform (2026-06-26, 545 tests)
- **P5**: LangGraph-native Lớp B interrupts (`approval_gate` node, pause/resume checkpoint flow).
- **P6**: FastAPI SSE streaming (localhost 4 routes: list/status/trigger/stream; live node-progress + terminal interrupt).
- **P7**: Web dashboard JSON API layer (5 GET endpoints: /api/{runs,cost,memory,automation,audit}/{id} + non-PII allowlist projection).
- **P8**: Postgres checkpointer + LangGraph Store + cross-thread agent memory (opt-in; SQLite default; MEMORY.md internal-only injection; Store namespace-scoped per-agent).
- **M4 (2026-06-28)**: React SPA replacing P7 HTMX (Vite+TypeScript, static assets committed to `src/server/static/app/`, served at `/`; ops JSON routes unchanged).

### M3: Extensibility (2026-06-27, 776 tests)
- **P10**: Skill system (5 bundled instruction-only skills, injectable LLM selector for internal-only prompt injection; red line: external gets no skills).
- **P9**: Cross-agent memory (sibling discovery + fact sharing via Store namespace `(sibling_id,"memory")`, RO-sibling/WO-self; injectable ranker; internal-only; red line: external gets nothing).
- **P11**: Integrations + multi-channel (config-driven extra MCP servers via `integrations:` block; Linear read + gated-write Lớp B; Email/SMTP delivery as new `email_send` action type, ALL email = Lớp B, internal-only; channel registry).
- **D4** (v11, 2026-07-10): XLSX report export + email attachment — Resource/OKR reports export deterministically to `.xlsx` (`src/reporting/xlsx_export.py`), written to `data_dir/artifacts/`. Email delivery attaches `.xlsx` when SMTP configured (path-only, never bytes). **NEW Lớp A red line**: attachment confinement (`confined_xlsx_path()` in `hard_block.py`, re-verified at send time in `email_write.py` handler). Internal-only, all sends Lớp B.
- **P12**: Automation + observability (opt-in LangSmith tracing B4, off=byte-identical; checkpoint-based replay B3 with safe-replay guard; READ-only workflow automation D3 via gateway, PROPOSE only, no auto-execute).

### M5: Domain-pack abstraction (2026-06-30, 816 tests)
- **S1-S6 slices**: Extract 3 coupling seams → generic core. PM becomes `domain-packs/pm-pack/` (graphs/tools/analyzers/allowlist/prompts/skills). PackRegistry loadable per domain. ToolProvider Protocol makes tool reads transport-agnostic. Config-driven allowlist stays pack-driven; Lớp A red line stays core-guarded. pm-pack output byte-identical pre-v3. Backward-compat: pre-v3 profiles default `domain: pm`.

### M6: Second domain (hr-pack) + generic seam patches (2026-07-01, 839 tests)
- **hr-pack lands**: Headcount report kind (count by employment status + department). Reads Confluence + Google Sheets via **gws CLI** (Google Workspace CLI, spawned like gh, independent auth). Writes via same Action Gateway (Lớp A/B unchanged). Config: HR_SHEET_ID / HR_SHEET_RANGE / HR_CONFLUENCE_PAGE_ID (env-only). Output PII-safe (aggregate counts, no employee names).
- **3 generic seam patches** (no domain logic; enable "git diff src/ = ∅" for future packs):
  - `discover_domains()` — filesystem-based pack discovery (domain-packs/<x>-pack/graphs.py marker), replaces hardcoded _KNOWN_DOMAINS.
  - `_ensure_pack_package()` — loads pack as importable domain_pack_<x> so pack modules can import siblings.
  - `all_report_kinds()` — kind validation unions all packs' kinds; failure-isolated per pack.

### M19: Company Docs (2026-07-04)
- **P13**: Company Docs library — flat files `company-docs/<slug>.md` (frontmatter title/updated). Agents opt-in via `company_docs:` list in profile.yaml (mirrors `skills:`). Doc bodies inject into INTERNAL compose prompt only as `<company_docs>` block (char-budget declared). **RED LINE: external audience gets zero bytes** (same guard as P10 skills; `company_docs_text` checks `audience != "internal"`). No DB, no RAG/embeddings; per-agent opt-in is selection mechanism (YAGNI). New modules: `src/company_docs/{store,inject,pool}.py`. New routes: `src/server/routes_company_docs.py` (library CRUD) + `src/server/routes_agent_company_docs.py` (per-agent opt-in). Web UI: `web/src/views/CompanyDocs.tsx` + picker in agent profile page. Backup: `deploy/backup.sh` tars `company-docs/`; `.gitignore` ignores (user data, restored from backup).

### M27–M30: Agent Office (2026-07-10)
- **M27 — Company setup**: `company.yaml` (name/coordinator_id/team_task_cap_usd=$2, gitignored per-install, mirror registry loader pattern). Staff templates in `profiles/templates/<role>/` = wizard prefill, 6 roles incl 5 office roles (Trưởng phòng, Nghiên cứu, Nội dung, Phân tích, Kiểm định, domain `office`). 1-click create coordinator (button ở Team page). New modules: `src/runtime/company.py` loader; `src/server/routes_company.py` CRUD; `web/src/wizard/staff-template-picker.tsx` + extend wizard.
- **M28a — Team-task store + graph**: `team_task_store.py` (SQLite WAL+seq+lease for step execution state machine). `team_task_graph.py` (perceive→work→deliver, atomic artifact handoff `/data_dir/artifacts/team-tasks/<id>/step-<n>.json`). Worker CLI gains `--task-id --step-id --attempt-id` argv (generic `team-step` run-kind). New modules: `src/runtime/{team_task_store,team_task_steps,team_task_paths,team_step_runner,team_tick_runner,team_tick_collaborators,team_task_cost,team_task_roster}.py`; `src/agent/{team_task_graph,team_task_artifact}.py`.
- **M28b — Coordinator + web search**: Coordinator = TICKER pseudo-kind (mirror tasks/ops-alerts, short tick exit, KHÔNG 600s-kill, lease reserve per-step). Decompose+confirm on admin ops agent via `assign_team_task` (1 LLM sync call → DecomposedTask, max 7 steps, role-constrained, plan hash bind TOCTOU-proof). Step dispatch DETACHED with lease (attempt_id+pid+lease_expires_at), per-step timeout → kill pid + escalate Telegram try/degrade (dedup_hint). **Web search** Tavily primary / Brave fallback, snippets-only, fail-closed query redaction BEFORE egress, 4-layer injection defense (delimiter/regex-filter/ToolMessage-sandbox/spotlight). New modules: `src/agent/{coordinator_graph,task_decomposition,ops_assign_team_task,team_task_roster}.py`; `src/tools/{web_search_tool,search_result_formatter}.py`; extend `src/actions/secret_patterns.py` redaction; `src/server/routes_setup.py` search-key whitelist.
- **M29 — Office room**: `office_room_store.py` (SQLite WAL+seq AUTOINCREMENT SSoT). `office_event_projection.py` (default-drop allowlist PII firewall AT WRITE TIME). `routes_office_stream.py` (SSE store-tail `/api/office/rooms/{id}/stream`, multi-subscriber, seq-cursored resume-safe). `milestone_mirror_runner.py` (store-poller pseudo-kind, cursor-after-send, milestone-only Telegram DM). New modules: `src/runtime/{office_room_store,office_room_append,milestone_mirror_runner}.py`; `src/server/{routes_office_stream,office_event_projection}.py`; `web/src/views/OfficeRoom.tsx`, `web/src/hooks/use-office-stream.ts`.
- **M30 — Office 3D**: r3f wireframe (~930KB lazy chunk `routes/office-scene-lazy.tsx`, isolated from main bundle). 2D fallback (table) for `prefers-reduced-motion`/mobile. Driven ONLY by real SSE events from office_room_store. New modules: `web/src/views/office-3d/{office-scene,agent-desk,coordinator-desk,speech-bubble,agent-status-table}.tsx`; add `three`, `@react-three/fiber@^9`, `@react-three/drei@^10` to `web/package.json`.
- **office-pack** new domain (`domain-packs/office-pack/`, Coordinator topology). Allowlist wiring: all `ActionGateway` MUST pass `mcp_allowlist=pack.allowlist or None` (M8-class regression guard). Default-deny on pack allowlist rests. Coordinator/step KHÔNG có write handler mặc định.
- **THE INVARIANT EXTENDED**: handoff nội bộ (/data_dir/artifacts/team-tasks/) KHÔNG egress. External write per-step vẫn Lớp B per-agent. Allowlist default-deny giữ. **PII firewall office events**: default-drop allowlist projection AT WRITE TIME → replay tự động an toàn; cấm free-form body_json. Role authz gate deterministic (decompose-validation + dispatch, assigned_to ∈ company staff + CEO-confirmed plan hash).

**Entry points**: Legacy `python -m src.entrypoints.cli`/`cron` (single-agent). Multi-agent: `python -m src.entrypoints.mpm agent {list,register,run,resume,replay,automate,approvals,approve,reject,audit}`. Runtime: `python -m src.runtime.worker`, `python -m src.runtime.service`.

### M31–M34: Team self-operation (2026-07-10)
- **M31 — Step graph LangGraph sâu**: `team_task_graph.py` v2: `perceive → work → self_check` with rework loop ≤2 counter in state (primitives, reset per attempt). `CheckVerdict` structured (`passed`/`failures`/`confidence`). `acceptance` METADATA per-step NOT in `decomposition_content_hash` (lưu `team_steps.acceptance` TEXT col, round-trip self_check criteria). `confirmed_plan_hash` = CEO-confirmed DAG only; rows `system_inserted=1` loại khỏi `_verify_plan_hash` recompute (Decision A hash-split). `version:=attempt_id` versioning; `_read_handoff` deps-aware (KHÔNG seq-1). Node phase events (dang-lam/tu-soat/dang-sua) qua `.stream(stream_mode=["updates","custom"]) → (mode,chunk)` tuple → room append; attempt_id carry zombie-event drop. **KHÔNG checkpointer/SqliteSaver/migrate_state** (Decision B: DROP). Retry=fresh attempt v12 semantics. New modules: `src/llm/team_task_check_prompt.py`; `src/runtime/team_step_runner.py` (.stream() handler); extend `src/agent/team_task_graph.py`, `src/runtime/team_task_steps.py` (cols: `acceptance`, `step_type`, `needs_review`, `system_inserted`, `parent_step_id`, `review_round`), `src/agent/task_decomposition.py` (acceptance field), `src/agent/coordinator_graph.py` (_verify_plan_hash gate).
- **M32 — Peer review tự chèn**: Ticker cứng (KHÔNG LLM steering): content-step done `needs_review=1` → review-step chèn via `pick_reviewer(author_id, roster)` (peer ≠ author, id-contains kiem/qa/review preferred, else any peer tie-break by id; no peer → SKIP+room "bỏ soát", KHÔNG stall). `review_graph.py` new: perceive artifact locked via `version(=attempt_id)` → structured `ReviewVerdict` (binary: passed/failures) → deliver. Rework ≤2 vòng via `review_round` col → hết vòng → EXPLICIT stall+escalate (không auto-step như v12 delivered). Verdict KHÔNG steering (KHÔNG đổi assignee/add-remove step). 4 prompts wrap failures via `format_internal_content` red-line. New modules: `src/agent/review_graph.py`, `src/agent/coordinator_nodes/review_insert.py` (coordinator_nodes/ NEW folder); extend `src/runtime/team_task_steps.py` (insert_step call), `src/agent/coordinator_graph.py` (_act_on_task), `src/agent/tick_actions.py` (pick_reviewer + round cap).
- **M33 — Consult đồng nghiệp**: `team_task_graph.py` work node hook: `ask_colleague(agent_id, question)` ≤2/step in state (consult_count, reset per attempt). Load colleague SOUL.md + PROJECT.md FILE RO via `profile.loader.load_profile(agent_id)` (KHÔNG Store, KHÔNG sibling-memory — internal-only by construction, M3-P9 red line unbroken). Question + SOUL+PROJECT vào 1 LLM call → answer cached in state; fail=degrade no-raise (KHÔNG tốn lượt rework). Question via `format_internal_content` red-line. Room `consult` event: template summary ~120-char {from, to, question_summary, answer_summary} AT WRITE TIME in `office_event_projection` allowlist (KHÔNG raw file content). New modules: `src/agent/team_task_consult.py`, `src/agent/coordinator_nodes/team_task_consult_propose.py`; extend `src/server/office_event_projection.py` (consult kind), `web/src/views/office-3d/consult-bubble.tsx` (new), `web/src/types.ts` (OfficeEventKind).
- **M34 — Parallel cap 2 + full replan**: **Parallel**: v12 ĐÃ dispatch concurrent across ticks; v13 THÊM cap (config `team_task_concurrency`, default 2). `coordinator_graph.py` dispatch loop: đếm `running` steps trước spawn; cost headroom DERIVED từ steps `running` (KHÔNG ledger, KHÔNG reserve/finalize/release) in `team_task_cost.py` (docstring update overshoot-bound). **Full replan**: `ops_adjust_team_task.py` NEW (mirror `ops_assign_team_task.py`): amend LLM on admin agent (context=id/title/assigned_to/status only, done/running FROZEN) → preview DIFF (keep/drop/add + cost note) → CEO confirm via `base_plan_hash` full-DAG TOCTOU verify (SINGLE live draft, confirm CONSUMES, BEGIN IMMEDIATE txn). Coordinator escalate ĐỀ XUẤT text: CONSTANT template task_id-only (KHÔNG LLM-composed, anti-steering Decision C). New modules: `src/agent/ops_adjust_team_task.py`, `src/runtime/team_task_store.py` (set_amendment_draft/confirm_amendment BEGIN IMMEDIATE), `src/runtime/team_task_cost.py` (derived headroom); extend `src/config/settings.py` (team_task_concurrency), `src/agent/ops_catalog.py` (adjust_team_task registration), `src/runtime/team_tick_collaborators.py` (escalate template), `src/runtime/team_task_steps.py` (swap_pending_steps query).
- **THE INVARIANT + 3 new clauses v13** (must stay intact): Handoff=artifact (KHÔNG egress, internal data-dir). External write per-step vẫn Lớp B per-agent via ActionGateway. Allowlist default-deny. **New**: (1) verdict KHÔNG steering — review verdict chỉ trả passed/failures, KHÔNG đổi assignee/add-remove step; (2) amend chỉ qua CEO confirm-hash — `adjust_team_task` không tự apply, preview DIFF → CEO confirm bind `base_plan_hash` full-DAG TOCTOU; (3) consult RO internal-only — colleague context SOUL.md+PROJECT.md FILE-only, KHÔNG Store, KHÔNG sibling-memory. PII firewall office events: closed-ENUM `phase`/`verdict`/`consult` (template-summary consult ~120-char). Role authz deterministic (assigned_to ∈ company staff, both decompose-validate + dispatch).

### v14: Living office + blocked-step tự cứu (2026-07-10)
- **Recover node (blocked-step tự cứu)**: `team_task_graph.py` v3: `perceive → work → (self_check | recover→work)`. `work` LLM raise lần 1 → `route_after_work` → `recover` (1 consult best-effort về blocker qua CHÍNH seam propose/ask M33, budget chung MAX_CONSULTS) → retry 1 lần với hint; fail lần 2 → raise y pre-v14 (`MAX_RECOVER=1`, counter-in-state). `consult_context` persist trong state (paid answers sống qua retry). Phase mới `nho-tro-giup` — closed enum 3 NƠI: graph `PHASE_RECOVER` / `office_event_projection._STEP_PHASES` / FE `PHASE_LABEL`. KHÔNG row mới, KHÔNG đụng `_verify_plan_hash`.
- **Consult targeting theo vai trò**: `team_task_roster.roster_with_role_hints` — dòng đầu SOUL.md đồng nghiệp (RO ≤80 chars, fail-degrade) vào roster propose; roster block bọc `format_internal_content` (SOUL = agent-authored, chống second-order injection).
- **3D văn phòng sống** (`web/src/views/office-3d/`): OrbitControls autoRotate 0.5 (drei tự pause khi drag; reduced-motion vẫn 2D fallback); `office-props.tsx` NEW (chậu cây/bảng viết/sofa/đèn — tĩnh, không state); avatar tay+chân + breathing bob (cosmetic có chủ đích, inner group tách khỏi lerp); consult → 2 avatar đi tới `consultMeetPoint` (40% về phía nhau, pure helper `desk-layout.ts`) rồi tự về; reducer `endConsult` clear consultWith ĐỐI XỨNG (event của 1 bên thả cả 2 — tránh avatar kẹt giữa phòng).

### v15: @PIC assignment + unified office + demo v2 (2026-07-10)
- **@PIC giao việc**: `ops_assign_team_task.parse_pic_prefix` (`@id`/`@all`/không-@);
  decompose JSON thêm `pic_id` (LLM đề xuất khi không @; CODE override khi CEO @-chỉ định
  — red-team F4); `validate_pic_terminal` = DAG có ĐÚNG MỘT bước terminal ∧ thuộc PIC (F5;
  decompose áp toàn DAG, amend áp SLICE bước mới — frozen rows luôn "trông terminal");
  empty pic_id bị ép retry (review M1 — mọi task MỚI có PIC; amend task cũ pic="" skip).
  `team_tasks.pic_id` col (ALTER-except); **pic NGOÀI canonical hash** (pattern Decision A,
  pin test hash-neutrality); amend PIC-aware (`team_task_amend_prompt`, F2). Assignment
  event body +`pic`+`task_id` (projection allowlist mở đúng 2 field).
- **Auto-confirm** (`company.team_task_auto_confirm`, default off): preview tự chạy
  `run_assign_team_task` CÙNG đường hash-bind, slots `auto_confirmed` → ops_chat KHÔNG
  park draft ma (F3); fail → cancel draft (F9, except Exception); `routes_company` POST
  load-modify-save (F7 — fix luôn bug clobber `team_task_concurrency`/cap sẵn có).
- **Routes composer** `routes_office_assign.py`: /api/office/assign/{staff,preview,confirm,
  cancel} — thin wrapper trên CHÍNH hàm command (hash-bind/authz ở đó); protected mặc định;
  brief cap 4000 chars.
- **FE màn office hợp nhất** (`views/office-unified/`): MỘT `useOfficeStream` nuôi cả
  OfficeCanvas (extract từ office-scene, ĐÃ XÓA file cũ) + ActivityFeed (tail 40, dùng
  chung `office-shared/office-message-line` với OfficeRoom) + AssignComposer (@ dropdown,
  preview/confirm/cancel inline, card ĐÃ TỰ XÁC NHẬN). Reducer `picTasks` Set per desk —
  set bởi assignment.pic+task_id, clear bởi `milestone === 'done'` field CỨNG (F6, không
  match chuỗi); ⭐ label + bubble PIC tag. Routes: `office`→unified (lazy chunk riêng),
  `office/timeline`→OfficeRoom (nav "Nhật ký văn phòng"), `office/3d`→redirect. Settings
  toggle auto-confirm.
- **Demo v2**: registry demo TẮT `default` (E2E bắt LLM chọn nó làm PIC); truong-phong
  telegram stub qua escalation-gate (F1); seed assignment pic+task_id. E2E Playwright
  13/13 trên demo + LLM thật: @/không-@/auto-confirm, soi DB pic_id, redirect.

### v16: office workrooms + room chat + coordinator health (2026-07-11)
- **Workroom** (`team_tasks.room_id`, ALTER-except, NGOÀI hash): room chứa ≥1 task;
  `room_for_task()` (office_room_append) = MỘT chỗ route mọi writer event (9 module);
  `list_workrooms`/`tasks_in_room` (loại planning/cancelled; cấm room_id='office').
- **Chat-in-room** `routes_office_room_chat.py`: 3 intent — tier-1 REGEX (`chỉnh [id]:` /
  `giao|@`) được hưởng auto-confirm; tier-2 LLM classify LUÔN preview (M3); default
  question = `office_room_qa.answer_room_question` (read-only, artifact bọc internal,
  reply ephemeral). Adjust đi `preview/run_adjust_team_task` (single-draft/TOCTOU giữ).
- **Coordinator health**: heartbeat từ VÒNG LẶP `service.py` (không phải worker tick) →
  `GET /api/health/coordinator` {alive, reason: no_coordinator|no_heartbeat|stale} →
  FE banner đỏ — fix gốc "task giao xong kẹt im lặng".
- **FE workrooms** (`office-unified/`): ≤2 EventSource (3D luôn room 'office'; feed theo
  room chọn, ?room= URL); `workroom-list` + refetch guard theo seq; feed icon+màu token;
  composer 2 chế độ (toàn cảnh giao việc / in-room 3 intent + confirm-adjust); canvas
  `visibleDesks` lọc roster thật (hết desk ma) + dimmed ngoài room; banner poll 30s.
- **Demo v3**: chạy KÈM service thật (pid-file, refuse nếu service khác đang chạy, off
  kill + xoá heartbeat); seed task rows TERMINAL-only (C2 — ticker thật sẽ ăn task open).
  E2E 13/13: ticker thật dispatch, question no-write, task con cùng room, adjust, banner.

### v17: office command center — 3 cột + artifact viewer + IA (2026-07-11)
- **Artifacts API** `routes_office_artifacts.py`: 2 GET read-only (room catalog từ
  `tasks_in_room`; step artifact qua `read_step_artifact` — path do server ghép, task_id
  gate store.get, seq int-coerce, mọi lỗi → 404). FE lọc `done ∧ step_type∈(work,rework)`
  (review-step không có artifact file — M1).
- **FE Kết quả**: `artifact-panel` (maxSeqOf refetch helper thuần) + `artifact-viewer`
  (react-markdown+remark-gfm trong LAZY office chunk; M4: components.img → link, không
  load remote; copy + tải .md Blob; Esc). Feed handoff line = notice ngắn cố định.
- **Q4 bubble**: `shouldShowBubble(desk)` — chỉ assigned/working/consult; M2: ticker
  timeout giờ append `step_status failed` (desk hết kẹt bubble vĩnh viễn).
- **IA v17**: `/` → Văn phòng (màn chính); nav [Văn phòng, Đội, Duyệt(badge), Trợ lý,
  Cài đặt]; Work.tsx = "Cần bạn duyệt" + "Việc đã giao cho từng nhân sự" (board giữ).
- **Demo**: seed ghi artifact THẬT theo seq đọc từ store (seq GLOBAL autoincrement —
  M3); demo off dọn `artifacts/team-tasks/demo-*`. E2E 16/16 (markdown render thật,
  download, Q4, task thật bàn giao → xem full).

### v18: registry = user-data + team recovery UX (2026-07-11)
- **registry.yaml RỜI GIT** (gitignored `/registry.yaml`): user data như company.yaml/
  profiles — đội thật của CEO không bao giờ bị git revert (root-cause của "profiles tồn
  tại mà registry trống"). `registry.example.yaml` committed; `load_registry()` bootstrap
  atomic từ example khi vắng (CHỈ đường path-mặc-định — caller truyền path giữ
  FileNotFoundError); installer copy idempotent.
- **Recovery UI**: `GET /api/agents/unregistered` (per-profile degrade — 1 hồ sơ hỏng
  không 500 danh sách) + `POST /api/agents/{id}/register` (register-ONLY, validate id,
  409 race); trang Đội section "Hồ sơ chưa trong đội".
- **C1 scheduler seed-at-discovery**: `run_tick` setdefault last_fire cho (agent,kind)
  mới — agent đăng ký runtime có lịch nổ ngay tick kế (trước: chết im lặng tới restart).
- **Polish**: 3D canvas/floor theme-aware (MutationObserver data-theme, 2 palette cứng —
  r3f không đọc CSS var); rooms-list mobile cuộn ngang; health check `websearch_key`
  (agent bật web_search mà máy thiếu TAVILY/BRAVE key — ok khi không ai bật).
- Fleet thật đổi: `default` DISABLED (quyết định CEO — đội office = mọi agent enabled,
  default là pm không thuộc văn phòng).

### v19: agent-harness vòng 1 — memory seam + workspace protocol (2026-07-11)
- **Memory provider seam** (`src/memory/`): `resolve_memory_text(loaded)` = MỘT cửa lấy
  memory text, thay 6 call-site đọc `loaded.memory` trực tiếp (worker/team_step_runner/
  review_graph/cron/cli + **qa_answer** — site thứ 6 red-team bắt). Provider `static`
  (MEMORY.md, byte-identical) + `MemoryConfig` từ `memory:` block profile.yaml (default
  static; parse fail-loud RuntimeError khớp `_parse_inbox`). Provider `kioku` HOÃN v19.5 —
  chọn nó raise rõ (KHÔNG im lặng fallback static).
- **Workspace protocol v2**: mỗi `profiles/<id>/` thêm `vault/` (reserved kioku v19.5) +
  `skills/` (per-agent). `scaffold_profile_dir` tạo 2 thư mục khi tạo nhân viên.
- **Per-agent skills** (`load_agent_skills`): cùng frontmatter pack skill nhưng **trust tier
  thấp hơn** — body wrap `format_internal_content` (L1/L2/L4 chống second-order injection),
  name scrub charset (chặn forge prompt-tag). `load_skill_pool` merge pack∪agent; collision
  cùng tên **KHÔNG shadow** pack (rename `agent:<name>`, giữ cả hai — pack repo-vetted luôn còn).
- **Capability block** (`src/profile/capability_block.py`): "TOOLS.md-equivalent" auto-gen
  deterministic (domain/report-kinds/skills/web_search/memory-provider, ≤600 chars).
  **INTERNAL-ONLY** — vào `build_context_block` (user msg, gate `audience=="internal"`), KHÔNG
  system msg (system phục vụ cả external → skill.name free-text = injection vector; red-team H6).
  `build_context_block` thêm param `capability=""` default → caller cũ byte-identical.
- **Red-team HOÃN kioku**: adapter viết theo CLI tưởng tượng (my-kioku thật khác 7/16 claim:
  chưa publish npm, `--digest`=recency-top-5 không-query, `bun x`=RCE-with-creds, race vault
  thiếu busy_timeout...). v19.5 làm sau khi giải 7 điều kiện (xem plan v19 "Giữ cho v19.5").
- **Known-limitation**: memory_node (Store P8, report runs) tách khỏi seam — facts học ở
  report run KHÔNG vào vault (khi kioku về); ghi để v19.5 không "phát hiện lại".

**Entry points**: Legacy `python -m src.entrypoints.cli`/`cron` (single-agent). Multi-agent: `python -m src.entrypoints.mpm agent {list,register,run,resume,replay,automate,approvals,approve,reject,audit}`. Runtime: `python -m src.runtime.worker`, `python -m src.runtime.service`.

## Cây thư mục (v3 M5 state with domain-packs)

```
src/
├── agent/        # LangGraph graph + nodes + state — LÕI (M1)
├── tools/        # *_read.py: generic models (Task/Event) used by packs
├── actions/      # action_gateway.py + approved_dispatch.py (WRITE, qua guardrail; handler lookup via pack)
├── llm/          # provider config + LLM builder logic (P2: accepts persona/project/memory params)
├── config/       # Settings + domain: field, ReportingConfig (P1); config_builders
├── profile/      # [M1-P2] Profile loader + context injection; [M5] parse domain: field
├── runtime/      # [M1-P3] Worker + service + registry + scheduler; [M5] worker dispatches via PackRegistry
├── audit/        # audit log (append-only)
├── server/       # [M2-P6] FastAPI + SSE + JSON API; [M4] React SPA (static/app/)
├── reporting/    # [v11 D4] Report export (xlsx_export.py: deterministic .xlsx from dataclasses)
├── packs/        # [M5] PackRegistry loader + ToolProvider Protocol
├── automation/   # [M3-P12] Workflow automation engine + LangSmith tracing config
└── entrypoints/  # cli.py, cron.py (legacy); mpm.py (M1-P4: multi-agent)
                  # mpm_resume_cmd.py, mpm_replay_cmd.py, mpm_automate_cmd.py (M3)

domain-packs/    # [M5] Domain implementations (pluggable)
├── pm-pack/     # PM domain: graphs/tools/prompts/skills/allowlist
│   ├── pack.yaml             # manifest: id, report_kinds, required bindings
│   ├── graphs.py             # report_kind builders (daily/weekly/okr/resource)
│   ├── tools.py              # ToolProvider wrapping jira/github/confluence reads
│   ├── write_handlers.py     # allowlist + handler dispatch for slack/confluence
│   ├── models.py             # Issue↔Task mapping (lossless) + generic Task/Event
│   ├── prompts/              # 8 PM system prompts (dynamic-loaded)
│   └── skills/               # 5 bundled PM skills
└── hr-pack/     # [M6] HR domain: headcount reports via Google Sheets + Confluence
    ├── pack.yaml             # manifest: id, report_kinds (headcount)
    ├── graphs.py             # headcount report builder
    ├── tools.py              # ToolProvider: Confluence read + gws CLI (Google Sheets)
    ├── write_handlers.py     # allowlist (slack/confluence writes)
    ├── analyzers.py          # headcount analyzer (count/group_by)
    └── prompts/              # HR-specific system prompts

profiles/         # Agent configs (gitignored except default/)
├── default/      # v1 migration template (SOUL/PROJECT/MEMORY; profile.yaml; domain: pm implicit)
│   ├── profile.yaml
│   ├── SOUL.md
│   ├── PROJECT.md
│   └── MEMORY.md
└── .../<id>/     # Per-agent profile (same 4-file structure; domain: field optional)

registry.yaml     # [NEW P3] agents: [{id, enabled}]

.data/
└── agents/       # [NEW P3] Per-agent stores (were .data/ in v1)
    ├── default/  # Migrated v1 stores (single-agent compat)
    │   ├── checkpoints.db
    │   ├── audit/
    │   ├── budget/
    │   ├── approvals.db
    │   └── dedup.db
    └── <id>/     # Per-agent isolation
        └── (same structure)
```

## Bản đồ "tìm gì ở đâu"

| Cần tìm | Ở |
|---|---|
| **[M5] Domain pack load** | `src/packs/registry.py::PackRegistry.load(domain)` — importlib-load `domain-packs/<domain>-pack/` modules; return Pack object |
| **[M5] ToolProvider interface** | `src/packs/tool_provider.py::ToolProvider` Protocol — `read(name: str) -> list[Task/Event]`; transport-agnostic |
| **[M5] Pack allowlist** | `domain-packs/pm-pack/write_handlers.py` — contributes `ALLOWLIST` dict; loaded by `hard_block.py` (Lớp A red line stays core) |
| **[M5] Profile domain field** | `src/config/settings.py::Settings.domain` — defaults `"pm"` if absent (backward-compat); loaded by profile.py |
| **[M6] Discover packs (filesystem)** | `src/packs/registry.py::discover_domains()` — finds `domain-packs/<x>-pack/` folders with graphs.py marker (replaces hardcoded _KNOWN_DOMAINS) |
| **[M6] Pack package registration** | `src/packs/registry.py::_ensure_pack_package()` — loads domain-packs/<x>-pack/ as importable domain_pack_<x> (enables pack self-imports) |
| **[M6] Kind validation union** | `src/packs/registry.py::all_report_kinds()` — unions all packs' report_kinds for early typo detection; failure-isolated per pack |
| **[M6] HR gws adapter** | `domain-packs/hr-pack/tools.py::_gws_sheet_rows()` — spawns gws CLI (Google Workspace CLI), parses JSON, mirrors gh CLI pattern |
| **[M6] HR analyzer** | `domain-packs/hr-pack/analyzers.py` — headcount aggregator (count/group_by employment status + department) |
| **[M19] Company Docs store** | `src/company_docs/store.py` — CRUD library (load/save docs from `company-docs/<slug>.md` dir) |
| **[M19] Company Docs inject** | `src/company_docs/inject.py` — opt-in injection into compose prompt; checks `audience != "internal"` (red line) |
| **[M19] Company Docs pool** | `src/company_docs/pool.py` — doc pooling/selection by agent; char-budget tracking |
| **[NEW P2] Load profile** | `src/profile/loader.py::load_profile()` — parse `profiles/<id>/profile.yaml` + SOUL/PROJECT/MEMORY + domain field |
| **[NEW P2] Profile → config** | `src/profile/loader_mapping.py` — map profile.yaml fields to P1's Settings/ReportingConfig dicts + domain |
| **[NEW P2] Prompt injection** | `src/profile/context.py::ProfileContext` — persona (system msg), project+memory (user msg, internal only) |
| **[M5 UPDATE] Worker dispatch** | `src/runtime/worker.py::build_graph_for()` — calls `PackRegistry().load(domain).report_kinds[kind]` instead of if/elif |
| **[M5 UPDATE] Hard-block load** | `src/actions/hard_block.py` — `allowlist` loaded from pack; Lớp A red-line markers (`_DATA_LOSS_TOOL_MARKERS`, etc.) stay core-only |
| **[M5 UPDATE] Dispatch handlers** | `src/actions/approved_dispatch.py` — handler lookup via pack registry; write-handler dispatcher LOGIC stays core (slack/linear/email shared) |
| **[P2 UPDATE] CLI entry (legacy)** | `src/entrypoints/cli.py` — now accepts `--profile` (default `default`); calls `load_profile()` + passes config downstream |
| **[P2 UPDATE] Cron entry (legacy)** | `src/entrypoints/cron.py` — now accepts `--profile`; scheduler loads profile per agent-run |
| **[NEW P4] Multi-agent CLI** | `src/entrypoints/mpm.py` — dispatcher for `mpm agent {list,register,run,approvals,approve,reject,audit}` |
| **[NEW P4] Registry cmds** | `src/entrypoints/mpm_registry_cmds.py` — `run_list()`, `run_register()` |
| **[NEW P4] Run cmd** | `src/entrypoints/mpm_run_cmd.py` — `run_agent()` spawns worker subprocess |
| **[NEW P4] Manage cmds** | `src/entrypoints/mpm_manage_cmds.py` — `run_manage()` for approvals/approve/reject/audit per-agent |
| **[NEW P3] Worker entry** | `src/runtime/worker.py::main()` — CLI: `python -m src.runtime.worker --agent-id <id> --report <kind> [--audience] [--dry-run]` |
| **[NEW P3] Service entry** | `src/runtime/service.py::main()` — daemon: reads registry.yaml, spawns/supervises workers, respects schedule + timeout/cap |
| **[NEW P3] Registry** | `registry.yaml` + `src/runtime/registry.py::load_registry()` — list agents (id, enabled) |
| **[NEW P3] Per-agent paths** | `src/runtime/agent_paths.py` — `agent_data_dir(id)` = `.data/agents/<id>/`, `agent_thread_id(id, kind, audience)` = `<id>:<kind>:<audience>` |
| **[NEW P3] Per-agent isolation** | Each agent's stores (checkpoints, audit, budget, dedup, approvals) isolated under `.data/agents/<id>/`; `thread_id` contains agent_id for checkpoint safety |
| **[NEW P3] V1 migration** | `src/runtime/legacy_migration.py` — once-only idempotent move of v1 `.data/` → `.data/agents/default/` (triggered on first worker run) |
| **[NEW P3] Scheduler** | `src/runtime/scheduler.py` — pure croniter due-check; reads `schedule:` in profile.yaml; fires internal audience only |
| **[NEW P3] Run events** | `src/runtime/run_event.py` — B1 runs.jsonl per agent (one entry per worker run, records outcome) |
| Flow agent (graph) | `src/agent/report_graph.py` (perceive→analyze→compose→deliver) + injectable deps with config/settings |
| Cách đọc Jira | `src/tools/jira_read.py` — hoạt động qua pack ToolProvider (`pm-pack/tools.py`); adapter MCP ở `src/adapters/mcp_adapter.py` |
| Cách đọc GitHub | `src/tools/github_read.py` — hoạt động qua pack ToolProvider; adapter CLI `src/adapters/cli_adapter.py` |
| **[M5] Generic data model** | `src/tools/models.py::Task/Event` — cross-domain; `pm-pack/models.py::issue_to_task/task_to_issue` (lossless mapping) |
| Models (v2 PM-specific) | `src/tools/models.py::Issue, PullRequest, CiRun, Risk, Sprint` — PM-only; analyzers still consume Issue (byte-identical) |
| Risk phát hiện | `src/agent/risk_analyzer.py` (pure: overdue/blocker/stale_pr/ci_failure) |
| **[P1 UPDATE] Config reporting** | `src/config/reporting_config.py` + `src/config/settings.py` (no `@lru_cache` singletons; parametrized builders) |
| Cách agent ghi/post | `src/actions/action_gateway.py` (MỌI mutation; per-agent isolation in P3) |
| Post Slack | `src/actions/slack_write.py` (deliver_report + build_slack_short) |
| Tạo page Confluence | `src/actions/confluence_write.py` (create_report_page via gateway) |
| **[v11 D4] XLSX export** | `src/reporting/xlsx_export.py` — `build_resource_xlsx()`, `build_okr_xlsx()`, `artifact_path()` (deterministic from dataclasses, no LLM) |
| **[v11 D4] Email attachment** | `src/actions/email_write.py::deliver_email_report()` — gateway-routed, ALL Lớp B; `_attachment_bytes()` re-validates attachment path; `make_email_handler()` binds SMTP config |
| **[M27] Company loader** | `src/runtime/company.py::load_company()` — parse `company.yaml` (name/coordinator_id/team_task_cap_usd); default safe no-crash if missing |
| **[M27] Staff templates** | `profiles/templates/<role>/profile.yaml` + SOUL/PROJECT/MEMORY (wizard prefill) — 6 roles incl 5 office: Trưởng phòng, Nghiên cứu, Nội dung, Phân tích, Kiểm định |
| **[M28a] Team-task store** | `src/runtime/team_task_store.py` — WAL+seq+lease state machine (pending → open → running → completed/failed); `reserve_step()` atomic lease (attempt_id+pid+lease_expires_at) |
| **[M28a] Team-task graph** | `src/agent/team_task_graph.py` — perceive(brief+handoff) → work(LLM+persona+company-docs+web-search) → deliver(artifact atomic + append office_room_store) |
| **[M28b] Coordinator ticker** | `src/agent/coordinator_graph.py` — TICKER pseudo-kind (short tick exit, no 600s-kill), lease logic, step spawn DETACHED, reboot recovery via store read |
| **[M28b] Decompose+confirm** | `src/agent/task_decomposition.py` — Pydantic schema (max 7 steps, role-constrained), `assign_team_task` on admin ops agent (1 LLM sync), plan hash bind TOCTOU-proof, no re-materialize |
| **[M28b] Web search** | `src/tools/web_search_tool.py` + `src/tools/search_result_formatter.py` — Tavily primary/Brave fallback, snippets-only (no page fetch), fail-closed pattern-scan before egress, 4-layer injection defense |
| **[M28b] Query redaction** | Extend `src/actions/secret_patterns.py` — redact query before egress, audit logs redacted query only (KHÔNG raw) |
| **[M28b] Cost cap per task** | `src/runtime/team_task_cost.py` — sum `HistoryEntry.cost_usd` (decompose+step+aggregate), default $2/task via `company.yaml::team_task_cap_usd` |
| **[M29] Office room store** | `src/runtime/office_room_store.py` — SQLite WAL+seq AUTOINCREMENT SSoT; append-only, seq-indexed for stream-tail |
| **[M29] Office event projection** | `src/server/office_event_projection.py` — default-drop allowlist firewall, PII projection AT WRITE TIME (safe replay) |
| **[M29] Office stream SSE** | `src/server/routes_office_stream.py::stream_office_room()` — store-tail per seq, multi-subscriber (KHÔNG 1-drain 409 limit), resume-from-seq safe |
| **[M29] Telegram mirror** | `src/runtime/milestone_mirror_runner.py` — store-poller pseudo-kind, cursor-after-send, milestone-only DM (chỉ nhận việc/xong/hoàn/duyệt), dedup, không spam |
| **[M30] Office 3D** | `web/src/views/office-3d/` — r3f wireframe (lazy chunk ~930KB), agent-desk/coordinator-desk/speech-bubble, driven by SSE thật; 2D fallback (table) reduced-motion/mobile |
| **[M27–M30] office-pack** | `domain-packs/office-pack/` — coordinator domain, allowlist wiring bắt buộc (`mcp_allowlist=pack.allowlist or None`) |
| **[v19] Memory seam** | `src/memory/provider.py::resolve_memory_text(loaded)` — 1 cửa lấy memory text (6 site); `parse_memory_config` fail-loud; `static_provider.py` = MEMORY.md verbatim; `kioku` raise (v19.5) |
| **[v19] Per-agent skills** | `src/skills/skill_loader.py::load_agent_skills(dir)` — wrap body `format_internal_content` + scrub name; `skill_pool.load_skill_pool(..., profile_id=)` merge pack∪agent, collision→`agent:<name>` |
| **[v19] Capability block** | `src/profile/capability_block.py::build_capability_block(loaded, pack)` — auto-gen ≤600 chars, INTERNAL-only qua `build_context_block(project, memory, capability)` |
| **[v19] Workspace scaffold** | `src/runtime/registry_edit.py::scaffold_profile_dir` — tạo `vault/` + `skills/`; `src/packs/registry.py::profile_skills_dir(id)` |
| Guardrail allow/deny | `src/actions/hard_block.py` (allowlist + Lớp A/B + per-agent in P3) |
| **[v11 D4] Attachment confinement** | `src/actions/hard_block.py::confined_xlsx_path()` — NEW Lớp A red line; verify attachment is .xlsx, exists, inside artifact_root (symlink-safe via resolve()) |
| Guardrail giải thích | `docs/v1/action-gateway-explainer.md` — safety model (giữ nguyên từ v1) |
| Lớp B duyệt người | `src/actions/approval_store.py` (queue SQLite) + gateway `approve/reject` |
| Dedup bền | `src/actions/dedup_store.py` (SQLite, reserve-before-execute) |
| Xem audit | `cli audit [--tool/--verdict/--since/--limit]` |
| Phát hiện/redact secret | `src/actions/secret_patterns.py` |
| Report prompt | `src/llm/report_prompt.py` (P2: accepts persona/project params) |
| OKR Confluence read | `src/tools/confluence_read.py` |
| OKR epic progress | `src/tools/okr_read.py` |
| OKR analyzer | `src/agent/okr_analyzer.py` |
| Resource analyzer | `src/agent/resource_analyzer.py` |
| **[M31] Step graph v2** | `src/agent/team_task_graph.py::v2` — perceive→work→self_check loop ≤2, rework ≤2 counter in state, CheckVerdict structured (passed/failures/confidence), route_after_check conditional. `version:=attempt_id`, `_read_handoff` deps-aware. `.stream(stream_mode=["updates","custom"])` → (mode,chunk) tuple + heartbeat on updates only. Retry=fresh attempt, NO checkpointer/migrate_state. |
| **[M31] Self-check prompt** | `src/llm/team_task_check_prompt.py` — rubric input, result_text wrapped `format_internal_content` red-line |
| **[M31] Team-step runner** | `src/runtime/team_step_runner.py` — `.stream()` handler, phase events (dang-lam/tu-soat/dang-sua) to room via `get_stream_writer`, attempt_id carry for zombie-drop |
| **[M31] Acceptance metadata** | `src/agent/task_decomposition.py` — `acceptance` optional field on step (METADATA, NOT in `decomposition_content_hash`); `src/runtime/team_task_steps.py` — `acceptance TEXT DEFAULT ''` col, thread via `_row_to_step`/`replace_steps`/`TeamStep` |
| **[M31] Hash split** | `src/agent/coordinator_graph.py::_verify_plan_hash` — `confirmed_plan_hash` recompute CHỈ trên steps `system_inserted=0` (Decision A); acceptance KHÔNG vào hash |
| **[M32] Review graph** | `src/agent/review_graph.py` — perceive artifact locked via `version(=attempt_id)` → ReviewVerdict binary (passed/failures) → deliver. Result_text wrapped `format_internal_content` |
| **[M32] Review insert** | `src/agent/coordinator_nodes/review_insert.py` NEW folder — luật cứng chèn review-step (content-step done + needs_review → reviewer via pick_reviewer) và rework-step (verdict cần-sửa, same author, ≤2 vòng) |
| **[M32] Reviewer selection** | `src/agent/team_task_roster.py::pick_reviewer(author_id, roster)` — peer ≠ author, id-contains kiem/qa/review preferred, else any tie-break by id, None if no peer |
| **[M32] Verdict no-steering** | Review verdict chỉ trả passed/failures, KHÔNG đổi assignee/add-remove step (Decision B anti-steering). Rework loop ≤2 vòng → EXPLICIT stall+escalate (không auto-deliver) |
| **[M33] Consult colleague** | `src/agent/team_task_consult.py` — `ask_colleague(agent_id, question)` loads colleague SOUL.md + PROJECT.md FILE RO via `profile.loader.load_profile()` (KHÔNG Store/sibling-memory), question via `format_internal_content`, 1 LLM call → answer; fail=degrade no-raise |
| **[M33] Consult proposal** | `src/agent/coordinator_nodes/team_task_consult_propose.py` — propose consult event to room (question_summary ~120-char template at WRITE TIME, no raw file) |
| **[M33] Consult event** | `src/server/office_event_projection.py` — `consult` kind allowlist {from, to, question_summary, answer_summary} template-truncate AT WRITE TIME |
| **[M34] Parallel cap** | `src/config/settings.py::team_task_concurrency` (default 2); `src/agent/coordinator_graph.py` dispatch loop déns running steps; cost headroom DERIVED via `src/runtime/team_task_cost.py` (no ledger → no leak) |
| **[M34] Cost headroom** | `src/runtime/team_task_cost.py` — `reserved = Σ estimate over steps status='running'`; KHÔNG ledger/reserve/finalize/release; update docstring overshoot-bound |
| **[M34] Full replan** | `src/agent/ops_adjust_team_task.py` NEW — mirror `ops_assign_team_task.py`: amend LLM (context=id/title/assigned_to/status, done/running FROZEN) → preview DIFF → CEO confirm via `base_plan_hash` full-DAG |
| **[M34] Amend confirm** | `src/runtime/team_task_store.py::set_amendment_draft` + `confirm_amendment` — SINGLE live draft, confirm CONSUMES, BEGIN IMMEDIATE txn verify `base_plan_hash` (subsume completed-prefix + pending-set + inserted-step) → swap pending-only (skip just-reserved) |
| **[M34] Escalate template** | `src/runtime/team_tick_collaborators.py` — escalate ĐỀ XUẤT text (CONSTANT template task_id-only, KHÔNG LLM-composed anti-steering) |
| **[M34] Swap pending** | `src/runtime/team_task_steps.py::swap_pending_steps` — pending-only query, skip reserved |
| **[M33 Consult bubble** | `web/src/views/office-3d/consult-bubble.tsx` NEW — 2-bàn hỏi-đáp bong bóng |
| **[M33 Event kind]** | `web/src/types.ts::OfficeEventKind` +`consult` |

## Key v2 Changes vs v1

| Aspek | v1 | v2 M1-P3 |
|---|---|---|
| **Config source** | `.env` (singleton `get_settings()`) | `profiles/<id>/profile.yaml` (parametrized loader) |
| **Entry point (CLI)** | `cli report --daily` | `cli report --daily [--profile default]` |
| **Entry point (worker)** | N/A | `python -m src.runtime.worker --agent-id <id> --report <kind>` |
| **Entry point (service)** | Per-report launchd plists | `python -m src.runtime.service` (one daemon, reads registry) |
| **Token storage** | ENV values in `.env` | Profile refs ENV var NAME; token resolved at spawn |
| **Persona/project/memory** | Hardcoded prompts | Profile SOUL/PROJECT/MEMORY files → injected at prompt time |
| **External report** | PII scrub at prompt time | Same (persona/project/memory NOT injected to external path — safety preserved) |
| **Data isolation** | All data in `.data/` | Per-agent under `.data/agents/<id>/` (v1 `.data/` migrated to `.data/agents/default/` once) |
| **Multi-agent** | Single agent hardcoded | Multiple agents via registry.yaml (enabled/disabled) |
| **Default profile** | N/A | `profiles/default/` = v1 replica (empty MD, yaml from config.example.env) |
| **Thread safety** | `thread_id` = kind + audience | `thread_id` = agent_id + kind + audience (checkpoint isolation) |

## Testing

- **Unit tests**: `uv run pytest` — 1500 backend tests pass (M1–M6, M19, M27–M30 + coverage pack/dispatch/red-line/office/web-search injection).
- **Frontend tests**: `vitest` — 146 tests (M30 3D/office views, M27 template-picker, M28 team components).
- **Linting**: `uv run ruff check src tests` — clean.
- **Byte-identity**: pm-pack output (report text, Slack mrkdwn, Confluence XHTML) diff vs pre-v3 = empty (2026-06-30).
- **E2E Red-line suite** (M5 verified live, 2026-06-30): pack allowlist loaded; Lớp A hard-deny refuses destructive unplugged tools; default-DENY preserves invariant. `default` profile (no domain field) routes to pm-pack; M1-style e2e (Jira read, Confluence create, Slack post) re-runs without code change.

## Next Phase

**M7 (admin-pack):** Third domain to validate "git diff src/ = ∅" gate (M6 seam patches should suffice). Candidate: billing/cost-center reports via API integrations.

## Deferred

- **Live-key integration E2E:** Linear/SMTP/LangSmith with real credentials (skipped M3/M5; scheduled separately).
- **Advanced workflow:** Boolean `when` conditions, schedule-triggered automation (deferred D3 expansion).
- **Replay re-fetch:** Safe re-fetch in replay (currently frozen-state safe-replay guard; future: selective re-fetch with audit).
