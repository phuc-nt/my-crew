# Project Roadmap — my-crew

> Lộ trình + trạng thái (as-built v95, đã ship tới 0.15.0 — arc v86–v95). Cập nhật khi mốc đổi. Chi tiết mỗi vòng: `docs/journals/`.
> Cập nhật: 2026-08-30.

## Trạng thái tổng

**Production-usable, single-user autonomy-first. Đã ship tới v0.15.0 (PyPI, 2026-08-30 — arc
v86–v95).** 4212 BE + 417 FE + 44 e2e test + 33 live fullflow (opt-in), ruff/tsc sạch.
Mọi vòng E2E trên browser + LLM + ticker thật (live daemon, kill-9 resume, fan-out,
UAT đối kháng, benchmark sprint-vs-team chấm mù, live e2e opt-in, release gate delta).

**v86–v88 (arc vòng lặp gọn + dọn dẹp + redesign web — 08-18→08-19):**
**v86 thin tool loop** (`runtime_backends/thin_tool_loop.py`): vòng tool-calling tự chủ
trên OpenAI SDK thay `langchain.agents.create_agent` ở tier react, cờ `loop_engine:
thin|langchain` giữ A/B; bench live 3+3 interleaved — pass-rate hòa 3/3, prompt token rẻ
3.5×, wall nhanh 1.6×, chỉ thin có cost exact; stress 5 brief khó × 2 run PASS 10/10 và
tìm ra bug thật (OpenRouter 200 + body JSON hỏng xuyên thủng retry → thêm vào `_RETRYABLE`)
· **v87 dọn sau release**: CI thoát Node 20 (6 action, 3 workflow), `httpx2` vào dev group
hết warning suite, `chart.js` rời entry qua lazy chunk (777→504 kB), xóa tag arc-số cũ
· **v88 redesign toàn bộ web FE**: ~20 route phẳng → **5 hub** (`/chat` HOME, `/office`,
`/work`, `/team`, `/system`), mỗi màn cũ thành tab có URL riêng (`?tab=`); chat làm màn nhà
theo lối app chat nhưng khai thác BE (giao việc + duyệt + artifact ngay trong luồng); tầng
dữ liệu sang TanStack Query với `query-keys.ts` là factory key duy nhất cho cầu
SSE→invalidate; code theo `features/<hub>/`; 21 redirect giữ mọi URL cũ sống; entry
540→476 kB. Đóng arc: audit cold-start (một máy trắng) tìm ra nút "Bật lại" chỉ lật cổng
registry mà bỏ cổng profile — template tạo agent `enabled: false` cố ý nên tuyển người đầu
tiên không thể bật bằng UI; và chặn giao việc do rào escalation viết bằng từ vựng backend,
không chỉ ra màn nào sửa được. Cả hai sửa, giữ nguyên rào an toàn.

**v92 (fast/crew lane routing v2 — 08-25→08-26, trong v0.14.0):** **Nâng cấp 2-lane routing v77**
giữ lại mọi tiến bộ, lấp 4 gap: (1) **routing steering** — sprint dead-end → lật sang team giữ bối cảnh
(`run_upgrade_to_team`, nháp dở đi theo làm tham khảo); (2) **effort tier** (`low|medium|high` lưu `route_json`)
— chỉ `low` đổi hành vi: model role `sprint_low` + cắt budget search + tối đa 1 revise; `medium` hành vi
cũ (fail-open); (3) **lane stats** — đo 3 miss-rate (`dead_end`/`downgrade`/`upgrade`) trên `routed_tasks`
(không tất cả), thêm `cost_usd`/`wall_clock_seconds` per-lane; (4) **benchmark v2** — 4 mode:
`routing` (0 call, offline so router), `release` (0 call, so chi phí), `tasks` (read live store),
`judge` (blind A/B chất lượng). **Live fullflow suite** (`tests/fullflow_live/`, 18 case) end-to-end vs
model thật **opt-in** (`pyproject.toml::addopts = ["-m", "not live"]`), assert trên `route_json` + DAG
shape ổn định qua model nondeterminism. Cũng tìm ra 3 lỗi thực tế (tiền tố ép chế độ bị drop,
`_parse_json_object` nhặt thêm sau dấu `}`, đếm dãy inline nhận đánh số DANH TỪ). Cổng: 3991 BE passed,
1 skipped, 18 live deselected.

**v93 (graph-engineering crew lane — 08-30, trong v0.14.0):** decompose theo triết lý
graph-engineering "mỗi bước phải có ranh giới thật": (1) **nhãn ranh giới** — `TeamStepPlan.boundary`
(5 loại `BOUNDARY_KINDS`), observational-only, phân bố ghi `route_json.signals.boundary_counts`;
(2) **fold cấu trúc** — `fold_unjustified_steps` chạy sau fanout, gộp bước đúng-1-dep + cùng người
+ cùng quyền (bỏ qua nhãn khai — chống model bịa nhãn giữ bước), fail-open; (3) **tiền kiểm định
lượng** — `deterministic_step_check` đo phủ thực thể + đếm mục bằng CODE trước LLM checker, gap
code-found fail ngay confidence 1.0, sprint tắt (`deterministic_precheck=False`, đã có
`coverage_gaps` riêng). **Bench vòng 6 (lanes14, 11 cặp judged)**: gate trao quyền
`material_transform` **TRƯỢT** (team judge-win 3/7 < 2/3; no-salvage completion 64% < 80%; chỉ cost
1.19× đậu) → routing giữ nguyên, signal tiếp tục đo-không-quyết. Salvage-draft hạ nguồn **verified
live** (nợ vòng 5): 2 bước chết → nháp salvage → bước cuối giao có dán nhãn 'chưa qua soát'. Fold
kéo team-lane về 1–3 bước, cost sát sprint (1.19× vs 3–4× các vòng trước). Cổng: 4088 BE passed, ruff sạch.

