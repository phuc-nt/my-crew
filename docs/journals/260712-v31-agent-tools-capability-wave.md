# v31 — Agent-tools capability wave (hậu kiểm + 4 native type + wake-gate + OpenAlex)
2026-07-12 · ✅ Done (P1-P6 một phiên cook, live E2E từng phase; P7 reddit/youtube CẮT theo khuyến nghị plan)

## Làm gì
- **Hậu kiểm fleet-wide** (nửa còn thiếu của v30): `GET /api/company/activity` gộp audit + runs + captures mọi agent (projection allowlist, bounded), web view "Hoạt động" ở nav CEO-primary, lệnh ops-chat `company_activity` — LLM tóm tắt audit thật, mọi row bọc `format_internal_content` chống injection.
- **4 action type native mới qua 1 cửa gateway**: `schedule_update` (agent tự đổi lịch CHÍNH MÌNH — cron floor */5, cap 6 entry + 5 lượt/ngày, CEO Telegram notice mỗi lần chạy), `team_task_create`/`team_task_move` (thẻ việc kanban — quyền đối chiếu STORE: assignee ∈ roster, move chỉ PIC/người tạo/người nhận bước), `gws_write` (Sheets/Docs qua gws CLI — bảng 3 prefix cứng, gmail đi đường `email_send`). Guarded queue / autonomous chạy ngay + audit; Lớp A gác mọi mode.
- **Wake-gate watcher (hồi sinh v29a)**: `watchers:` trong profile.yaml → pseudo-kind `watch` 5 phút, poll KHÔNG-LLM (Jira/GitHub/Sheets) → normalize → hash → diff mới wake đúng 1 lần; nguồn không đổi = 0 LLM (đo capture store live). Fail ×3 / im lặng >24h → DM CEO.
- **OpenAlex** `academic.search`: tra paper không cần key cho tools-tier, opt-in per-agent `academic_search: true`; query redact trước egress, kết quả bọc untrusted + bounded.
- Suite 1894→**2019 BE** + 180→**183 FE**; ruff + tsc sạch. E2E thật: sales-pm đổi lịch qua chat door + notice CEO; hr tạo/move card + append Sheet A14 + tạo/ghi Doc thật; noi-dung watch Jira SCRUM (wake → task, tick 2 = 0-LLM); LLM tóm tắt audit thật.

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Deny cấu trúc/floor/prefix của type mới = category CỨNG (SECURITY/DATA_LOSS), KHÔNG NOT_ALLOWLISTED | Autonomous re-entry `approved=True` bỏ qua NOT_ALLOWLISTED — chat door chặn nhưng execute/approve door lọt | Không human-approve được một action sai cấu trúc (đúng ý: sửa payload, không duyệt bừa) |
| Identity self-only = closure tại call site có `loaded` (`make_agent_bound_dispatch`), payload KHÔNG mang agent_id | Không có field để giả mạo = không cần validate; cli.py legacy không có loaded → raise named-error | Legacy CLI approve không hỗ trợ type mới (đã doc) |
| Probe pack-load cho native type CHỈ kiểm vetted-set, KHÔNG struct-check | Struct-check là hard category → probe `args:{}` sẽ chặn pack hợp lệ khỏi boot (chicken-egg) | Struct sai chỉ lộ lúc runtime — nhưng bị chặn 2 lần (classify + handler) |
| Wake vehicle = team-task enqueue `create_task`+`set_plan` 1 step pre-built (không decompose) | Tái dùng nguyên đường step chuẩn (lease/capture/office-event); run-kind mới phải dựng harness graph trùng lặp; điểm trừ gốc của phương án task (decompose LLM) tự tiêu khi plan dựng sẵn | Cần coordinator chạy; agent watcher phải roster-assignable (check trước enqueue) |
| Handler TỰ re-enforce toàn bộ policy trước side-effect | execute_approved/approve reach handler không qua chat door; không tin classify đã chạy | Check ×2 mỗi lần chạy (rẻ so với rủi ro) |
| Ops readonly `needs_llm: True` → engine truyền `run(slots, llm=)` | Catalog là dict module-level — không có điểm build closure như phase file gợi ý; contract mở rộng opt-in, lệnh cũ byte-tương-đương | Thêm 1 nhánh dispatch trong ops_chat |

## Vấp & học được
- **Review bắt HIGH thật trước ship**: `team_task_move` cho participant chuyển planning→open — bypass cửa hash-bind `confirm_plan`, ticker sẽ dispatch plan CEO chưa duyệt. Vá: cấm planning→open/running trong handler + redline test. Bài học: type mới đụng store có state-machine phải rà TỪNG transition với cửa duyệt hiện có, không chỉ quyền actor.
- Cron hợp lệ cú pháp nhưng không bao giờ chạy (`0 0 30 2 *`) làm croniter raise xuyên qua `classify()` — policy verdict phải là reason string ở mọi door, không phải exception.
- Stale-alert viết xong là dead code: đo từ `last_checked_at` mà chính poll thành công vừa refresh nó. Semantics đúng = đo từ `last_advanced_at` (lần đổi cuối). Bài học: alert theo "thiếu sự kiện" phải đo từ mốc sự kiện, không từ mốc quan sát.
- Dandori hook chặn Write vì fake key `sk-…` trong test (false-positive quen từ v16) — ghép chuỗi runtime để source không chứa pattern, `contains_secret` vẫn thấy giá trị thật.

## Mở / sang sau
- P7 reddit/youtube CẮT (dep 1.5GB, không hợp read-tool) — đường đúng sau này là deep_agent sandbox.
- Fleet chưa có agent tools-tier nào → `academic.search` chưa có E2E agent-trong-loop (tool + flag + skill picker đã verify); bật khi có agent `agent_runtime: create_agent` thật.
- Confluence/Linear watcher fail-closed chờ idempotency test với page thật; `schedule_update` vs admin-API sửa profile cùng lúc = last-writer-wins (chấp nhận, tần suất thấp).
