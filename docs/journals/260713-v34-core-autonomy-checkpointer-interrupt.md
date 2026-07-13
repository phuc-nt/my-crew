# v34 — Lõi autonomy: checkpointer team-graph, interrupt clarify, follow-up, criteria review
2026-07-13 · ✅ 5/5 phase Done (P4 thiết kế lại + cook sau khi CEO duyệt; suite 2066→2103 BE + 200 FE)

## Làm gì
- **Checkpointer cho team-step graph** (đảo YAGNI-cut v13 có evidence mới): thread `team:<task_id>:<step_id>` trên SqliteSaver riêng (`team_checkpoints.sqlite3`); attempt MỚI **adopt** state của attempt chết (`update_state` stamp attempt_id — store write luôn khớp lease sống); checkpoint FINISHED (crash giữa deliver-END và mark_done) → short-circuit không double-deliver; mất/vênh checkpoint → chạy mới y hệt pre-v34; xoá thread eager khi xong + ticker sweep thread mồ côi.
- **`interrupt()` clarify** — nâng queue v33 thành dừng-giữa-step: node `await_clarify` TÍ HON giữa work và self_check (re-run miễn phí); agent nháp an toàn → hỏi CEO → graph pause (`waiting_clarify` + cột `clarify_id`) → CEO trả lời (web/Telegram v33) → ticker poll `ClarifyStore` → worker resume `Command(resume=answer)` → **rework theo đúng câu trả lời**; expired → resume "" → ship bản nháp an toàn. Graph không checkpoint giữ nguyên fire-and-forget v33.
- **Follow-up sweep**: coordinator đeo bám việc kẹt — detect PURE SQL (stalled / 24h không tiến triển / chờ-CEO >4h), bậc thang office-event → câu hỏi clarify ("Đợi thêm"/"Huỷ việc") → Telegram, cooldown 8h/task, hồi phục thì reset bậc, rung không tới nơi (cap/dedup) KHÔNG leo bậc.
- **Runtime fan-out (P4, thiết kế lại rồi cook cùng ngày)**: bước tự khai "nên chia" qua CHÍNH propose-call của consult (0 LLM call thêm, field `split` 2-4 mục) → deliver notice, `mark_done` kèm `split_proposal_json` → **ticker mint** (mirror review-insert rule, atomic 1 transaction): N sub (`deps=[]`, chạy song song theo cap sẵn) + 1 gather (`deps=[các sub]` — fan-in `_read_deps_handoff` có sẵn, kế thừa `needs_review` của cha); downstream dep vào cha bị `ready_pending_steps` giữ tới khi con xong; artifact gather copy về seq cha để dep edge confirm đọc nội dung thật; depth-1 ba lớp; amend bị chặn khi fanout dở.
- **Review theo tiêu chí**: decompose prompt bắt tiêu chí ĐO ĐƯỢC + tôn trọng tiêu chí CEO nêu; self_check/review chấm TỪNG tiêu chí (`criteria` optional, parse bao dung — model yếu không phá verdict); verdict artifact mang checklist; room event chỉ mang ĐẾM (x/y tiêu chí đạt — no-content-echo); FE hiện "x/y tiêu chí đạt".

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Thread id KHÔNG chứa attempt_id | Cả mục đích là attempt mới nhặt tiến độ attempt chết; zombie-guard vẫn là trọng tài qua lease | Zombie kill-fail có thể ghi checkpoint rác — store write attempt-guarded chặn hậu quả |
| Interrupt SAU work (nháp trước, hỏi sau) thay vì trước | Node interrupt tí hon re-run miễn phí (interrupt() re-chạy node từ đầu khi resume); tái dùng nguyên máy rework; CEO không blốc việc nháp | Trả lời của CEO tốn 1 rework_count |
| P4 fan-out: hoãn → thiết kế lại → cook | Đánh giá lại trên code mới: ticker-insert + fan-in deps + parent_step_id + propose-call đã có sẵn — effort 1.5d→0.5d | Chia bước chỉ ở depth-1, review dồn về gather; amend bị chặn khi fanout dở |
| Tiêu chí GIỮ ngoài plan-hash | Quyết định v13 đã verify (hash byte-compat); amend vẫn là cửa sửa | Khác câu chữ phase file gốc — annotate thay vì đảo thiết kế |
| Follow-up v1 không auto-act trên answer | Ghi nhận + CEO tự hành động (amend/cancel) an toàn hơn auto-reassign | Thêm 1 thao tác tay cho CEO |

## Vấp & học được
- P4 đổi số phận nhờ đánh giá lại trên code mới: 4/5 mảnh máy "chờ-và-gom" hoá ra đã tồn tại (ticker-insert rule, fan-in deps, parent_step_id, propose-call) — thiết kế đúng thời điểm quan trọng hơn thiết kế đúng lý thuyết. Review P4 vẫn bắt 3 Medium thật: mint không atomic (crash giữa chừng mồ côi subs), amend nuốt con fanout đang chạy, và raw `_conn` write lách store API.
- **Review bắt 2 HIGH đúng góc crash wave này sinh ra để xử**: (1) dead-end detector không đếm `waiting_clarify` là in-flight → 1 step fail + 1 step chờ CEO = task bị stall oan, clarify mồ côi; (2) crash giữa interrupt-checkpoint và `mark_waiting_clarify` → dispatch lại trả clarify_id=None + XOÁ nhầm thread resume. Vá: đếm in-flight đủ 3 status; clarify_id móc từ INTERRUPT PAYLOAD (values không bao giờ có); không xoá thread khi status trả về là waiting_clarify.
- Test vá H2 còn bắt thêm bug thứ 3: `update_state` chạy TRƯỚC check pending làm hỏng interrupt của thread khi dispatch sớm — đảo thứ tự, chỉ adopt khi thật sự resume. Bài học: state-machine crash-window phải test qua saver THẬT, SimpleNamespace snapshot không đủ.
- DedupStore không TTL → dedup_hint tĩnh làm rung-3 câm vĩnh viễn sau 1 lần — hint bucket theo NGÀY (1 tin/ngày cho việc kẹt mãi).
- `awaiting_approval` END-state không được short-circuit khi resume (deliver phải chạy lại sau approve) — suite cũ bắt được ngay vì có test đường này từ v13.

## Mở / sang sau
- E2E live (kill -9 giữa step LLM thật + interrupt qua Telegram thật): chạy khi CEO bật service daemon — cơ chế đã chứng minh bằng integration test trên saver/graph thật.
- Backlog nhỏ (review lows, chấp nhận có ghi chú): capture telemetry đếm trùng work-cost qua pause/resume (cost cap và step-row không ảnh hưởng); zombie kill-fail ghi checkpoint rác (attempt-guard chặn hậu quả).