**v94 (crew reliability — guidance đóng băng, 08-30, trong v0.14.0):** truy gốc bước chết
vòng 6 bằng taxonomy trên transcript thật → nguyên nhân top: **guidance điều phối đóng băng cả
attempt** (perceive chạy 1 lần/attempt, vòng rework 2 bị nhắc sửa đúng thứ vòng 1 vừa sửa) —
fix: chỉ vòng rework đầu tiêu thụ guidance, các vòng sau strip (giữ dòng wake-context của
rework soát chéo; anchor `rfind` chống header bị nội dung nhại). **Bench vòng 7 (lanes15,
re-run 4 case chết)**: gate khóa trước ≥2/4 sống sạch → **ĐẬU 3/4** (baseline 0/4; drop 2→0,
salvage 2→0, failed 3→1; cost team −60% — hết đốt vòng rework vô ích). Judge mù: 2 case lật
0-3→3-0 sau khi sạch. Giả thuyết chữ ký `multi_deliverable` **HỦY sau khi đo** (0 từ vựng tách
được nhóm thắng/thua; biến dự báo judge-win là run có sạch hay không). Kèm: phát hiện + sửa bug
bộ lọc judge (chấm cả bản giao hỏng — nhiễm verdict vòng 6, tally 7-4 cần chú thích); kiểm
chứng routing thật trên 11 brief: đúng 7/11 = luôn-chọn-sprint, 2 tín hiệu hiện có giá trị
ròng 0 (khớp-chuỗi sai nghĩa). Routing 0 diff. Cổng: 4091 BE passed, ruff sạch.
Việc vòng sau: xét lại tín hiệu `'trong tuần'`→nhiều-giai-đoạn (bắt nhầm hạn chót); rõ hóa
phân rã bước review-and-finalize (tách "chốt bản cuối" khỏi "phán quyết" — case meeting_notes
stalled vì mơ hồ này); bộ đề ≥30 case cho routing + đo lại tương quan sạch→thắng phi-cơ-học.

**v95 (zalo business fleet P2/P3/P4/P6 — 08-30, ship 0.15.0):** 4 phase của plan
`260830-1311-zalo-business-fleet` (P1 kênh Zalo + P5 digital-assistant khách **hoãn**, chờ OA
verified). (1) **Control-plane API** — `delegate_work` + status hợp nhất + fleet overview cho
caller ngoài SPA, confirm bắt buộc mang plan hash hiện hành (hash cũ/thiếu → từ chối, không
hành động trên kế hoạch caller chưa thấy); (2) **escalation→manager agent** — việc vượt thẩm
quyền mint task 1 bước cho manager thay vì chết tại chỗ, 3 chốt chống bão: task escalate không
escalate lại, cap ngày theo nguồn, manager không giao được → báo thẳng chủ; `company.yaml`
thêm `manager_id`/`escalation_daily_cap` (chưa có UI ghi → mọi save path phải giữ giá trị đặt
tay); (3) **credential store mã hoá** — `credentials.enc` Fernet per-account thay token
plaintext, master key do store tự ghi, bộ lọc egress học cả hai dạng Fernet; (4) **worker
packs accounting + Meta Ads** (đọc-insight), agent có media dir bền không bị quét dọn.
Hai lỗi hạng production **chỉ lộ khi chạy model thật**: hỏi giá/tỷ giá được trả lời từ trí nhớ
cũ thay vì cử người tra; việc đụng bên ngoài (gửi mail, clone repo chạy test) trả về danh sách
lệnh thay vì thành việc — nặng nhất trên catalog admin (trượt 4/5, personal 1/5: catalog lớn
hơn cho model thêm cớ kết luận "không lệnh nào khớp"). Sửa ở prompt + mô tả lệnh, không nới
assert; sau sửa 42/42 trên ma trận phân loại. Thêm `dead_end` không còn đè `source` của
route (phá nguồn mà escalation cần). **Live fullflow 33 case** vs model thật ($0.19, 19 phút,
không case nào quá 1/4 trần chi phí). Cổng: 4212 BE passed / 69 skipped, 417 FE, 44 e2e,
ruff sạch; release + routing bench **0 delta** so v0.14.0.
Việc vòng sau: P1 (Zalo OA) + P5; `escalation_daily_cap` per-source hay global; nối
`ads_credential` vào config builder.

**v80–v85 (arc quan sát bước + toàn vẹn nguồn — 08-16→08-18, trong v0.14.0):** **v80 step
observability**: transcript JSONL per-attempt trong jail agent (`runtime/step_recorder.py`),
work-order + replay (`mpm step-replay`), evidence quá trình vào prompt review, reflection
đọc hành vi tool (threat model chỉ tên + số đếm) · **v81 sprint lookup v2 + release bench**
(prose entity, xoay góc truy vấn, bench 4 trục so phiên bản) · **v82 web redesign** (lazy
data layer, sprint surfaces, SSE cold-tail replay) · **v83 benchmark sống vs 0.10.0** (no-subagent,
blind judge; phát hiện judge v1 thưởng hình thức) · **v84 sprint mở trang chính thức**
(`official_page_pick/fetch` giữa prefetch và draft, registrable-domain match chống lookalike,
`_strip_control_markers` chặn marker giả từ thân trang, `_pricing_affinity` chọn đúng TRANG
không chỉ đúng NHÀ) · **v85 toàn vẹn nguồn**: truy gốc "vì sao review cho qua bảng giá bịa"
= luật chống bịa có điều kiện mà tiền đề vĩnh viễn FALSE ở bước sprint; `content_head` vào
event prefetch/fetch để reviewer thấy NỘI DUNG trang; `QUY TẮC NHÃN NGUỒN` (gọi "chính thức"
số từ báo/đại lý = sai nhãn; ô trống trung thực > ô đầy không truy được); blind judge v2 đếm
verified/contradicted theo từng số — phán quyết v84 ĐẢO; xác nhận sống 3 run: 2 bug đứt ống
bằng chứng (transcript nằm jail agent nhưng review glob root chung; nội dung trang bị cắt
theo hằng tool-result) tìm và sửa qua từng run, run cuối reviewer đối chiếu được giá thật
trong prompt. Firecrawl render JS trên SPA xác nhận (đảo giả định v84).

