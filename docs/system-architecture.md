# System Architecture — my-crew

> Kiến trúc kỹ thuật (as-built, v95 — control-plane API, escalation→manager, credential store, worker packs; backend 0.15.0). Đọc cùng [project-overview-pdr](project-overview-pdr.md)
> (vì sao) + [action-gateway-explainer](action-gateway-explainer.md) (mô hình an toàn) +
> [codebase-summary](codebase-summary.md) (cái gì ở file nào).
> Cập nhật: 2026-08-30.

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
   CEO ──(web / Telegram)──►  FastAPI (my_crew/server) ──► SQLite stores  ◄── Coordinator daemon
        giao việc/duyệt          routes_*.py              (.data/)          (my_crew/runtime/service.py)
                                    │  SSE                    ▲                    │ mỗi phút: tick
                                    ▼                         │                    ▼
                              React SPA (web/)          team_tasks.sqlite3   spawn worker subprocess
                              màn Văn phòng 3D          office_room.sqlite3   (my_crew/runtime/worker.py)
                                                        approvals/dedup.db          │
                                                                              LangGraph step graph
                                                                              (my_crew/agent/*_graph.py)
                                                                                    │
                                                                          Action Gateway (my_crew/actions)
                                                                                    │
                                                                     Jira · Confluence · Slack · Email
```

## 3. Các thành phần

### 3.1 Web server (`my_crew/server/`)
FastAPI + 17 routers (`app.include_router`). Serve React SPA tĩnh từ
`static/app/`. SSE store-tail cho feed realtime (`routes_office_stream.py`). Auth
middleware: localhost + chưa đặt password ⇒ auth OFF; bind LAN bị từ chối trừ khi bật
web-auth (`assert_bind_safe`). `office_event_projection.py` = **PII firewall** (allowlist
theo kind AT WRITE TIME — room event không chứa nội dung tự do).

**Agent config routes (P4 v88):**
- `GET/PATCH /api/agents/{id}/profile-settings` — structured edits to name, model, model_chain, role_models, runtime.advisor_enabled, budget, schedule (via `profile_patch` helper)
- `GET/POST /api/agents/{id}/band` — autonomy band control (supervised/normal/trusted), separate SQLite write
- `GET /api/agents/model-catalog` — model id suggestions from `config/model_prices.yaml`

**Profile-patch helper (`my_crew/server/profile_patch.py`):** ruamel.yaml round-trip loader preserves comments and key order when writing profile.yaml updates. Whitelisted write surface: top-level scalars (`name`, `model`, `model_chain`), leaf-merged blocks (`safety.dry_run`, `budget.monthly_usd`, `runtime.advisor_enabled` — `runtime`'s infra keys checkpointer/store/postgres_dsn stay unreachable from the web form), and whole-block-replace mappings (`schedule`, `role_models` — free key sets, so a role dropped from the form must actually disappear from yaml; a leaf-merge would leave the old override in place and keep billing for it). Same pattern as `save_company` (P5-D0) for configuration preservation. One authoring
constraint follows from ruamel's comment model: a commented-out example block must sit
*above* the key it documents, never directly below an empty `key: {}`. ruamel folds a
key's inline comment and any comment block immediately following it into a single token
attached to that key, so filling that key from the form emits the new children below
those comment lines, making them read as the key's own children. A test guards the
shipped `profiles/default/profile.yaml` against this for every replaceable block.

### 3.1a Control-plane API (`my_crew/server/routes_control_plane.py`, phase 2 260830-1311)
`/api/control-plane/*` — stable HTTP contract cho caller NGOÀI SPA (script, CLI, agent
khác): `POST /delegate` (giao việc — 2 bước hash-bind mặc định, 1 bước khi
`confirm: true`), `GET /tasks/{id}` (trạng thái hợp nhất: state/steps/cost/delivery/
route), `GET /overview` (4 khối: registry/health/queue/approvals, MỖI khối fail-degrade
độc lập qua `control_plane_views._safe`). Thin wrapper — KHÔNG viết lại hash-bind:
`/delegate` gọi thẳng `ops_assign_team_task.preview_assign_team_task`/
`run_assign_team_task`, cùng hàm SPA composer dùng. Mọi response có `"v": 1`
(contract version). Auth: nằm trong `/api/*`, KHÔNG trong `auth._PUBLIC_PREFIXES` — được
`AuthMiddleware` bảo vệ y hệt SPA, không cần code auth riêng. `mpm crew assign|status|
overview` là CÙNG logic in-process (không qua HTTP) — hai bề mặt chỉ khác transport, gọi
chung `control_plane_views.py`. Chi tiết field + ví dụ curl: `docs/control-plane-api.md`.

### 3.1b Encrypted credential store (`my_crew/config/credential_store.py`, phase 4 260830-1311)
Credential mã hoá at-rest cho tài khoản dịch vụ ngoài (Zalo OA, Meta, tương lai Gmail
per-account): `.data/accounts/<account-id>/credentials.enc` — dict JSON (token/secret/
refresh/meta) mã hoá NGUYÊN BLOB bằng Fernet (`cryptography`, thêm vào dependency core).
Master key `MY_CREW_CRED_KEY` sinh tự động lần đầu dùng, ghi qua CHÍNH `env_writer
.merge_env` (whitelist `CREDENTIAL_STORE_WRITABLE_KEYS`) — cùng choke-point mọi secret
khác trong repo đi qua, không phải đường ghi `.env` mới. File mode 0600; ghi atomic
(temp + `os.replace`, cùng pattern `env_writer`); rotation giữ đúng 1 bản `.bak.enc`.
`account-id` validate cùng regex với agent-id (`runtime/agent_paths.py`) — chặn escape
khỏi jail `.data/accounts/`. `get` sai key/hỏng file → `CredentialDecryptError` rõ ràng,
KHÔNG bao giờ trả dict rỗng im lặng (rỗng trông giống "chưa cấu hình" → gọi API dịch vụ
ngoài không có auth, tệ hơn crash).

**Resolver chung** (`config/credential_resolver.py::resolve_service_credentials`):
nhận bất kỳ dict config nào, thứ tự ưu tiên `block["account"]` (account-store) →
`block["token_env"]` (tên biến env, indirection cũ từ `config/telegram_token.py`) →
`None`. Generic — KHÔNG import Zalo hay bất kỳ adapter cụ thể nào; adapter (Zalo P1,
ads-pack P6) tự gọi resolver thay vì tự đọc `.env`/store. Một reference CÓ MẶT nhưng
hỏng (account id sai, env var rỗng) raise thay vì rơi xuống nhánh sau — tránh gửi
request không xác thực bằng token cũ âm thầm.

**Web UI**: `GET/PUT/DELETE /api/connections/accounts[/<id>]` (`server/
routes_account_store.py`, mount vào `routes_connections.router` — không thêm router
mới ở `server/app.py`). Giá trị credential KHÔNG BAO GIỜ echo lại trong response hay
log — chỉ account-id + hành động, cùng posture với `env_writer.read_key_presence`.

**Threat model**: master key vẫn plaintext trong `.env` — NGANG mức hiện tại (mọi
secret khác trong repo cũng vậy), không tệ hơn. Store này KHÔNG chống lại kẻ tấn công
đã có quyền đọc cả `.env` VÀ `.data/` trên cùng host (không HSM/KMS). Nó chống: token
dịch vụ ngoài rơi vào backup `.data/`, log capture, hay `grep -r` toàn repo ở dạng
plaintext — giá trị chỉ tồn tại trong memory lúc giải mã để dùng.

### 3.2 Coordinator daemon (`my_crew/runtime/service.py`)
Vòng lặp mỗi phút: đọc registry, chạy scheduler (báo cáo định kỳ) + **team-tick**
(điều phối đội). Ghi `coordinator.heartbeat` mỗi vòng (health API + banner đỏ đọc file
này). Là process TÁCH BIỆT web app — web không tự dispatch việc.
**v65 — scheduler công bằng 2 tầng**: chọn agent theo round-robin STATELESS mỗi tick
(không agent nào đói định mệnh khi hàng đợi vượt trần spawn); pseudo-kind đúng-giờ
(`reminder-sweep`, mỗi phút quét `reminders.db` per-agent, DM Telegram đúng phút hẹn)
được MIỄN trần spawn — đúng-giờ không xếp hàng sau việc thường. **08-07**: `team-tick`
cũng miễn trần — chỉ có MỘT coordinator nên chi phí thêm bị chặn ở 1 worker/tick, còn
giữ nó sau trần thì phán quyết cho step hỏng chờ >3h (đo thật).
**v74 — dispatch hướng sự kiện (`tick_poke.py`)**: worker team-step thoát (mọi kết cục)
→ finally-touch `.data/tick.poke`; service ngủ lát 5s, thấy mtime poke vượt watermark →
spawn 1 team-tick sớm trên thread riêng (debounce theo lát, poke cũ trước khi daemon
start được coi đã xử lý). Nhịp 60s giữ nguyên làm fallback — mất poke chỉ trả về độ
trễ cũ, không mất việc. **v74.1 mở rộng 3 nguồn poke nữa**: (a) chính team-tick khi kết
thúc bằng action mở đường (`poke_worthy`: spawned/aggregated/stuck_retry/
stuck_reassigned/review_inserted/fanout_inserted — "none" và dead-end KHÔNG poke nên
chuỗi luôn tự dừng); (b) `run_assign_team_task` ngay sau confirm (dispatch đầu ≤5s thay
vì đợi nhịp phút); (c) row mint (review/fanout) → tick kế spawn trong lát ngủ. Đo qua 7
vòng benchmark: gap dispatch từ ~253s/task (11% wall-clock) xuống **0–8s mọi đường**,
kể cả dưới tải 2 task đồng thời. Song song per-task theo `company.yaml::
team_task_concurrency` (dispatcher spawn tới `concurrency - running`); KHÔNG có
single-flight per agent — hai bước cùng một agent chạy song song được nếu còn slot. **Khoá tick fleet-wide** (context-crew): tick do poke (thread riêng) và tick theo
phút từng chạy song song lên cùng một hàng `needs_decision` — cả hai đốt một lần can thiệp rồi ghi
đè phán quyết của nhau (đo live: retry có hướng dẫn bị reassign đè sau 19s, 4 can thiệp cho 1 lỗi).
`run_team_tick` giữ `flock` không chặn trên `team_tick.lock` dưới team-tasks root; tick thua trả
`status="tick_in_flight"`, không đọc store, không poke.

### 3.2a Integration health (`my_crew/server/integration_health.py`, v47)
**Health check Docker chủ động** (`_docker_check`): probe `docker info` giới hạn 5s, báo ✓/✗ sạch khi daemon tắt/offline — panel Sức khỏe noti lỗi TRƯỚC khi giao việc deep_agent (no-shell step chạy 0-Docker qua `create_agent`, chỉ needs_shell→deep_agent thì dùng Docker).
**Warm image opt-in** (`prepull_sandbox_image` + `mpm sandbox prepull`): tự tìm `SANDBOX_DEFAULT_IMAGE` ("python:3.12-slim"), present-check no-op → else pull không raise khi daemon tắt.

### 3.3 Worker (`my_crew/runtime/worker.py`)
Mỗi lần ticker cần chạy 1 bước việc → spawn 1 worker subprocess (`kind=team-step`) với
`--task-id --step-id --attempt-id`. Worker chạy LangGraph step graph rồi thoát. Isolation
per-agent (profile/data-dir/gateway riêng). Cũng chạy các kind khác: report, ops-alert,
milestone-mirror.

### 3.4 Team-task store + lease (`my_crew/runtime/team_task_store.py`)
SQLite WAL, single source of truth cho state đội. **Reserve-before-spawn + lease**:
`reserve_step` cấp `attempt_id` UUID + ghi `child_pid`/`lease_expires_at`; ticker chỉ
re-reserve khi lease hết hạn AND chưa có outcome artifact. Terminal write mang `attempt_id`
→ một worker cũ (zombie) ghi trễ thành no-op, không corrupt attempt mới.

**v67–v68 Task lifecycle discipline (P1)**: task field `delivery_status` (not_applicable / pending / success / failed)
tách khỏi `status` (task-level: open/done/stalled) để ghi rõ "chạy xong ≠ ghi ra ngoài được". Escalation
contract: `delivery_status='failed'` → escalate CEO tại delivery-sweep (không retry, cần CEO chỉnh kế hoạch
hay accept). Cơ chế `set_delivery_status` và `list_delivery_failed` query riêng. Audit: delivery failure
được ghi office event + append escalation suggestion từ `team_tick_collaborators` (constant template,
không field dấu hiệu injection).

### 3.5 Agent graphs (`my_crew/agent/`)
- `coordinator_graph.py` + `coordinator_nodes/` — ticker: chọn task, verify hash, dispatch
  bước sẵn sàng (cap song song 2), chèn soát chéo, escalate. v63: review theo cỡ việc —
  task ≤3 bước không `external_write` được waiver peer review (code-side,
  `task_decomposition.apply_review_waiver`); verdict `passed_with_notes` không mint
  rework, góp ý vào aggregate. `external_write` vào plan_hash CONDITIONAL (tiền lệ
  `needs_shell` — DAG cũ hash y nguyên).
- `team_task_graph.py` — chạy 1 bước: `perceive → work → (self_check | recover→work) →
  (deliver | rework→self_check)`. Consult đồng nghiệp trong `work`.
- `task_decomposition.py` — chia việc ≤7 bước; validate (acyclic/authz/PIC); hash canonical.
- `team_task_roster.py` — `planning_roster()`: roster cho decompose/sprint intake/replan, mỗi dòng `id (domain — gợi ý năng lực)` suy từ `Capability` (tier/web/mail) để planner giao bước cần công cụ đúng người; ids y hệt `assignable_staff()`.
- `review_graph.py` — soát chéo (peer review).
- `ops_*.py` — lệnh CEO: giao việc (`ops_assign_team_task`), chỉnh việc
  (`ops_adjust_team_task`), chat quản trị (`ops_chat`). v61: engine nhận catalog theo
  domain (`ops_catalog.catalog_for_domain`) — admin = full; personal (thư ký) = subset
  ĐIỀU PHỐI, không bao giờ thấy lệnh quản trị fleet (create_agent/set_enabled). v63
  thêm vào subset: gỡ-stall một chạm (`accept_stalled_result`/`retry_stalled_step`/
  `drop_stalled_step` — `ops_stalled_task.py`), `list_team_tasks` (bảng thẻ việc nhóm
  + retro soát/sửa/chi phí), `set_autopilot`/`get_autopilot`.
- **Autopilot (v63, CEO chốt "Toàn quyền thật" 2026-08-04)**: flag
  `company.yaml::autopilot` (đọc tươi mỗi quyết định — tắt là ăn ngay tick sau). Bật ⇒
  (1) kế hoạch tự xác nhận qua ĐÚNG đường hash-bind của `team_task_auto_confirm`;
  (2) task `stalled` được `runtime/autopilot_sweep.py` tự xử theo thang định trước
  retry→accept/drop, trần 2 lượt/task (`autopilot_attempts`), không LLM; (3) bước
  `awaiting_approval` Lớp B được ticker tự duyệt qua `transition_if_pending` (CEO bấm
  trước thì thắng race). Opt-out per-task: cụm "để anh duyệt" trong brief ⇒
  `team_tasks.require_ceo_approval` — vụ đó giữ mọi gate tay suốt vòng đời. Bất biến:
  Lớp A hard-deny + cost cap KHÔNG bị ảnh hưởng (test pin); mọi quyết định append
  office event `milestone: autopilot_decision` (audit) → admin mirror DM CEO
  (notify-after, không cần plumbing mới).

### 3.5b Sprint mode — bước một-người-làm-trọn, code điều nhịp (v77)

**Vì sao**: đề research vừa (5 thực thể × 3 tiêu chí) đi trọn DAG mất 23–31 phút vì mỗi
bước cold-start lại + soát chéo giữa chừng. Thử react-loop model-tự-lái thì tệ hơn: đo
**780s cho MỘT bước synthesis** trên fleet model (`qwen/qwen3.7-plus`) vs 60–120s native.
Kết luận: nhịp phải do **code** giữ, không giao cho model.

**Hình dạng**: sprint = **team task suy biến** — đúng 1 content step gắn
`step_type="sprint"` (`team_task_steps.CONTENT_STEP_TYPES = ("work", "sprint")`). KHÔNG có
nhánh runtime thứ hai: kanban/cost/lease/delivery/clarify/stuck/band/metrics dùng chung
đường cũ. Quy tắc chỉ áp cho việc fan-out phải hỏi `step_type`, không mặc định `"work"` —
một bước sprint tự phủ hết thực thể trong pipeline của nó và không bao giờ được fan out.

**Pipeline** (`my_crew/runtime/sprint_runner.build_sprint_work`, cắm vào graph qua
`work_override` trong `team_step_runner`; `self_check → rework → deliver → gateway` giữ
nguyên):

```
prefetch (code: 1 truy vấn/thực thể + 1 tổng quan, ≤ MAX_SPRINT_PREFETCH_QUERIES=6)
   → draft (LLM, 1 call)
   → coverage_gaps (code: thực thể nào chưa được phủ)
   → targeted-search + revise (LLM, ≤ MAX_REVISE_ROUNDS=2)
   → done          # trần cứng MAX_TOTAL_QUERIES=8
```

Truy vấn dựng bằng `_topic_phrase` — cắt tối đa `_MAX_TOPIC_WORDS=6` nhưng **tôn trọng
ranh giới cụm danh từ** (`_governs_next`/`_trimmed_to_whole_phrase`): cắt giữa cụm từng
làm search trả blog thay vì trang giá. `_source_refused` phân biệt "không tìm ra nguồn"
với "nguồn nói không có" — đề bịa thực thể phải bế tắc thật, không được bịa số liệu.

**v79 — sprint tool-less**: `build_sprint_work` nhận `needs_web` từ intake;
`needs_web=False` (việc viết/suy luận trên dữ liệu có sẵn trong đề) tắt TOÀN BỘ máy
search — không prefetch, không vòng coverage, không note THIẾU. Đo sống: một thank-you
note từng chạy prefetch định-sẵn-thất-bại rồi ship disclaimer về việc tra cứu nó không
hề cần. Kiểm soát chất lượng cho đường này dồn về bước review.

**Router** — v78 đổi từ MỘT phép đoán thành **phễu 6 lớp**, mỗi hướng sai có lưới đỡ
riêng nên bản thân phép đoán không cần đúng (4 lớp đầu ở `my_crew/agent/sprint_intake.py`;
dead-end ở `runtime/team_tick_collaborators.py`; cột `route_json` ở `team_task_store`):

| Lớp | Nơi | Vai trò |
|---|---|---|
| Tiền tố CEO | `strip_mode_prefix` | `sprint:`/`team:` chọn CHẾ ĐỘ, KHÔNG gỡ rào an toàn |
| Refusal cứng | `sprint_refusal` | 4 loại luôn về team: ghi-ra-ngoài, cần shell, CEO nêu cần nhiều người, việc dài nhiều giai đoạn |
| Heuristic cấu trúc | `classify_brief` | **Mặc định sprint**; chỉ đẩy team khi >1200 ký tự, >10 thực thể, hoặc ≥3 đầu việc tách dòng |
| Downgrade | `downgrade_to_sprint` | Chạy SAU decompose: plan suy biến (≤2 bước, 1 người, tuyến tính) → sprint, 0 lượt gọi model thêm |
| Dead-end | `_is_sprint_dead_end` | Sprint bế tắc (`gave_up`) → gợi ý CEO giao lại `team:`; `_mark_route_dead_end` ghi cờ riêng `dead_end` (KHÔNG đè `source`), phán quyết gốc giữ dưới `previous` |
| Kết cục thất bại | `_mark_route_failure` | Mọi escalation KẾT THÚC việc ghi `route.failure_mode` một lần (enum 5 giá trị trong `task_failure_mode.py`, nhóm MAST spec/verification/system); phán quyết trả bước về pending không ghi gì; `route_stats` mục "Kết cục thất bại" |
| Routing log | cột `route_json` | `mode`/`source`/`reason`/`signals`/`effort` — chỉ số, không chứa nguyên văn đề |

**v93 — nhãn ranh giới + fold cấu trúc (graph-engineering cho decompose)**: mỗi bước
trong plan team giờ phải KHAI vì sao nó xứng là một node riêng — field `boundary` trên
`TeamStepPlan` (`agent/task_decomposition.py`), 5 loại `BOUNDARY_KINDS`: `dependency` /
`concurrency` / `specialization` / `permission` / `human_gate`; rỗng cho mọi plan cũ.
Nhãn CHỈ quan sát: nằm ngoài content hash, không nhánh routing nào đọc nó; phân bố nhãn
ghi vào `route_json.signals.boundary_counts` (`boundary_label_counts`). Lưới cưỡng chế
thật là `fold_unjustified_steps` — chạy SAU fanout trong `ops_assign_team_task`, gộp
bước mà cấu trúc DAG không biện minh nổi: đúng-1-dep + cùng người + cùng cờ quyền =
việc của một người bị chẻ qua hai cold-start (hình dạng chain-death đo ở bench
lanes8/12). Fold cố ý BỎ QUA nhãn khai — justification suy từ cấu trúc thuần, nên model
bịa nhãn để giữ bước không được gì; fold lỗi thì fail-open giữ nguyên plan. Đường
sprint 0 diff.

**v93 — tiền kiểm định lượng trước LLM checker**: `_run_self_check` chạy
`machine_checkable_gaps` (`runtime/deterministic_step_check.py`) TRƯỚC khi gọi model
chấm: code đo phủ thực thể nêu đích danh trong acceptance và đếm số mục khi acceptance
đòi "liệt kê N …". Gap code tìm ra ⇒ fail ngay với confidence 1.0, không tốn lượt gọi
model; đo sạch ⇒ vào prompt checker thành dòng dữ kiện "CODE ĐÃ KIỂM"; không đo được gì
⇒ fail-open, prompt byte-identical thời trước. Bước sprint TẮT tầng này
(`deterministic_precheck=False`): pipeline sprint đã có `coverage_gaps` riêng, tầng đó
biết "nguồn từ chối cung cấp" không phải gap đóng được — để tầng code chung fail bước
đó là sai.

**Effort tier** — `sprint_intake` chấm độ khó BẢN CHẤT của việc, ngay trong lượt gọi intake
đã có sẵn nên KHÔNG tốn thêm lượt gọi model nào: "low" (rõ ràng, ít bước suy luận, dữ liệu
đủ trong đề), "medium" (mặc định), "high" (tổng hợp nhiều nguồn trái chiều, phán đoán
chuyên môn sâu). Ba bậc chứ không phải bốn — model nhẹ chấm 3 lớp đáng tin hơn hẳn — và
phân vân giữa hai bậc thì chọn bậc THẤP hơn.

Chỉ "low" đổi hành vi: dùng model role `sprint_low`, cắt budget tìm kiếm, và tối đa 1 vòng
sửa lại thay vì `MAX_REVISE_ROUNDS`. "medium" là hành vi cũ nguyên vẹn, đồng thời là đích
fail-open của mọi nhánh hỏng (intake chết, tier rác, tier lạ, hạ cấp từ team) — nên bán
kính ảnh hưởng ngoài "low" bằng không. Bậc lưu trong `route_json` chứ không thành cột
riêng: nó nằm sẵn cạnh kết cục của task, nên `route_stats` trả lời được "đề chấm khó bế
tắc bao nhiêu phần trăm". Vòng này CHỈ ĐO — effort chưa được quyền đổi lane.

`classify_brief` **lật chiều mặc định** (v77: nghi ngờ → team; v78: nghi ngờ → sprint).
Căn cứ là chi phí route sai **bất đối xứng**, đo ở `benchmark-260810-1602`: sai về phía
sprint thì dead-end kéo về sau vài phút; sai về phía team tốn 20m14s/$0.0757 so với
7m48s/$0.0191 trên CÙNG một đề, chấm mù 10 so với 29, **và không ai biết** — không có
tín hiệu nào báo rằng việc này lẽ ra một người làm là xong.

Lý do refusal không bao giờ nới: `_build_sprint_task` đóng cứng
`external_write=False`, mà `review_insert` lại bắt buộc review cho mọi bước
`external_write` ở MỌI band — đề ghi-ra-ngoài lọt vào sprint sẽ mất đúng vòng review nó cần.

**Sprint luôn có đúng 1 review ở mọi band** (chốt sau nghiệm thu v78 — ca trusted×sprint
từng ra 0 mắt soát): `_build_sprint_task` đặt `needs_review=True` và
`effective_needs_review` (`coordinator_nodes/review_insert.py`) không cho band trusted
waive bước `sprint` — waiver review nội bộ cho bước `work` giữ nguyên. Hết đường
zero-eyes ở mọi tổ hợp band.

**Giao kết quả (v79 tổng quát hoá từ sprint)**: artifact của bước terminal CHÍNH LÀ thứ
CEO cần. `_direct_result_text` (`runtime/team_tick_collaborators.py`) trả NGUYÊN VĂN
artifact khi plan hội tụ về MỘT bước nội dung terminal (sprint là ca 1 bước); nhiều
terminal mới đi đường tóm tắt `make_aggregate` — và ngay trong aggregate, bước terminal
cũng không còn bị cắt 500 ký tự (chỉ bước trung gian giữ trần, chi tiết của chúng đã tới
terminal qua deps handoff). **Terminality tính từ bước nội dung** (`_content_dep_targets`
— chỉ quét deps của row `work`/`sprint`): review/rework mint sau confirm khai dep vào
bước nó soát, nên quét deps trần từng làm mọi terminal-có-review "biến mất" và bản giao
lặng lẽ rơi về tóm tắt ("Bước 2: Đã viết xong bản thảo..." thay vì bài viết). Đánh đổi
giữ từ v77: lớp tóm tắt từng âm thầm gánh luật "bắt đầu NGAY bằng kết quả" — luật ĐỊNH
DẠNG nằm ở `_SYSTEM` của `llm/team_task_prompt.py`
(pin bởi `tests/test_team_step_prompt_format_rule.py`).

**Đo thật** (`plans/reports/benchmark-260810-0654-v77-sprint-vs-team-mode-report.md`):
cùng đề, team 31m12s/$0.0700 vs sprint 8m43s/$0.0169, chấm mù 8 vs 28 điểm.

### 3.5c Ngân sách review tầng task + phanh chi phí in-flight (v78–v79)

- **Trần review/rework theo TASK** (`coordinator_nodes/review_insert.
  _task_review_budget_exhausted`): trần theo-từng-bước (`MAX_REVIEW_ROUNDS=2`) không
  thấy được tổng — nghiệm thu đo một task 6 bước mint 11 review + 7 rework mà bước nào
  cũng đúng luật. Ngân sách = `_TASK_REVIEW_LOAD_FACTOR=2` × số bước nội dung, sàn 5
  (= một bước đơn lẻ dùng trọn trần bước: 3 review + 2 rework — trần task không bao giờ
  cắt sớm hơn trần bước). Chạm trần mà verdict vẫn fail → stall + escalate
  `task_review_budget_exhausted`, chung nhánh CEO-override với trần bước.
- **Phanh in-flight** (`runtime/team_task_halt.py`): `check_cost_cap` chỉ chặn spend
  MỚI — task `cancelled`/`stalled` rời `list_dispatchable()` nên worker đã spawn chạy
  nốt và vẫn tính tiền (đo sống: ~$0.05 cháy SAU lệnh huỷ, "cancel không phải phanh").
  Nay: (1) nhánh `cost_cap_exceeded` của coordinator stall TRƯỚC (an toàn không phụ
  thuộc phanh) rồi gọi `halt_running_steps` — kill qua `_kill_pid` pid-reuse-guarded
  (verify command line còn mang attempt_id), terminal write `TeamTaskStore.halt_step`
  atomic trên attempt_id AND status='running'; (2) hygiene mỗi team-tick chạy
  `run_cancel_reap_sweep` quét "task cancelled còn bước running" — derive tươi từ bảng
  nên đúng cho MỌI đường cancel by construction, giá là 1 tick trễ. Stall vì lý do
  khác (review cạn, ruling bước kẹt) chủ ý KHÔNG halt — phần việc in-flight còn lại
  vẫn được cần khi CEO resume.

### 3.5d Model 3 tầng: fleet → per-agent → per-role (v79)

`Settings.model_for_role(role)` (`my_crew/config/settings.py`, call-site `llm/client.py`)
trả về CHAIN: model override của role đứng đầu, đuôi là fleet chain — model rẻ là đúng
loại hay bị rate-limit/5xx, nên role degrade LÊN fleet model thay vì chết bước. Role hợp
lệ `MODEL_ROLES = ("content", "review", "aggregate", "plan", "util", "advisor", "sprint_low")` — chia theo cost
shape ("người có đọc output này không"), không phải capability; content là sản phẩm,
không bao giờ hạ cấp; sanitizer deep-agent chủ ý KHÔNG vào bucket nào (fail-closed gate
network sandbox, giữ nguyên fleet model). Role `sprint_low`: dành cho bước sprint khi
intake chấm công việc là EASY — unconfigured thì degrade về fleet, cho phép cấu hình
model rẻ chỉ cho công việc dễ thay vì toàn bộ content. Cấu hình per-agent trong profile.yaml: `model`
/ `model_chain` / `role_models` (yaml mapping hoặc chuỗi `"role=model,..."`, env fallback
`OPENROUTER_ROLE_MODELS`; validate ở `config_builders._d_role_models` — role lạ/trùng
raise rõ). Fleet default: `deepseek/deepseek-v4-flash-latest`
(`DEFAULT_MODEL`). Role chưa cấu hình → nguyên fleet chain, byte-identical pre-v79.

**Thứ tự 3 tầng (hẹp thắng rộng)**: `role_models[role]` trong profile.yaml của agent →
`model`/`model_chain` của agent → fleet chain (`OPENROUTER_MODEL`/`DEFAULT_MODEL`). Env
`OPENROUTER_ROLE_MODELS` chỉ là fallback cho tầng role KHI profile.yaml không có key
`role_models` — key có mặt trong yaml thắng env, kể cả mapping rỗng. Loader đọc
`role_models` ở TOP LEVEL của profile.yaml, còn `advisor_enabled` nằm dưới `runtime:`
(`profile/loader_mapping.py`).

**Role `advisor`** (v91): bucket cost cho ghi chú ride-along của cố vấn — mặc định TẮT
(`Settings.advisor_enabled = False`), bật per-agent bằng `runtime.advisor_enabled: true`
hoặc env `ADVISOR_ENABLED`; bool ghi rõ trong yaml thắng env (kể cả `false` tường minh).
Vì advisor chạy song song mọi bước nên nó là role đáng gắn model rẻ nhất — `role_models:
advisor: <model rẻ>` cho chain `(rẻ, fleet)`, degrade LÊN khi model rẻ rate-limit.

**Surface web** (v91): tab Hồ sơ của agent có ô "Model theo loại việc" (textarea `role =
model_id`, ghi đè NGUYÊN mapping nên xoá dòng = xoá override thật, không còn âm thầm
tính tiền) và ô bật/tắt "Cố vấn theo sát". Route dùng lại `_d_role_models` để validate
tên role và trả nguyên văn message của loader ra form — không cài lại luật ở lớp web.
GET **không** trộn giá trị env vào payload: hiện giá trị kế thừa trong ô sửa được sẽ khiến
một lần Lưu vô hại ghim luôn default của fleet vào yaml riêng của agent. Không cần restart
— tick loop và mỗi worker đọc lại profile.yaml mỗi lần dispatch.


### 3.5e Provider registry: `provider::model` (v91)

Trước v91 `LlmClient` chỉ dựng đúng MỘT client OpenAI trỏ `OPENROUTER_BASE_URL`. Nay mỗi
entry trong chain có thể mang tiền tố `provider::model` để đi qua một endpoint
OpenAI-compatible khác; entry trần (`org/model`) vẫn về OpenRouter y như cũ — không có
config nào phải sửa để giữ hành vi cũ.

- **Cú pháp**: tách ở `::` ĐẦU TIÊN (`llm/client.py::_resolve_entry`); id model gửi lên
  upstream là phần SAU tiền tố — tiền tố là routing của mình, vendor không biết nó.
  Chọn `::` vì id OpenRouter đã dùng hết `/` (org/model) và `:` (hậu tố `:free`).
- **Registry**: `Settings.providers` = tuple `(name, base_url, api_key_env)`, khai báo ở
  `providers:` trong company.yaml/profile.yaml (hoặc env `MY_CREW_PROVIDERS` dạng
  `"name=base_url|API_KEY_ENV,..."`). Chỉ chứa TÊN biến môi trường, không bao giờ chứa
  key — `_d_providers` từ chối thẳng giá trị trông giống key. Tên `openrouter` bị cấm
  đặt lại: nó là provider ngầm của mọi entry trần, đổi nó = bẻ lái cả fleet.
- **Client cache**: `_client_for(provider)` dựng lười và cache theo provider, nên chain
  đi ngang nhiều vendor không dựng lại connection pool mỗi lần fallback. Header
  `HTTP-Referer`/`X-Title` (attribution của OpenRouter) CHỈ gửi cho OpenRouter.
- **Fallback xuyên provider**: chain `("deepseek::deepseek-chat", "org/fleet")` — vendor
  rẻ chết thì bước vẫn xong trên fleet model, đúng ngữ nghĩa degrade-UP của v4 M9. Ghép
  với §3.5d: `role_models: advisor: vendor::model` cho cố vấn chạy hẳn vendor khác.
- **Lỗi**: provider lạ → nêu tên + liệt kê provider đã khai; thiếu key → nêu cả tên
  provider LẪN tên biến env (env-name indirection nghĩa là config không nói biến tên gì,
  thiếu một nửa thì operator không hành động được).
- **Giới hạn có chủ đích**: chỉ endpoint OpenAI-compatible (DeepSeek, Moonshot, Groq,
  Together, server local). API không tương thích nằm ngoài phạm vi. Chỉ provider dùng
  API key — KHÔNG OAuth subscription (quyết định ToS ghi trong plan).

### 3.5f Lane stats, effort tier, & benchmark v2 (v92)

**Effort tier** (`low|medium|high`, v92): LLM intake tự chấm trong JSON kế hoạch
(`sprint_intake()` → `SprintPlan.effort`); lưu trong `route_json` (không thêm cột), cùng với
`mode`/`source`/`reason`/`signals`. Chỉ `low` đổi hành vi: dùng model role `sprint_low` (rẻ hơn
nếu cấu hình), cắt budget tìm kiếm, tối đa 1 vòng revise. `medium` là hành vi cũ nguyên vẹn và
là fail-open của mọi nhánh hỏng (effort rác ép về medium, không cảnh báo). `high` vòng này CHỈ
để đo — đóng thêm cờ `route["effort_high"]` trong route record, chưa được quyền đổi lane và
chưa có chỗ nào trong runtime đọc lại (mới chỉ test đọc).

**Lane stats** (`my_crew/bench/task_metrics.py::load_lane_stats`, v92): đo thực tế trên live store.
Ba tỉ lệ lỗi tính TRÊN `routed_tasks` (chỉ task CÓ bản ghi định tuyến `route_json`), không tất cả
— task cũ trước v77 vào lane `unknown`, không đoán bừa: `dead_end` (sprint nhận việc rồi bế tắc),
`downgrade` (heuristic gọi team quá tay, lưới an toàn hạ xuống sprint), `upgrade` (một dead-end đã
được trả tiền lần hai để chạy lại bằng đội). Thêm `cost_usd` + `wall_clock_seconds` per-lane để so bản.
v93: route team ghi thêm `signals.boundary_counts` — phân bố nhãn ranh giới của plan SAU fold
(xem §3.5b) — nguyên liệu để route_stats trả lời "các bước được tách ra vì lý do gì" khi đối
chiếu giữa các vòng bench.

**Benchmark v2** (`my_crew/bench/`): bốn mode đo công việc sprint/team:
1. **routing** — offline, 0 model call. Chạy quyết định router trên bộ đề, diff hai bản (`routing_bench.py`).
2. **release** — offline, 0 model call. Tính chi phí dự định ở mỗi effort tier, diff hai bản.
3. **tasks** — online, read-only. Đọc store live, trả bảng per-lane cost/delivery/miss-rates.
4. **judge** — online, chi phí. Blind A/B chấm chất lượng deliverable (model độc lập từ task runner).

Live fullflow suite (`tests/fullflow_live/`, v92): 18 case end-to-end vs model thật, **opt-in**. 
`pyproject.toml` đặt `addopts = ["-m", "not live"]` nên `uv run pytest` mặc định skip; chọn với 
`-m live`. Không `OPENROUTER_API_KEY` → skip ngoài lỗi xác thực. Case assert trên `route_json` 
(route record chứ không prose), ổn định qua model nondeterminism.

### 3.5g Context-crew: vai = bộ năng lực, ba hình thái đội, bench giả thuyết (v0.17)

**Vai = bộ năng lực, không phải persona** (`team_task_roster.Capability(tier, web, mail, model)`):
suy từ profile — `tier` = `agent_runtime.kind` (native không gọi tool, `create_agent` có bộ
tool đọc, `deep_agent` thêm shell), `web_search` ⇒ web, `gws_context` + `gws_enabled` ⇒ mail,
model hiệu lực (profile ghi đè hoặc fleet). Tier là một trường riêng: agent tầng tool và agent
native cùng web + model vẫn là hai vai (đo live: thiếu tier, bước research của analyst
`create_agent` bị gộp vào bước của writer native, toolset không bao giờ được bind). `fold_unjustified_steps(task,
capability_of=…)` gộp hai bước kề nhau khi CÙNG bộ năng lực dù khác người được giao (bước của PIC
thắng khi gộp, giữ bất biến PIC-terminal). Profile không đọc được ⇒ `None`, không bao giờ bằng
một `None` khác — hai agent không ai đọc được không được gộp làm một.

**Hợp đồng artifact** (`step_artifact_contract.py`): hand-off giữa hai bước là artifact, không
phải hội thoại. Kind suy từ vị trí trong DAG: `findings` (bước thu thập không dep, `needs_web` ⇒
phải có ≥1 URL `http`), `draft` (bước giữa ⇒ không rỗng), `final` (bước cuối ⇒ ≥200 ký tự),
`verdict` (dòng review — `review_graph` chấm bằng schema riêng). `artifact_contract_gaps` chạy
bằng code TRƯỚC self-check LLM, cùng đường rework với `machine_checkable_gaps`; worker nhận
đúng một dòng hợp đồng trong prompt (`artifact_contract_line`). Kind lạ / text rỗng ⇒ không thêm
gap (fail-open cho caller cũ).

**Hình thái đội còn sống** (`crew_shape.classify_shape(task, signals)`, thứ tự ưu tiên):

| Hình thái | Điều kiện | Ranh giới một agent mạnh không vượt được |
|---|---|---|
| `permission_chain` | có bước `needs_shell` / `external_write` / `needs_mail` | quyền (an toàn) — không bench, không bao giờ rút |
| `do_review` | ≤3 bước, tín hiệu `needs_independent_review`; `mark_do_review` cắm `needs_review` vào bước cuối, reviewer ≠ author qua `pick_reviewer`; điều phối viết đè (judge accept hoặc `self_do_step`) GIỮ cờ soát qua `keeps_planned_review` — điều phối là tác giả, không phải người đọc độc lập | người chấm độc lập (H2 giữ) |

Hình thái thứ ba `fanout` (≥2 bước `needs_web` không dep + bước gộp) đã bị bench 260902 loại
(H1 + H3 chết, xem dưới): kế hoạch dạng toả ra/gộp lại nay không khớp hình thái nào ⇒ sprint
như mọi chuỗi cùng công cụ; `sprint_query_budget` co giãn theo số thực thể nên độ rộng là
việc của sprint. Fan-out RUNTIME của coordinator (`fanout_insert`, tách bước liệt kê thực thể
trong một đội đã tồn tại) là cơ chế khác, không đổi. Nhãn `fanout` vẫn còn trong
`route_stats` để đếm route cũ. Không khớp hình thái nào ⇒ sprint, `route.source="shape"`.
`team:` ép hoặc refusal ⇒ vẫn team, ghi `shape="custom"` khi không khớp (tiền tố là quyết
định của người giao, hình thái là quan sát). Refusal "ghi ra ngoài công ty" mà model quên cờ ⇒ `enforce_refusal_boundary` gắn
`external_write` lên bước cuối — cổng an toàn thắng cổng hình thái. `route_json.signals` thêm
`independent_sources`, `needs_independent_review`, `sensitive_tool`; mọi route team có
`route.shape`; `route_stats` đếm theo shape.

**Chống lãng phí** (cùng vòng): `MAX_REWORK=1`; can thiệp tối đa 1 cho bước cuối khi
`self_do_step` đã nối (bước giữa giữ 2); bước `needs_web` mà search hỏng ⇒ lỗi công cụ ⇒
machine retry (`MAX_STEP_RETRIES`), không đem artifact viết mù đi chấm; kế hoạch có bước không
đo được (`unmeasurable_gap`: acceptance không có số / từ khoá đo / kết quả thực thi như test,
build, exit / thực thể trong ngoặc) ⇒ retry rồi sprint `source="unmeasurable"` — trừ khi đề đã
bị TỪ CHỐI sprint (shell, ghi ra ngoài, nhiều người): cổng an toàn thắng cổng đo được, raise cho
CEO viết lại đề như `team:` ép (đo live: đề "clone repo rồi chạy test suite" từng trượt xuống
sprint không có ranh giới shell nào); `cost_cap_usd` mặc định 1.0 USD
cho tầng `create_agent`/`deep_agent` (`DEFAULT_STEP_COST_CAP_USD`, native giữ None), profile
ghi đè.

**Bench giả thuyết** (`bench/hypothesis_stats.py`): mỗi hình thái sống trên một giả thuyết có
ngưỡng giết cố định TRƯỚC khi đo, min 4 case × 3 run, Wilson interval báo kèm điểm ước lượng.
H1 fanout: thắng ≥2/3 cặp judge mù VÀ chi phí ≤3× sprint. H2 do_review: bắt ≥50% lỗi cài sẵn,
bất đồng giữa các run ≤25%. H3 chuyên viên rẻ + điều phối mạnh: không thua judge VÀ chi phí
≤70% sprint. Hình thái chết ⇒ rút khỏi `classify_shape`. **Kết quả vòng 260902** (4 case × 3
run, judge mù 3 phiếu/cặp, sprint = 1 agent mạnh có web): H1 CHẾT — đội toả ra thắng 4/12
(Wilson 0.14–0.61), chi phí 1.51× sprint; H3 CHẾT — chuyên viên rẻ (deepseek-v4-flash) dưới
điều phối mạnh chỉ tốn 0.59× nhưng thua 8/12, không phải "bằng chất lượng"; H2 GIỮ — reviewer
độc lập bắt 10/12 artifact cài lỗi (29/36 lỗi cài sẵn), bất đồng giữa run 8%. Chi tiết:
`plans/reports/bench-260902-1140-context-crew-h1-h3-keep-kill-report.md`.

**Ngang chuẩn harness tham chiếu (vòng 260903)** — ba hợp đồng nhỏ, đo bằng bench đã có:

- *Brief giao việc* (`step_delegation_brief.py`): worker nhận đúng tiêu chí nghiệm thu của
  bước mình (khối `TIÊU CHÍ NGHIỆM THU`, nguyên văn) và danh sách tiêu đề các bước anh em
  (khối `VIỆC CỦA BƯỚC KHÁC — KHÔNG làm ở đây`, bỏ dòng review + bước hệ thống chèn, tối đa
  6). Cùng một khối đi vào cả prompt làm lẫn prompt sửa (`build_team_step_messages`,
  `build_rework_messages`, tham số `delegation_brief`); runner dựng nó từ `step.acceptance` +
  `task.steps`. Đây là "objective + output format + boundaries" của brief uỷ quyền
  Anthropic, và là cách chữa lỗi MAST "bước làm lấn việc bước khác" mà live 260902 đã đo.
- *Nguồn đi theo artifact* (`ArtifactContract.upstream_sources`): runner đếm số URL phân
  biệt trong artifact của các dep (`_read_deps_handoff`, an toàn checkpoint) và đưa vào hợp
  đồng; bước `draft`/`final` nhận ≥1 nguồn mà thân bài không còn link `http` nào ⇒ gap bằng
  code, rework trước khi LLM chấm. Chỉ đếm dep, không đếm link CEO dán trong đề (bài học
  precision > recall của v93).
- *Hợp đồng kết cục thất bại* (`runtime/task_failure_mode.py`): bảng cố định
  `event_kind → failure_mode` (`cost_cap_exceeded→cost_cap`, `plan_hash_mismatch→plan_mismatch`,
  `review_rounds_exhausted→verification_exhausted`, `task_stalled_dead_step→dead_step`,
  `gave_up→step_exhausted`) và mode → nhóm MAST. `_escalate` đóng dấu một lần cạnh quyết
  định định tuyến; `route_stats` đếm theo mode và nhóm để retro trả lời "lỗi ở đề, ở soát,
  hay ở máy". Mode lạ (ghi bởi bản mới hơn) vẫn đếm dưới tên thô, nhóm "khác".
- *H4 — hiệu chuẩn bộ chấm* (`verdict_calibration`, `H4_MAX_FALSE_FAIL = 0.25`,
  `H4_MIN_CATCH_RATE = 0.5`): bộ chấm chỉ "keep" khi đồng thời ít báo động giả trên artifact
  ĐÚNG và bắt được lỗi cài; mỗi vế có sàn mẫu riêng (12) nên bộ chấm "luôn đạt" hay "luôn
  trượt" đều không qua. Đo trên Haiku (260903): self-check và review cùng 3/12 báo động giả,
  10/12 bắt được — keep sát vạch; cả 6 báo động giả là một dòng rubric mập mờ (cọc có tính
  vào tổng 24 tháng không), và cả hai bộ chấm đều không cộng cột ngân sách (lỗi tổng 95≠90
  lọt 0/3). Bench cũng lộ lỗi thật ở gate code: `_MIN_ITEMS_RE` đọc "cộng đúng 90 triệu"
  thành "≥90 mục" — đã sửa (đơn vị/thập phân ngay sau số không phải yêu cầu số lượng).

### 3.6 Action Gateway (`my_crew/actions/`, v30–v31, v67–v68 learned rules)
`action_gateway.py` = cửa duy nhất. `hard_block.py` = Lớp A (chặn cứng, không duyệt được).
Lớp B = phụ thuộc `safety.trust_mode` per-agent:
- **autonomous** (mặc định): tự chạy ngay → audit log rationale "trust_mode=autonomous".
- **guarded** (opt-in): chờ CEO duyệt (`approval_store.py` + `auto_approve_policy.py` chỉ dùng khi guarded).

**v67–v68 Learned rules (Lớp B pattern memory)**: Khi CEO duyệt/chặn hành động Lớp B, thêm cờ `--always` hoặc `--deny` để ghi rule (pattern + target); lần sau action cùng pattern + target tự quyết (ALWAYS: chạy → audit rule id; DENY: từ chối không queue). Chỉ áp ở guarded mode — autonomous giữ toàn quyền (CEO quyết định 2026-08-04). Store per-agent (`approval_rules` bảng trong `approvals.db`). CLI: `mpm agent approve <id> <approval-id> --always` / `mpm agent reject <id> <approval-id> --always` (tạo rule); `mpm agent rules <id>` (liệt kê); `mpm agent rules <id> --revoke <rule-id> [--confirm]` (hoàn tác, deny rule cần `--confirm`). Đổi tham số bind (recipient, channel, repo) → miss → hỏi lại. Lớp A + kill-switch + dedup vẫn áp trước rule (rule chỉ decide Lớp B, không bao giờ nới Lớp A).

**Native action types (v31)**: `schedule_update` (agent đổi lịch báo cáo chính mình), `team_task_create`/`team_task_move` (kanban), `gws_write` (Google Sheets/Docs append+create). (`academic_search` OpenAlex thêm ở v31, **gỡ ở 0.17.0** — rate-limit theo IP, 429 mọi lần bench; tra cứu dùng `web_search`/scrape.) Các handler `*_write.py` khác (jira/confluence/slack/email) — đều gọi qua gateway, không lối tắt.

**Agent creation (v32)**: Template-based create-from-template / crew bootstrap (`my_crew/server/template_create.py`) both build spec server-side from `profiles/templates/`, then go through the same `agent_create.create_agent(spec)` door as wizard — no bypass, new agents land DISABLED (CEO sets .env tokens, then enables on Team page).

### 3.6a Fleet activity audit (v31, v46, v50 UI)
**Hậu kiểm đội**: mọi hành động qua gateway ghi vào `audit.jsonl` (per-agent), `runs.jsonl` (lịch sử chạy), `captures.sqlite3` (chi phí). **Web surface** (`routes_visualize.py` + `visualize_views.py`): GET `/api/company/activity` trả audit rows (allowlist-projected, KHÔNG raw args chứa dữ liệu nhạy), phân trang, filter theo agent/loại. **Ops-chat command** (`ops_company_activity.py`): readonly lệnh mới `company_activity` (LLM tóm tắt hành động đội tuần này → gửi chat nội bộ, KHÔNG external).
**v46 — Actor attribution**: mỗi `AuditEntry` ghi field `actor` (agent `profile_id` hoặc `""` cho lệnh CLI) — 1 choke point `_record` stamp actor trên MỌI outcome branch (allow/deny/dry/dedup). `approvals.actor` (sqlite ALTER migrate-free) cho phép query filter "ai duyệt gì".
**v50 — UI surface**: AuditTable column "Ai thực hiện" render `actor` (or "—" nếu rỗng); CompanyActivity tag "[bởi {actor}]" khi actor≠log-owner (điều phối).

### 3.6b Operator channels (v90)

**Seam báo vận hành đa đường**: `my_crew/runtime/operator_channels.py::send_via_channels()`
thử lần lượt Telegram → SMTP → Webhook, dừng ở kênh đầu tiên gửi được. **Vì sao**: escalation
trước đây chỉ biết Telegram; đo trên fleet thật thấy **7/11 agent không có kênh nào**, tức
người vận hành không dùng Telegram thì không có đường báo nào cả.

**Hợp đồng 3 trạng thái** — điểm mấu chốt của seam này:

| Trả về | Nghĩa | Caller làm gì |
|---|---|---|
| `True` | một kênh đã gửi được | dừng |
| `False` | có kênh nhưng gửi hỏng | dừng, coi như thất bại |
| `None` | agent này **không cấu hình kênh nào** | **đi tiếp** sang agent kế trong danh sách |

`None` tách khỏi `False` vì caller (`operator_notify._try_send`) duyệt một danh sách agent
theo thứ tự điều phối → dự phòng → admin. Gặp agent câm phải đi tiếp; gộp chung với lỗi gửi
sẽ dừng cả vòng duyệt ngay ở agent đầu tiên không có kênh.

**Cấu hình bằng biến môi trường, KHÔNG phải `company.yaml`**: `OPERATOR_EMAIL` (người nhận
SMTP) và `OPERATOR_WEBHOOK_URL` (endpoint nhận POST). Lý do không dùng yaml: `save_company`
dựng lại file từ một dict cứng, nên mọi key viết tay sẽ bị nuốt ở lần lưu kế tiếp.

`send_plain_email` đặt trong `my_crew/actions/email_write.py` chứ không tách module mới —
guard `test_smtplib_imported_only_in_email_write` giữ `smtplib` chỉ có một nhà.

Consumer đi qua seam này: `operator_notify._try_send`, `team_tick_collaborators._escalate_direct`,
`ops_alert_runner.run_ops_alerts`. Trạng thái kênh đọc được ở mục `operator_push` của
`integration_health` (hiển thị trong hub Đội ngũ).

### 3.7 Domain packs (`domain-packs/`)
Kiến trúc pluggable: `pm-pack` (mặc định), `hr-pack`, `office-pack`, `admin-pack`,
`personal-pack` (v57 — thư ký riêng: catalog M12 set_reminder/send_email/create_event…,
briefing, gws Gmail/Calendar). Mỗi pack = graphs + tools + analyzers + write_handlers +
allowlist. `my_crew/packs/registry.py` discover pack từ filesystem. Lõi (`my_crew/`)
không chứa logic domain.

**P6 — ads-pack + accounting-pack**: cùng shape push-graph kiểu personal-pack
(perceive→analyze→compose→deliver, Telegram DM). `ads-pack`: đọc Meta Marketing API v25.0
qua `urllib` thuần (không dependency mới) — report `ads-weekly`, ZERO writes
(`write_handlers.ALLOWLIST` rỗng). `accounting-pack`: đọc sổ quỹ qua gws Sheets HOẶC CSV cục
bộ (`ACCOUNTING_LEDGER_CSV_PATH`, fallback offline) — report `cashflow-weekly`, một write duy
nhất `append_ledger_row` đi qua `commands.py::COMMANDS` (kiểu `gws_write`, không phải
`write_handlers.ALLOWLIST`), sheet đích bị PIN theo cấu hình, guarded mặc định (Lớp B).
Cả hai: lỗi nguồn ngoài → fail-degrade render sentinel "THIẾU" từng số liệu (không bao giờ
bịa số); thiếu biến môi trường cấu hình → raise fail-loud.

### 3.8 Memory provider seam (`my_crew/memory/`, v19)
`resolve_memory_text(loaded)` là MỘT cửa mọi prompt path lấy memory text (thay 6 call-site
đọc `loaded.memory`). Provider chọn qua `memory:` block trong profile.yaml: `static`
(MEMORY.md verbatim, mặc định, byte-identical) | `kioku` (my-kioku subprocess — HOÃN v19.5,
chọn nay raise rõ). Memory tiếp tục vào INTERNAL user-msg qua `build_context_block`
(external nhận 0 byte — red line giữ). Workspace mỗi agent thêm `vault/` (reserved kioku)
+ `skills/` (per-agent, body wrap `format_internal_content`, không shadow pack skill).
Capability block auto-gen (`capability_block.py`) cũng INTERNAL-only cùng path.
**v66 — trí nhớ bền cross-agent**: `runtime.store` default `sqlite` → MỘT store chung
`.data/memory_store.sqlite3` (langgraph SqliteStore, autocommit); fact rút ra sau mỗi
việc sống qua restart và đọc chéo giữa agent (khối "trí nhớ đồng nghiệp" wrap
`format_internal_content` — data-not-instructions). Per-profile `memory_share:
full|read_only` (thư ký = read_only: đọc của đội, KHÔNG chia sẻ ngữ cảnh riêng tư CEO
ngược lại). Retention 90 ngày trong sweep. Bài học v66: máy móc có từ v2 nhưng store
chưa từng được truyền vào graph compile — "đã wired ≠ có điện", chỉ UAT sống mới lộ.

### 3.9 AgentRuntime backends (`my_crew/runtime_backends/`, v20–v45)
Tách agent-LOOP khỏi điều phối + an toàn. Backend được chọn PER-STEP qua
`resolve_step_runtime(loaded, step)` (v45 — xem "Định tuyến per-step" cuối §3.9); `resolve_runtime(loaded)`
(chọn theo `agent_runtime:` của cả agent — native|create_agent|deep_agent; default native, kill-switch
`RUNTIME_FORCE_NATIVE`) vẫn là nền cho report + fallback. `NativeGraphRuntime` = graph hiện tại byte-identical.
`ToolCallingRuntime` = tool-calling loop; từ v86 mặc định là **thin loop tự chủ** trên OpenAI SDK
(`thin_tool_loop.py` + `typed_tool_specs.py` — typed specs + generic fallback nên không tool nào bị rớt;
cost EXACT từ usage extras; profile đặt `loop_engine: langchain` để chạy lại đường `create_agent`
langchain.agents cũ làm baseline A/B) NHƯNG swaps chỉ `run_work` nên deliver (ghi artifact
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

**v74 — tier theo bước (`needs_web`) + fan-out**: đo thật (task b4c227ec37ba) 64% wall-clock là bước
KHÔNG-tool chạy tier nặng (qa 548s deep, finalize 780s loop). Decompose gán `needs_web` per-step (true
CHỈ KHI bước tra cứu web lấy dữ liệu mới; flag PHẢI nằm trong schema ví dụ của prompt — chỉ mô tả bằng
văn không đủ, model mirror ví dụ); `resolve_step_runtime` ép **native one-shot** cho bước work
`needs_web=false` chưa can thiệp + mọi review row (tool-less grading); rework row GIỮ tier agent (sửa
lỗi dữ liệu cần tool — bài học vòng 7); hint sai tự hồi phục sau ruling đầu (`intervention_count≥1` bỏ
ép). Bind hash có điều kiện như `needs_shell`. Hint-only, không phải quyền — tier native không vì thế
có thêm tool nào. Decompose thêm QUY TẮC TÁCH SONG SONG: đề ≥4 thực thể độc lập cùng dạng → 2-3 bước
collect deps rỗng, tên thực thể đích danh trong title + acceptance.

**Context-crew thu hồi phép ép native theo `needs_web`**: tier là một trường của VAI
(`Capability.tier` — bộ (tools, permissions, model, artifact schema)), không phải phỏng đoán tốc độ
theo bước. Đo lại trên fleet có agent tier tools: bước tra lịch sử nội bộ được kế hoạch giao ĐÚNG
cho agent tier tools bị ép native, không bind toolset nào, đốt hết mọi lần can thiệp chỉ để giải
thích là không tìm được. `resolve_step_runtime` giờ: review/sprint → native; bước work `prefetched`
(launcher đã nhét dữ liệu web vào prompt) chưa can thiệp → native; còn lại chạy đúng tier của
assignee (fleet mặc định vẫn native nên tốc độ không đổi). Tốc độ đến từ planner gộp bước cùng
tier, không từ việc ghi đè vai lúc dispatch.

**v74.1–74.2 hoàn thiện (kiểm chứng qua 7 vòng benchmark, xem
`docs/journals/260808-v74-multi-agent-speed.md`)**:
- **Row mint kế thừa cờ**: runtime-split sub kế thừa `needs_web` của bước cha qua param
  keyword-only (pattern `needs_review` — không bao giờ đọc từ dict caller); gather giữ False.
  Bug đo được dưới tải: sub flagless bị ép native searchless, mỗi sub đốt 1 ruling tự hồi phục.
- **Fan-out ép bằng code** (`task_decomposition.fanout_gap`): đề liệt kê ≥4 thực thể (heuristic
  danh sách sau dấu hai chấm) mà plan không có ≥2 collect `needs_web` deps rỗng → trả lỗi vào vòng
  retry decompose; FAIL-OPEN lượt cuối (plan chậm vẫn hơn giao việc hỏng); plan thuần viết không bị ép.
- **Cạn loop không còn trả rỗng** (`community_loop_core.invoke_capped`): chạy qua stream giữ state
  cuối; overflow → 1 lượt tổng hợp bounded từ transcript dở ("dừng tool, thiếu ghi THIẾU"), hỏng nữa
  mới degrade rỗng.
- **Dead-step reset đổi người**: bước `needs_web` chết mà assignee không search được → reset chuyển
  cho đồng nghiệp web-capable đầu tiên (`agent_web_capable` — cờ + sandbox network cho deep tier);
  `_can_do_step` cũng chặn reassign vào agent không search được khi bước khai `needs_web`.
- **Số chốt** (baseline vòng 8 = 40'/$0.05): đề khảo sát 5-6 thực thể giờ ổn định **11–16'**,
  $0.02–0.05, gap dispatch 0–8s; biến động còn lại = chất lượng dữ liệu nguồn + vòng review/clarify
  (hành vi đúng, không tối ưu bỏ).

**v75 — coordination chủ động (học chọn lọc Hermes/OpenClaw, xem
`docs/journals/260809-v75-proactive-coordination.md`)**:
- **Sentinel 3-path** (`web_search_outcome`): "web nói không có" ("empty") ≠ "không tới được web"
  ("provider_error") — cả native hook lẫn tool-loop `web.search` render 2 sentinel khác nhau, chặn
  chuỗi "nguồn sập → bước kết luận 'dữ liệu không tồn tại'". Watcher tick toàn-lỗi trả
  `all_polls_failed`, không bao giờ đội lốt `no_change`. Wake-context line theo attempt đi kênh
  guidance (retry/rework biết mình là lần thử thứ mấy).
- **Goal-replan** (`runtime/goal_replan.py`): ladder autopilot 3 rung — retry → **replan** (amend-LLM
  đề xuất cách tiếp cận khác cho phần bước chờ, qua ĐÚNG flow amend draft + hash-guarded confirm;
  fail-CLOSED: LLM lỗi / đề xuất giữ nguyên / hết bước chờ = từ chối, stall + escalation đứng nguyên)
  → accept/drop. Rung replan là rung LLM duy nhất của ladder.
- **Hybrid collect launcher** (`runtime/collect_prefetch.py`, pattern Hermes launcher): bước
  `needs_web` lần-đầu no-shell được CODE chạy 1-3 query (title + biến thể topic+entity, không LLM)
  qua đúng WebSearchConfig + audit, bundle inject vào slot search-hook → route native one-shot
  (`resolve_step_runtime(prefetched=True)`). Fail-open: không có kết quả sạch → tool-loop như cũ;
  bước bị can thiệp không prefetch (self-heal giữ tier agent + tool sống). Đo sống: collect 119s
  gap 2s (vs 199–425s tool-loop).

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
**Không LLM poll — chỉ khi nội dung đổi:** `watchers:` block trong profile.yaml (jira/github/sheets sources). Service mỗi 5 phút poll → normalize → hash. Nội dung KHÔNG đổi = 0 LLM (measured capture store). Đổi → wake 1 lần: dispatcher tạo 1 step team-task pre-built (không LLM phân rã), assigned agent chính nó. **Alerts**: fail ×3 → CEO Telegram báo; no-change >24h → stale alert. Modules: `my_crew/runtime/watcher_store.py`, `watcher_normalize.py`, `watcher_runner.py`, `operator_notify.py`.

### 3.10 Telemetry capture + unified cost (v26, v50 UI)
Mỗi team-step attempt ghi telemetry vào `captures.sqlite3` (17 columns: attempt_id, task_id,
step_id, agent_id, engine, status, step_type, review_round, cost_usd, cost_source, input_tokens,
output_tokens, started_at, ended_at, duration_ms, error, ts). WAL+busy_timeout tương tự
team_task_store. Hook `run_team_step` thu thập lúc step kết thúc (best-effort, log WARNING
nếu fail, không tắc quy trình). **INTERNAL state — không qua gateway** (`capture_db_path()` trong
team_task_paths.py). Unified cost: thin loop (mặc định tier react từ v86) ghi cost EXACT từ
usage extras OpenRouter; chỉ còn `loop_engine: langchain` + deep_agent dùng `config/model_prices.yaml`
(mô hình đặt giá chỉnh sửa được, ví dụ placeholders minimax/qwen), estimate cost = Σ tokens ×
per-model price, column `cost_source = 'estimated' | 'exact'`.
Remember-node extends team-step: deliver→remember→END (CostedMemoryExtractor ghi facts vào
MEMORY.md, gộp cost LLM vào captured step cost), gated on delivered + internal + not-dry-run.
Modules: `my_crew/runtime/capture_store.py`, `my_crew/llm/model_pricing.py`, `my_crew/runtime/step_telemetry.py`.
**v50 UI**: GET `/api/team-tasks/{id}/cost` (read-only, allowlist-projected) trả per-step-attempt cost + task total; TeamTaskCost component lazy-expand "Chi phí" trên kanban card.

**v48 — MCP session pool wrapping team-step**: team-step call_tool (mcp_tool) giờ chạy TRONG `_run_with_mcp_pool` (như report/inbox/tasks branches) — 1 subprocess MCP/server dùng lại qua step thay vì spawn node mới per-call. Eliminate spawn-per-call overhead cho office cross-synth (92s→faster).

### 3.10b Secretary heartbeat (v68, P3)
**Proactive digest + optional DM**: thư ký định kỳ (opt-in `heartbeat.every` trong profile.yaml,
ví dụ `heartbeat.every: 30m`) quét digest: tasks stalled, delivery failed từ P1, reminders sắp reo, drafts
awaiting_confirm quá hạn. Digest rỗng → 0 LLM call (miễn phí). Có signal → 1 lượt LLM nhỏ cố định, reply
≤300 ký tự được gửi Telegram; ngược lại drop (kiểm soát spam). Defer khi đang mid-conversation hay secretary
chạy (ghi `heartbeat_deferred`). Suppression contract: 3 lỗi heartbeat liên tiếp → auto-stop + báo CEO.
Module: `my_crew/runtime/secretary_heartbeat_runner.py` + `secretary_heartbeat_digest.py`. Service loop mỗi
phút check trigger (v65 scheduler). Loop-prevention: heartbeat chỉ báo + đề xuất, không tự giao việc.

### 3.10c Task reflection (v68, P4)
**Memory học từ outcome terminal**: khi task vào done/stalled, enqueue 1 lượt reflection (inline, bọc trong
`_reflect_safely` nuốt exception — reflection là vệ sinh, không định sẵn thất bại tick). Reflection chạy
`is_durable_lesson` guardrail: cấm transient claim ("web_search timeout"), infra claim, blanket refusal,
tool-name + complaint (pattern `\b(dung|de|cho|lam)\b` phân biệt "dùng web_search"). Output ghi vào
`(coordinator_id, "memory")` namespace — bài học là về cách coordinator giao, không worker riêng; sibling
agent đọc qua `sibling_memory` sẵn có. Cooldown marker riêng ở `(coordinator_id, "reflected")` để tránh
bury fact giữa bookkeeping (marker viết mỗi lần, lesson hiếm) — sweep 90d không xoá marker làm re-open
task stalled cũ. Cost tính vào `BudgetTracker` sẵn (không cột DB mới). Module: `my_crew/agent/task_reflection.py`.
Consolidation sweep (v35, chạy 03:00 nightly) giữ nguyên, lesson chỉ là memory thường.

### 3.11 Frontend (`web/src/`, v88 redesign)

React 19 + Vite + TanStack Query. SPA phục vụ tại `/` (StaticFiles `html=True`), build dist
commit vào `my_crew/server/static/app/`.

**IA 5 hub.** `/chat` (màn nhà) · `/office` (3D) · `/work` · `/team` · `/system`. Mỗi màn
trước redesign giờ là một **tab có URL riêng** (`?tab=`) bên trong hub đã hấp thụ nó, nên
deep link mount đúng tab khi cold load. Bảng route ở `app/app-routes.tsx` giữ 21 redirect
cho mọi URL cũ (`/settings`, `/cost`, `/agents/:id`…); `/agents/:id` giữ id trong path.

**Cấu trúc.** `features/<hub>/` thay cho `views/` phẳng:

```
web/src/features/
├── chat/     # màn nhà: danh sách hội thoại, composer, thread
├── office/   # sàn bàn làm việc + 3D (office-3d/), activity feed, quick assign,
│             #   workroom list, review tray, health strip, artifact panel
├── work/     # board, hàng đợi duyệt, task detail, outputs, company activity
├── team/     # roster, agent detail (agent-detail/), hire panel
├── system/   # settings, connections, company, insights, audit
├── shared/   # dùng bởi >1 hub: assign-composer, artifact-viewer, transcript-tab,
│             #   coordinator-health-banner, office-message-line, phase-labels
└── palette/  # command palette (không phải hub)
```

`web/src/views/` chỉ còn cửa trước auth (`Login`, `Setup`, `setup-company-step`) — nó
mount ngoài shell nên không thuộc hub nào.

Cổng vào vẫn là `main.tsx` → `App.tsx` (chỉ là cửa setup/login, cố ý giữ mỏng) →
`app/app-providers.tsx` (chỉ còn query client) → `app/app-routes.tsx` → `app/app-shell.tsx`.
Theme/language/ui-mode provider nằm ở `main.tsx`, ngoài cửa auth.

**Tầng dữ liệu** (`web/src/api/queries/`). TanStack Query thay các hook fetch rời + 2 global
context cũ (`AgentProvider`, `PendingApprovalsProvider` — agent giờ nằm ở route, approvals là
1 query cache; bỏ được vòng fan-out 30s toàn fleet).

- `query-keys.ts` — factory key **duy nhất**; là thứ cho cầu SSE gọi đúng slice.
- Query theo hub: `use-office-queries.ts`, `use-work-queries.ts`, `use-team-queries.ts`,
  `use-system-queries.ts`, `use-agent-detail-queries.ts`.
- Dùng chung: `use-agents-queries.ts`, `use-approvals-queries.ts`, `use-artifact-queries.ts`,
  `use-clarify-queries.ts`, `use-auto-approved-query.ts`.
- `sse-invalidation-bridge.ts` — ánh xạ **kind sự kiện phòng → các slice query có thể đã đổi**.
  Cố ý là bảng thuần (không import `QueryClient`) để test được như dữ liệu: một kind lặng lẽ
  thôi invalidate một slice là một màn lặng lẽ thôi cập nhật, không test render nào bắt được.

**Chunk tách rời** (số đo từ lần build gần nhất): `agent-desk` 900 kB (94% là `three`+r3f, chỉ
tải sau `/office`) · `chart-theme` 173 kB (chỉ Cost/Guardrail) · `agent-detail-page` 23 kB ·
`office-page` 20 kB · `office-canvas` 19 kB · `task-detail-page` 3.5 kB. Entry `index` **475 kB**
(cổng ≤560).

## 4. Luồng dữ liệu chính: giao 1 việc

1. CEO gõ brief vào `/chat` (hub home) → message gửi backend.
2. Backend `routes_office_assign.preview` → `ops_assign_team_task.preview` —
   phễu định tuyến (§3.5b) quyết sprint/team trước; đường team: 1 LLM call phân rã →
   validate code-side → `downgrade_to_sprint` kéo plan suy biến về sprint → lưu draft
   (status `planning`) + hash.
3. CEO xác nhận (hoặc auto-confirm) trong **Chat** → `confirm_plan(hash)` TOCTOU-proof → task `open`.
4. Coordinator daemon tick kế: đọc task, `_verify_plan_hash` (chống tamper), dispatch
   bước sẵn sàng → spawn worker.
5. Worker chạy step graph → `deliver` ghi artifact `step-<n>.json` + append office event.
6. SSE đẩy event → **TanStack Query invalidates** affected keys → FE components re-render:
   - **Chat** hub: task confirmation feedback
   - **Office** hub: 3D desk updates, workroom list, action queue
   - **Work** hub: kanban board refresh, queue updates
   - **Team** hub: agent status updates
7. Bước done `needs_review` → ticker chèn soát chéo. Bước cuối (PIC) xong → task done.
8. Bước "ghi ra ngoài" (nếu có) → Action Gateway → Lớp B chờ CEO duyệt ở **Work → queue**.

### 4a. Vòng phán đoán khi step hỏng (cứng hoá 08-07/08-08)

- **Mọi step thấy đề gốc**: `original_request` của CEO mở đầu khối handoff của TỪNG
  step — worker không bao giờ phải đoán chủ thể từ title chung chung, và grader có căn
  cứ đối chiếu (`team_task_graph._read_handoff`).
- **Grader neo thực tại**: self-check + peer-review mở đầu bằng "HÔM NAY là <ngày>"
  (dữ liệu mới hơn kiến thức model ≠ bịa) và **luật TRẦN**: tiêu chí do decompose sinh
  ra đòi CAO HƠN đề gốc thì chấm theo đề gốc (`team_task_check_prompt`). Tiêu chí đếm
  được (link, N mục) phải kiểm thật. Lý do trượt lưu vào artifact
  (`self_check_failures`).
- **Guidance không đóng băng**: khối "CHỈ DẪN CỦA ĐIỀU PHỐI" trong handoff chỉ được
  vòng rework ĐẦU của attempt tiêu thụ; perceive các vòng sau strip nó đi (giữ lại dòng
  wake-context `Bối cảnh:` của rework soát chéo — dòng đó là bối cảnh đứng, không phải
  chỉ dẫn cũ; anchor strip bằng `rfind` để header bị nội dung nhại không cắt nhầm).
  Trước fix, guidance sống cả attempt: vòng rework 2 bị nhắc sửa đúng thứ vòng 1 vừa
  sửa → cascade drop/salvage (nguyên nhân top bước chết vòng 6, bench vòng 7 xác nhận
  0/4→3/4 sống sạch) (`team_task_graph.GUIDANCE_HEADER/_strip_guidance`).
- **Retry-first**: phán quyết ĐẦU TIÊN cho một step kẹt luôn là retry-with-guidance
  (đo 5/6 reassign-lần-đầu là sai); reassign chỉ từ phán quyết thứ hai, và gate năng
  lực xét cả TIER runtime (deep_agent sandbox không mạng ≠ biết search, dù cờ
  `web_search` bật) (`stuck_decision`, `team_tick_runner._web_search_enabled`).
- **Redo xoá checkpoint**: retry/reassign/CEO-retry là LÀM LẠI — thread checkpoint của
  attempt chết giữa chừng bị xoá, không adopt (adopt nhảy qua perceive nên guidance
  không bao giờ được đọc; resume crash cùng-attempt giữ nguyên)
  (`team_task_store.reset_step_to_pending/reassign_step`).
- **Nút bấm hành động thật**: câu hỏi nhắc-việc-kẹt rung 2 ("Đợi thêm"/"Huỷ việc này")
  được follow-up sweep tiêu thụ — huỷ là huỷ thật + mốc ❌ vào feed, mỗi câu trả lời
  chỉ hành động một lần (`follow_up_sweep._consume_ceo_answers`).

### 4b. Định tuyến Telegram (một chat duy nhất, 08-08)

Nguyên tắc CEO: *"giao việc cho bot nào thì bot đó nhận mọi thông tin"*. Mọi tin
CEO-facing đi **coordinator-first** (bot của chat giao việc), admin chỉ là fallback:
`operator_notify` (clarify, watcher, thông báo chung), digest 🏁 của milestone-mirror,
và tin "✅ HOÀN THÀNH" fast-path kèm link workroom
(`{MPM_WEB_BASE_URL|http://localhost:8765}/office?room=<task>` —
`dashboard_links.py`). Chống đúp cùng-chat: fast-path gửi trước rồi đóng dấu
`delivered_direct` vào mốc done (key này phải nằm trong whitelist của
`office_event_projection` — tường lửa PII từng nuốt cờ lặng lẽ), mirror bỏ qua mốc đã
đóng dấu. Tiêu đề task không lặp trong một tin.

## 5. Lưu trữ

| File (.data/) | Nội dung |
|---|---|
| `team_tasks.sqlite3` | Task đội + steps + lease state + `delivery_status` (v67) + `route_json` (v78, chỉ số định tuyến — NULL trên task trước v78) |
| `office_room.sqlite3` | Office events (feed realtime, projected PII-safe) |
| `captures.sqlite3` | Team-step telemetry: attempt_id, task_id, step_id, agent_id, engine, cost_usd, tokens (WAL, INTERNAL-only) |
| `approvals.db` | Hàng đợi Lớp B + `approval_rules` table (v67 learned rules per-agent) |
| `dedup.db` | Chống gửi trùng |
| `checkpoints.db` | LangGraph checkpoint (report graphs; team graph KHÔNG checkpoint) |
| `memory_store.sqlite3` | Trí nhớ bền dùng chung cross-agent (v66; retention 90 ngày; v68 reflection lesson ở `(coordinator_id, "memory")` + cooldown ở `(coordinator_id, "reflected")`) |
| `agents/<id>/reminders.db` | Nhắc hẹn giờ per-agent (v65; sweep mỗi phút) |
| `artifacts/team-tasks/<id>/step-<n>.json` | Kết quả bàn giao từng bước (artifact viewer đọc) |

User-data (gitignored): `.data/`, `registry.yaml`, `company.yaml`, `profiles/<id>/`
(gồm `vault/` + `skills/` per-agent, v19), `company-docs/`.

## 6. Bất biến an toàn (đừng phá khi refactor)

Xem [codebase-summary.md](codebase-summary.md) "THE INVARIANT" + HANDOVER §5. Tóm tắt:
gateway-only egress · Lớp A/B · PII firewall write-time · hash-bind confirm · process
isolation · registry user-data.

## 7. Kiểm thử full-flow (v79)

Nguyên pipeline intake → decompose → work → review → aggregate chạy được TRONG MỘT tiến
trình test với LLM kịch-bản-hoá — 8 kịch bản người-dùng-thật (clarify, autopilot,
sprint...), mutation-verified. Hướng dẫn vận hành + cách thêm kịch bản:
[fullflow-testing-guide](fullflow-testing-guide.md).