**v76–v79 (arc sprint + phễu định tuyến + release gate — 08-09→08-15, 0.10.0):**
**v76 đo lường + guardrail**: audit hash-chain (`mpm agent audit <id> verify`), fail-mode
contract + break-glass env-only (`MYCREW_GATEWAY_FAIL_OPEN=1` — không bao giờ nới Lớp A),
metrics honest-data (Wilson CI, `team_metrics`), autonomy band per-agent
trusted/normal/supervised CHỈ đụng cổng review + loop khép kín bất đối xứng (siết tự
động, nới cần người, cooldown 3 ngày) · **v77 sprint mode**: đề một-người = team task suy
biến 1 bước `sprint`, code điều nhịp (`runtime/sprint_runner.py`: prefetch → draft →
coverage check → revise ≤2 vòng, ≤8 truy vấn); tiền tố `sprint:`/`team:` override, 4 ca
không ép được sprint (ghi-ra-ngoài/shell/nhiều người/dài hơi); benchmark nhanh 3.6–7×,
rẻ 4.1×, chấm mù 28 vs 8 · **v78 phễu định tuyến 6 lớp** (`agent/sprint_intake.py`): lật
mặc định sang sprint, tín hiệu CẤU TRÚC đẩy team (>1200 ký tự / >10 thực thể / ≥3 đầu
việc); `downgrade_to_sprint` sau decompose (0 gọi model thêm); dead-end tự lật team giữ
quyết định gốc; cột `route_json` log mode/source/reason/signals mọi nhánh; UAT 18 task
live 13/13 ca định tuyến PASS, đủ 6 lớp có ca sống; sau nghiệm thu: **sprint LUÔN mint
1 review mọi band** (đóng đường zero-eyes) + **trần review tầng task** (2× bước nội dung,
sàn 5, chạm trần → stall + escalate); cộng dồn 4/5 cặp benchmark sprint thắng ·
**v79 release gate + hardening**: model 3 tầng fleet → per-agent → per-role (`role_models`),
fleet mặc định `deepseek/deepseek-v4-pro-0813`; **phanh in-flight cho trần chi phí** (chạm trần
halt bước ĐANG chạy — trả nợ "cancel không phải phanh"); harness fullflow in-process
(8 kịch bản người-dùng-thật, mutation-verified, `docs/fullflow-testing-guide.md`); chuỗi
fix chất lượng giao việc (terminal giao nguyên văn, review truy số về đầu vào, hết flood
Telegram, rework thừa kế quyền web); cổng release: delta-UAT sống 4/4 hành vi, 2 phát
hiện cosmetic sửa trước khi tag (sprint tool-less bỏ máy search; tiêu chí độ tươi không
loại số cũ khi không có nguồn mới hơn).

**v71–v74 (arc tốc độ + phán đoán — 08-06→08-09):** v71 personal crew quick-build · v72 tick
spawn-then-drain · v73 grader neo ngày + retry-first coercion + Telegram coordinator-first ·
**v74 tốc độ đa-agent** (tier theo bước `needs_web` → bước không-tool chạy native; dispatch hướng
sự kiện `tick.poke` 4 nguồn, gap 253s→0-8s; fan-out ≥4 thực thể ép code fail-open; salvage
transcript khi cạn loop; dead-step reset đổi người web-capable; concurrency 3). Số chốt benchmark:
đề khảo sát 5-6 thực thể 40'→11-16', $0.02-0.05/task, honesty chain giữ vững qua 7 vòng.

**v69 (bề mặt chat cho approval — 0.8.0):** Lớp B queue → **DM Telegram ngay khi enqueue**
(chỉ trường định danh, không lộ subject/body) · **duyệt/từ chối ngay trong chat** (bề mặt
thứ ba trên cùng đường gateway, admin-only, binding `(agent_id, approval_id)` chốt ở
preview) · **rule always/deny từ chat** (mô tả bằng lời từ binding thật, action không tả
nổi thì từ chối tạo rule) · reject thành **compare-and-set cả 3 bề mặt** + ApprovalStore
WAL · heartbeat digest **nêu tên mọi approval treo** (miễn trừ suppression) · `xem bài
học` đọc lesson reflection (tag `source` phân biệt với fact chat) · số lần hồi sinh trong
kanban. UAT thật trên fleet 10 agent + Telegram thật.

**v70 (personal assistant pong — 0.8.0+, in-progress):** Tác nhân riêng `pong` bổ sung thư ký `secretary` (2 bot Telegram cùng tồn tại, không đụng). Briefing/weekly nhìn vào Goodreads + Google Tasks (đọc công khai RSS + gws CLI). **PersonalToolProvider kind-aware**: mọi kind lấy bối cảnh ngày (calendar_next_24h, unread_email, pending_tasks, reading_now); riêng `weekly-review` trả thêm dải tuần (calendar_next_7d, tasks_completed_7d, goodreads_activity_7d, lessons). **Profile-only `goodreads_user_id`**, cố ý KHÔNG env fallback: kệ sách thuộc về một người còn env là fleet-wide, đặt biến là `secretary` âm thầm đọc kệ người khác. Goodreads tool: `currently_reading(user_id)` + `recent_activity(days)` lấy RSS công khai, stdlib-only, degrade-soft khi lỗi. Gws thêm `tasks_pending()` (briefing) + `tasks_completed(days=7)` (weekly) qua allowlist argv cố định, cả hai tự khai trần trang vì lọc `completed` chạy sau khi API cắt trang. Pong chạy schedule `0 7 * * *` (briefing) + `0 8 * * 0` (weekly). Phạm vi: mở rộng snapshot source của personal-pack, giữ nguyên 5 đánh đổi v30 autonomy-first + Lớp A + PII firewall.

**v57–v68 (arc thư ký — 0.7.0+):** **v57–v60 thư ký cá nhân** (pack `personal`: chat DM,
briefing sáng/tuần, Gmail/Calendar, gửi email, sửa/xoá lịch, multi-command) · **v61 chat
= cổng điều phối đội** (giao/chỉnh/huỷ việc + kanban qua Telegram, catalog scope domain) ·
**v62 English identifiers** · **v63 autopilot** (AI quyết cuối: tự xác nhận / tự gỡ kẹt /
tự duyệt Lớp B — Lớp A + cost cap bất biến) + review theo rủi ro + gỡ-kẹt 1 chạm ·
**v64 UAT hardening** (chống bịa sau bước bị bỏ) · **v65 nhắc đúng-giờ + scheduler
round-robin công bằng** · **v66 cross-agent memory SQLite** (fact sống qua restart, đội
đọc chéo, thư ký read-only) · **v67 learned Lớp B rules + task lifecycle** (CEO duyệt/chặn + `--always`/`--deny` → rule, guarded-mode-only; delivery_status tách execution_status; escalation contract P1) · **v68 heartbeat + reflection** (secretary heartbeat opt-in `heartbeat.every` config, im lặng đã yên, defer khi bận; task reflection chưng cất lesson khi terminal; 2692 BE test). Retro đầy đủ: `plans/reports/retro-260804-1721-*`.

**v51–v55 (productize + office cockpit):** **v51 productize** (PyPI package: console script
`my-crew`, serve supervisor, Docker, CI secret-free + OIDC release, MY_CREW_HOME) ·
**v52 office dual-lens** (👁/🔬 lens, captures explorer, FTS5 search, failure/review visuals 3D) ·
**v53 UI kỷ luật + VN/EN** (6 primitive, 1 cost/date format, dictionary typed-keys) ·
**v54 office cockpit** (rail duyệt/clarify tại chỗ, feed ra-ngoài từ gateway, review tray
per-criterion, ✋/×N/ghost 3D) · **v55 cockpit viewport shell** (1 màn không scroll, composer
command bar trên đỉnh, gộp watch-run ×N + lọc [●⚠✓] + search + tab Kết quả).

**v40–v50 (deep_agent + runtime-tier + governance + onboarding + UI catch-up):** v40–v42 deep_agent hardening ·
v43 deep_team in-sandbox · v44 benchmark-hardening · v45 tier-0 routing (no-shell→create_agent) ·
**v46 audit actor** (attribution end-to-end) · **v47 Docker UX** (health probe, prepull) ·
**v48 MCP pool** (team-step reuse) · **v49 quickstart** (OpenRouter-only first report) ·
**v50 UI catch-up** (surface v43–v46 backend: actor column, tier badge, per-task cost, deep_team toggle).

## Đã hoàn thành (gọn — chi tiết ở journals/plans)

| Mốc | Nội dung |
|---|---|
| **Nền tảng (v1)** | Single-agent PM: 4 báo cáo (daily/weekly/okr/resource) + Action Gateway (Lớp A/B) + đa-audience. |
| **Platform (v2, M1-M2)** | Multi-agent core (registry + worker + isolated store) · LangGraph interrupt/SSE · Web SPA (React) · Postgres+Store opt-in. |
| **Extensibility (M3-M6)** | Skills · cross-agent memory · domain-packs (pm/hr) · MCP suite · company docs. |
| **Trust & ops (v8, v10)** | Trust ladder (auto-approve Lớp B) · multi-project rollup · theme/dual-mode/installer hardening. |
| **Reporting (D4)** | Xuất .xlsx đính email (Lớp B, internal-only). |
| **Agent Office (v12)** | Team-task: coordinator ticker + store + lease · giao việc đội · office room + màn 3D. |
| **Team self-op (v13-v14)** | Soát chéo tự chèn · consult đồng nghiệp · song song cap 2 · full replan · tự cứu bước kẹt · 3D "sống". |
| **PIC & office UX (v15-v17)** | Giao việc @PIC/@all · auto-confirm · màn Văn phòng hợp nhất → workrooms → command-center 3 cột · artifact viewer · coordinator health banner. |
| **Registry user-data (v18)** | registry.yaml thành user-data (hết mất đội) · recovery UI · scheduler seed-at-discovery · 3D theme-aware. |
| **MCP suite + adapter (v11)** | 3 MCP server (Jira/Confluence/Slack) + session-pool cache (2ms warm) + npm publish 4.2.0/1.5.0/1.3.0. |
| **Agent-harness v1 (v19)** | Memory provider seam (static; kioku hoãn v19.5) · workspace protocol v2 (vault/ + skills/ per-agent) · per-agent skill có guard · capability block internal-only. |
| **AgentRuntime + community (v20)** | AgentRuntime seam (Native/ToolCalling/DeepAgent) giữ deliver→gateway · positive read-allowlist + classify shim (E2E LLM thật) · 3 ổ cắm: skill agentskills.io, pack-MCP spawn gate, pack template + PACK-AUTHORING. |
| **Runtime tiers + DeepAgent (v20.5)** | Multi-tier guardrail (native < tool-calling < deep) · DeepAgent Docker sandbox (fail-closed, token-free, teardown sạch) · team-step egress qua gateway. |
| **Capture telemetry + session log (v26)** | Bảng captures riêng · unify cost 3 engine · side-channel collector · telemetry per-step. |
| **Deep-agent harden (v27)** | Sanitize-at-source 5 kênh · network AND-gate fail-closed · container hardening · reaper orphan cleanup. |
| **Runtime consolidation (v28)** | DRY loop core (record_loop_result + invoke_capped) · migrate tools-tier to langchain.agents.create_agent. |
| **Autonomy-first trust model (v30)** | Lớp B split: autonomous (chạy ngay, audit rationale "trust_mode=autonomous", mặc định) vs guarded (queue duyệt, opt-in `trust_mode: guarded`). Chat flatten. Fleet-flip. No daily-cap in autonomous. |
| **Agent-tools capability wave (v31)** | Hậu kiểm fleet-wide (2 surface: web + ops-chat) · 4 native action types (schedule_update, team_task_create/move, gws_write) · wake-gate hồi sinh (perceive-only, no-LLM khi không đổi, CEO alert on fail/stale) · OpenAlex academic search tool. |
| **Staff templates + crew, office-3D refactor, UI/UX audit (v32)** | One-click template create (agent TẮT → token → bật ở trang Đội) + crew bootstrap từ `profiles/templates/crew.yaml` (per-member independent, skip-existing, coordinator auto-wire) · office-3D visual overhaul (flat low-poly solid pastel theme per light/dark, state hue on monitor, desk click→room/page, hover tooltip, panel 38vh) · error boundary + 12s watchdog cho lazy-office chunk · chat /commands listing "Trợ lý làm được gì?" · AgentPage profile-error recovery · office activity filter note. |
| **Connections + output hub + clarify + search (v33)** | Màn Kết nối = UI của .env (catalog presence-only) · hub Kết quả cross-task kanban · clarify buttons (CEO answer mid-execution) · history FTS5 search. |
| **Autonomy core: checkpointer + interrupt + follow-up (v34)** | Checkpointer resume after crash (attempt adopt tiến độ) · interrupt() pause-ask-resume · proactive follow-up sweep (SQL 8h cooldown) · per-criterion review scoring · fan-out parallelization (1 step → N parallel subtasks + gather). Live E2E verified. |
| **Tool-error resilience + memory consolidation (v35)** | `tool_error_guard` bọc mọi read-tool (Jira/Confluence/web) — lỗi thân tool trả "⚠️ tool lỗi" cho LLM thay vì làm nổ cả step · nightly (03:00) memory consolidation rút gọn `MEMORY.md` khi vượt ngưỡng, archive bản gốc trước khi ghi. |
| **Storage hygiene + template hybrid (v36)** | Template skill nạp LIVE lúc chạy (không copy-once) → sửa skill template lan mọi agent cùng vai ngay · template config version-pin: badge "⬆ bản mới vN" ở trang Đội, review dialog áp/giữ theo trường tự-chỉnh, backup `profile.yaml.bak-<ts>` trước khi ghi · GC nền (captures 180d/office_room 90d/clarify 90d đã trả lời/dedup 7d) + daily integrity audit. 2149 BE + 200 FE tests. |
| **UI design-system sync (v37)** | Văn phòng 3 cột canh cùng baseline · phân cấp size rõ ở cột Kết quả · input/button đồng nhất kích cỡ toàn app. Thuần CSS, không đổi hành vi. |
| **Harness wave 1: send_message + skill-curator (v38)** | `send_message` facade (slack/telegram/email) qua Action Gateway — agent chủ động gửi, thừa hưởng Lớp A/B + trust_mode + audit; surface chat-ops (không tool LLM ghi trong loop) · skill-curator: đếm skill được chọn + archive skill agent-own quá hạn (không xoá, không đụng template-role). 2177 BE + 200 FE tests. |
| **Google Workspace context + SMTP + Calendar-create (v39)** | Agent bật `gws_context` đọc Gmail/Calendar/Drive (gws CLI, argv CODE-cố-định, internal-only, flag mặc định TẮT) · SMTP vào Connections UI · Calendar-create WRITE qua Gateway (`("calendar","events","insert")` allowlist, delete/acl = Lớp A). 2207 BE + 200 FE tests, live E2E OAuth thật. |
| **UI catch-up: surface v43–v46 backend (v50)** | Audit actor column trên AuditTable (v46 data lộ UI) · tier badge "🔒 N sandbox" kanban card (v45 count steps_needs_shell) · GET `/api/team-tasks/{id}/cost` + TeamTaskCost component lazy-expand "Chi phí" (v26 telemetry bộ lộ) · create-wizard deep_team toggle (v43 feature YAML-only → UI, guarded passthrough). 2344 BE + 201 FE tests, E2E UAT browser 5/5. |
| **Productize → PyPI (v51)** | Package `my-crew` 0.1.0: console script (`quickstart`/`crew init`/`serve`/`doctor`/`upgrade`) · wheel bundle dist FE + shipped resources · MY_CREW_HOME · Docker compose · CI ubuntu+macos + OIDC release pipeline. PyPI 0.3.0 (v53) → 0.4.0 (v54). |
| **Office dual-lens (v52)** | 1 màn Văn phòng phục vụ CEO (thường) + maintainer (🔬): failure/review visuals 3D (desk đỏ + ⚠, floor ring verdict) · health strip · Desk Inspector · Captures explorer · FTS5 history search · read-only observability API. |
| **UI kỷ luật + song ngữ (v53)** | 6 primitive (Button/Card/Badge/Input/EmptyState/PageHeader) · 1 cost/date format · App.css 5 section chống drift · language mode VN/EN dictionary typed-keys (thiếu key EN = lỗi compile). |
| **Office cockpit (v54)** | Rail "Chờ anh/chị" (duyệt + clarify xử lý TẠI office) + "Sắp chạy" (effective schedule) · feed [All\|Steps\|External] bridge từ gateway audit choke-point · review tray per-criterion (criteria_json) · 3D ✋/×N/ghost deep_team. UAT live 6/6, vòng cockpit tự khép. |
| **Cockpit viewport shell (v55)** | Màn Văn phòng = 1 viewport 100dvh (scoped `:has()`, cột scroll riêng, page không bao giờ scroll) · composer command bar trên đỉnh (overlay @mention/preview) · gộp watch-run trùng tiêu đề ×N + lọc [●⚠✓] + search + tab [Phòng việc\|Kết quả] (chấm ● live) · nới shell 1600px. UAT 2 vòng đường thật 26 mục; chấm ● sửa 3 lần mới đúng (suite xanh ≠ chạy được). |

## Việc nên làm tiếp (từ UAT + nợ kỹ thuật)

**Định giá lại 2026-08-19 sau audit cold-start v88** (nguồn:
`plans/260819-1010-mobile-chat-polish-arc-closeout/reports/phase-02-*`):
1. **Rào escalation ép một kênh duy nhất** — giao việc đội bị chặn tới khi có đường
   báo tin về CEO, mà đường duy nhất hiện nay là Telegram. User không dùng Telegram
   thì cold-start vẫn cụt. Rào đúng, cần thêm đường thay thế (SMTP đã có sẵn, hoặc
   chỉ cần báo trong app) chứ không nới rào.
2. **Bảng việc hiện task ở hai cột cùng lúc** khi có preview draft bị bỏ dở — bản nháp
   chưa xác nhận nằm mãi ở "Chờ xác nhận". Cần dọn nháp quá hạn hoặc phân biệt rõ nháp
   với việc thật trên bảng.
3. **Chưa có test cold-start tự động** — audit v88 chạy tay bằng `MY_CREW_HOME` sandbox.
   Ba lỗi tìm được đều là "chỉ hiện trên máy trắng"; suite hiện tại không bao giờ thấy.

**Định giá lại 2026-08-16 sau 0.10.0** (nguồn: journals v76–v79 mục "Mở / sang sau"):
1. **Nợ trusted×external_write (ca sống)** — chưa dựng được: phễu đẩy đề gửi-email sang
   sprint, sprint hardcode `external_write=False`. **Luật thường trực**: chạy lại ca này
   NGAY trước lần cấp opt-in `team_step_egress` đầu tiên, trước khi agent đó nhận việc thật.
2. **Lượt tra cứu thêm cho bước sprint** (trả lời cặp C3 — research nhiều dịch vụ) —
   hướng ĐÃ DUYỆT, chưa triển khai: cần số chi phí trước, YAGNI về hình thức cấp.
3. **Auto-tune ngưỡng phễu** — cần ≥20 dòng `route_json` có outcome mới chỉnh ngưỡng
   (1200 ký tự / 10 thực thể / 3 đầu việc) từ dữ liệu thật; UAT tới nay 0 ca route sai.
4. **Bằng chứng sống `task_review_budget_exhausted`** — mới có unit test; lần đầu
   escalation này bắn tự nhiên → ghi task_id vào journal.
5. Band chưa hiện trên kanban card (mới có audit/Telegram/`team_metrics`); theo dõi
   demote `researcher` — nếu done-rate hồi phục, loop tự gỡ.
6. Ed25519 ký audit chain + checkpoint ngoài data-dir — chỉ khi có nhu cầu multi-machine.

**Định giá lại 2026-08-04 sau 0.7.0** (retro `plans/reports/retro-260804-1721-*`):
1. **Chất lượng NỘI DUNG chuỗi handoff/extractor** — điểm yếu số 1 (drift kiểu "Nghị
   định 206", fact vụn theo dòng): cơ chế tròn, óc viết chưa sắc — cần vòng riêng.
2. **Go-live pilot sales-pm** — checklist + drill sẵn (v58), chờ CEO bấm.
3. ~~**Soak autopilot + review policy mới**~~ — **đóng v76–v78**: đo lường thành hệ
   thường trực (`agent_metrics` + Wilson CI + band loop khép kín); review policy được
   siết thêm bằng band per-agent + trần review tầng task, UAT sống nhiều vòng.
4. Postgres deferred có chủ đích (SQLite chung đủ cho single-user).

Bên dưới là danh sách tích lũy cũ hơn (ưu tiên giảm dần). Nguồn:
`plans/260711-0711-.../reports/uat-*findings*.md` + HANDOVER §8. Định giá 2026-08-01 sau
0.5.0: `plans/reports/260801-1940-roadmap-reassessment-post-0.5.0.md` — hướng "Nền vững"
(Playwright smoke → dọn dẹp quick wins → attempt_id) ĐÃ XONG ở v56.

### Go-live có kiểm soát (checklist + drill XONG v58 — chờ CEO quyết pilot)
Xem `docs/go-live-checklist.md` (kiểm kê fleet thật + lộ trình 2 nấc + drill kill-switch
đã chạy, bug env-bị-profile-đè đã vá). Còn lại là quyết định vận hành:
- [ ] **Tắt DRY_RUN, chạy thật**: `trust_mode: guarded` (mọi Lớp B chờ duyệt ở hàng
  duyệt — hub Công việc, badge trên nav) → nâng dần autonomous cho hành động ổn định. Đây là giá trị cốt lõi chưa
  thu hoạch — trust-ladder (v30) + rail (v54) build sẵn để phục vụ chính bước này.
  Trước khi bật: brainstorm checklist riêng (soi audit hằng ngày, budget cap, kill-switch drill).

### Agent-harness (chương trình 3 vòng — brainstorm 260711)
- [x] **v19**: memory seam + static + workspace protocol (vault/skills per-agent) + capability block.
- [x] **v20**: AgentRuntime seam (Native/ToolCalling/DeepAgent) + 3 ổ cắm community. Red-team 4
  reviewer (5 Critical) → fix thiết kế giữ moat. DeepAgent experimental (deepagents optional);
  researcher-pack = template skeleton (team-step đã phục vụ researcher).
- [x] **v20.5**: runtime-tiers — team-step egress qua gateway (Phase 0, nối external_write) +
  guardrail phân tầng (runtime_loop_limit per-runtime) + DeepAgent cháy thật (Docker self-hosted
  sandbox, fail-closed allowlist, PII gate) + wizard chọn runtime theo role. Red-team 3 reviewer
  (6 Critical, đọc deepagents wheel) → provider đổi sang Docker (không dịch vụ ngoài). **DeepAgent
  tự chủ trong Docker verify THẬT** (LLM tự gọi docker exec, container token-free, teardown sạch).
- [x] **v19.5 (kioku adapter)** — **XONG v58 P7 (2026-08-03)**, đủ 7 điều kiện dưới (chi
  tiết docs/journals/260803-v58-roadmap-sweep.md):
  cắm my-kioku sau khi giải 7 điều kiện red-team — dist
  (`bun link`+`MY_KIOKU_BIN`, BỎ `bun x`); recall `<query>` (không `--digest`); wrap digest
  `format_internal_content`; env allowlist subprocess; flock per-vault + stagger reflect;
  health probe thật; pin "zero network I/O". Xem `plans/260711-1543-v19-.../plan.md` §"Giữ cho v19.5".
- [x] ~~**v20**: channel binding account→agent (mỗi agent 1 bot Telegram, OpenClaw-style)~~ —
  **đóng 2026-08-03**: đã là hiện thực từ v6 M13 (bot per-agent + allowlist 2 chiều); v57 còn
  thêm listener long-poll trả lời tức thì. Không còn nội dung để làm.
- [x] ~~**v21**: 2-mode UI (CEO đơn giản / Maintainer config+monitoring)~~ — **đóng
  2026-08-01**: v52 dual-lens (👁/🔬 + captures explorer + health strip) đã đáp ứng đủ
  ý tưởng gốc; phần còn lại không đáng một hạng mục riêng.

### Tài liệu
- [x] Dựng bộ doc chuẩn v18 (overview-pdr, system-architecture, deployment-guide, roadmap).
- [x] Archive doc cũ (v1/v2/interview) + gộp UAT.
- [ ] Đồng bộ header `codebase-summary.md` (ghi v13 → v18) + gộp phần lịch sử dài.

### v57 — Thư ký riêng CEO trên Telegram (2026-08-03, ✅ 5/5 phase)

Domain pack thứ 5 `personal` (tham chiếu Pong/openclaw; "full-ga trong khung": autonomous +
dry_run off, GIỮ Lớp A): chat DM tức thì (listener long-poll, tick làm fallback) · briefing
7:00 + weekly CN 8:00 (kind pack tự sở hữu) · đọc Gmail/Calendar qua `gws` · lệnh `tao_lich`
(gws_write) · chat có trí nhớ (daily notes 7 ngày + mirror MEMORY.md, opt-in
`memory.daily_notes`). `plans/260803-1816-personal-secretary-agent/` +
`docs/journals/260803-v57-personal-secretary.md`. Còn mở từ v57:

- [x] **P4 web-search cho thư ký (xong 2026-08-03, 5/5 phase)**: không mua key — Brave dùng
  lại từ openclaw, Firecrawl self-host localhost:3002; thêm nhịp chat 2-pass
  (`WEB_SEARCH:` marker) vì M11 không có tool-loop.
- [x] ~~Thư ký biết roster crew~~ — xong v58 (yaml-peek, UAT gợi ý đúng @researcher).
- [x] ~~Gửi email từ chat~~ — xong v58, hoàn tất 2026-08-04: đổi kênh sang `gws gmail +send`
  (OAuth sẵn, bỏ hẳn SMTP; vetted-types rút về 5). UAT thật: mail nằm trong Gmail.
- [x] ~~`memory.search` trên notes >7 ngày~~ — giải bằng kioku v58 (recall ngữ nghĩa toàn vault).
- [x] **v60 (2026-08-04): cổng điều phối + sửa/xoá lịch**: thư ký giao việc cho crew
  (`giao_viec`/`chuyen_the` — reuse team_task types + handler actor-bound, card planning
  cho coordinator lo tiếp) · `doi_lich`/`xoa_lich` (resolver tiêu đề→eventId, mơ hồ hỏi
  lại + arg `luc` phân biệt trùng tên; xoá qua carve-out Lớp A cấu trúc
  `_is_calendar_event_delete` — CHỈ đúng shape 1 event calendar primary, test pin đủ
  biến thể xấu). `plans/260804-0840-secretary-dispatch-calendar-edit/`.
- [x] **v61 (2026-08-04): thư ký = điều phối viên (ops orchestration)**: mở tầng
  ops-chat cho domain personal với catalog 12 lệnh ĐIỀU PHỐI (`catalog_for_domain` —
  assign_team_task DAG nhiều agent + confirm, adjust/list/cancel, việc định kỳ,
  send_message, 4 readonly; KHÔNG fleet-admin). Backend 100% English (id lệnh
  create/update/delete_event, send_email, arg `at`, slot `request`); gỡ cặp M12
  giao_viec/chuyen_the (một bề mặt giao việc duy nhất).
  `plans/260804-1004-secretary-orchestration-gateway/`.
- [x] ~~**Cross-agent memory**~~ — **xong v66 (2026-08-04, thiết kế + ship cùng ngày)**:
  backend `store: sqlite` default (1 file chung `.data/memory_store.sqlite3`, WAL);
  nhóm `project: company` 8 agent; `memory_share: read_only` cho secretary (đọc đội,
  không chia ngược đời tư CEO); sibling block wrap `format_internal_content`; retention
  90d. UAT sống: fact persist thật, đọc chéo đúng luật. Còn mở: chất lượng extractor
  (tách theo dòng → fact vụn) · Postgres chỉ khi đo được tranh chấp ghi thật.
- [x] ~~**Nhắc việc theo giờ**~~ — **xong v65 (2026-08-04)**: lệnh `set_reminder`/
  `cancel_reminder` (M12 personal, native type `reminder_create`/`reminder_cancel`
  actor-bound + nhánh Lớp A riêng), store per-agent `reminders.db`, pseudo-kind
  `reminder-sweep` mỗi phút CHỈ mọc khi còn nhắc pending (no-LLM, gửi qua
  telegram_send có dedup), snapshot thêm `upcoming_reminders`. Kèm fix ghép tầng:
  ops-unsupported của thư ký giờ RƠI XUYÊN xuống catalog M12 thay vì trả listing chặn
  đường (admin giữ nguyên).
- [x] ~~**Cân chỉnh review theo cỡ việc (từ UAT v61)**~~ — **đóng v63 (2026-08-04)**:
  waiver code-side (task ≤3 bước VÀ không bước `external_write` → bỏ peer review, chỉ
  self-check; ngưỡng "kết hợp cả hai" do CEO chốt) + verdict `passed_with_notes` (đạt
  kèm góp ý — không mint rework, góp ý vào aggregate). `external_write` vào plan_hash
  CONDITIONAL như `needs_shell` — DAG cũ hash y nguyên.
- [x] **Gỡ-stall một chạm (v63)**: 3 lệnh ops `accept_stalled_result` / `retry_stalled_step`
  / `drop_stalled_step` + escalate kèm evidence pack (tóm tắt verdict trượt, wrapped).
- [x] **v64 — vá 4 finding UAT vòng 3 (2026-08-04)**: honest-drop (cấm bịa số liệu sau
  bước bị bỏ — 3 lớp: placeholder/system-prompt/aggregate) · shell guard plan-time
  (needs_shell không ai chạy được → chết lúc lập kế hoạch; analyst bật sandbox Docker,
  chuỗi viết-code→chạy-thật→báo-cáo đã sống, engine=deep_agent) · review CHỈ terminal +
  external_write (hết nổ 23 dòng) · queue ưu tiên task chưa-chạy (hết đói 40').
  Đuôi v64 đóng cùng ngày: round-robin stateless (task hoạt-động-cũ-nhất trước, nuốt
  rule chống-đói) · read-path `_approval_status` scope theo assigned_to như write-path.
- [x] **Autopilot toàn quyền (v63, CEO chốt 2026-08-04 "Toàn quyền thật")**: flag
  `company.yaml::autopilot` + lệnh `set_autopilot on|off`; bật → tự xác nhận kế hoạch
  (đường hash-bind của `team_task_auto_confirm`), tự gỡ stall (thang retry→accept/drop,
  trần 2 lượt/task, `autopilot_sweep`), tự duyệt Lớp B đang chờ trong ticker
  (`transition_if_pending` — CEO bấm trước thì thắng). Opt-out per-task bằng cụm
  "để anh duyệt" khi giao (`require_ceo_approval`). Bất biến giữ: Lớp A + cost cap;
  audit + báo lại qua office event → admin mirror.

### Sản phẩm
- [x] ~~**Web-search key cảnh báo → hành động**~~ — **đóng 2026-08-03**: v56 đã nhắc ngay
  preview giao việc (và chốt KHÔNG auto-tắt flag — flag là ý định người dùng); v57 máy đã có
  key (Brave dùng lại từ openclaw). Hết việc.
- [x] ~~**Queue transparency**~~ — xong v58: card kanban hiện "⏳ xếp sau N việc (~N phút)"
  theo đúng thứ tự ticker phục vụ.
- [ ] **QA reply persist (tùy chọn)**: câu trả lời "hỏi tiến độ" hiện không lưu — thêm
  kind lưu nếu CEO muốn lịch sử hỏi-đáp.
- [ ] **Chi phí classify/QA vào cost-cap**: hiện chỉ log, chưa tính vào trần chi phí việc.

### Kỹ thuật (hướng "Nền vững" — thứ tự chốt 2026-08-01)
- [x] **1. Playwright smoke cockpit (v56, 2026-08-01)**: 8 test đo DOM thật (page-no-scroll,
  scroll trong khung, composer luôn thấy, overlay không đẩy grid, gộp ×17, filter/search,
  chấm ● live qua SSE reconnect thật, mobile stack) — toàn bộ /api mock trong browser,
  CI job `frontend-e2e` secret-free. `plans/260801-1948-v56-playwright-smoke-and-cleanup/`.
- [x] **2. Vòng dọn dẹp gộp (v56)**: web-search thiếu key → dòng nhắc ngay trong preview
  giao việc (không auto-tắt flag — flag là ý định người dùng; trang Đội đã có health
  check v18) · focus-trap + `HTTP <status> — <detail>` cho artifact viewer (GET giờ parse
  detail như write) · GC artifact dir mồ côi (guard kép: không task row + >7 ngày).
  Bonus từ review: audit orphan v36 quét SAI đường dẫn từ đầu (chưa bao giờ thấy gì) —
  sửa bằng helper path chung `team_task_artifacts_root()`.
- [x] ~~**3. Opaque `attempt_id` cho review tray**~~ — xong v58: event review mang id mờ,
  tray join thẳng, heuristic v54 thành fallback event cũ.
- [x] ~~`/api/office/assign/staff` load_profile per-staff~~ — xong v58: yaml-peek chung
  `peek_profile_yaml`, test chống tái phát.
- [x] ~~**Nghiên cứu harness openhuman**~~ (CEO đặt 2026-08-31, xong cùng ngày) — report:
  `plans/reports/research-260831-1827-openhuman-emulation-report.md`. Kết luận: harness tách
  4 lớp (definition data / loop / policy gate / orchestration); đáng mượn Ý TƯỞNG (GPL-3.0
  cấm copy code): P1 = BudgetStopHook (biến `cost_cap_usd` observability-only thành hard
  stop giữa các iteration) + `max_result_chars` nén kết quả fanout; P2 = ToolCallContext cho
  `hard_block.classify`, progressive-disclosure handoff cho tool result quá cỡ (khớp lỗ
  truncation v92), ToolStats tracker. KHÔNG mượn: Memory Tree, medulla, TokenJuice, tool
  ranking mờ, worktree per agent, DAG ledger. Chưa cam kết tích hợp — chờ CEO duyệt P1.
- Modularization >200 LOC: KHÔNG đứng riêng — `team_task_graph.py` (920 LOC) là lõi đã
  red-team nhiều vòng, refactor vì đếm dòng = rủi ro > lợi. Áp rule khi chạm file có lý
  do hành vi.

## Ngoài phạm vi hiện tại (cần thiết kế lại nếu mở)

- Multi-user / hosted multi-tenant (auth + isolation phải làm lại).
- RBAC, thanh toán, chạy cloud.

## Nguyên tắc khi thêm tính năng

1. Brainstorm → plan → **red-team plan** → cook → review → **E2E thật** → docs/journal.
2. Field mới trên step → hỏi "có va `_verify_plan_hash` không?" (metadata phải NGOÀI hash).
3. Ghi ra ngoài mới → PHẢI qua Action Gateway.
4. Không phá 6 bất biến (xem HANDOVER §5).
