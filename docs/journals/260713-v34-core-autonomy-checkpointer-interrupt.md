# v34 — Lõi autonomy: checkpointer team-graph, interrupt clarify, follow-up, criteria review
2026-07-13 · ✅ 4/5 phase Done, P4 fan-out HOÃN chờ CEO (suite 2066→2091 BE + 200 FE)

## Làm gì
- **Checkpointer cho team-step graph** (đảo YAGNI-cut v13 có evidence mới): thread `team:<task_id>:<step_id>` trên SqliteSaver riêng (`team_checkpoints.sqlite3`); attempt MỚI **adopt** state của attempt chết (`update_state` stamp attempt_id — store write luôn khớp lease sống); checkpoint FINISHED (crash giữa deliver-END và mark_done) → short-circuit không double-deliver; mất/vênh checkpoint → chạy mới y hệt pre-v34; xoá thread eager khi xong + ticker sweep thread mồ côi.
- **`interrupt()` clarify** — nâng queue v33 thành dừng-giữa-step: node `await_clarify` TÍ HON giữa work và self_check (re-run miễn phí); agent nháp an toàn → hỏi CEO → graph pause (`waiting_clarify` + cột `clarify_id`) → CEO trả lời (web/Telegram v33) → ticker poll `ClarifyStore` → worker resume `Command(resume=answer)` → **rework theo đúng câu trả lời**; expired → resume "" → ship bản nháp an toàn. Graph không checkpoint giữ nguyên fire-and-forget v33.
- **Follow-up sweep**: coordinator đeo bám việc kẹt — detect PURE SQL (stalled / 24h không tiến triển / chờ-CEO >4h), bậc thang office-event → câu hỏi clarify ("Đợi thêm"/"Huỷ việc") → Telegram, cooldown 8h/task, hồi phục thì reset bậc, rung không tới nơi (cap/dedup) KHÔNG leo bậc.
- **Review theo tiêu chí**: decompose prompt bắt tiêu chí ĐO ĐƯỢC + tôn trọng tiêu chí CEO nêu; self_check/review chấm TỪNG tiêu chí (`criteria` optional, parse bao dung — model yếu không phá verdict); verdict artifact mang checklist; room event chỉ mang ĐẾM (x/y tiêu chí đạt — no-content-echo); FE hiện "x/y tiêu chí đạt".

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Thread id KHÔNG chứa attempt_id | Cả mục đích là attempt mới nhặt tiến độ attempt chết; zombie-guard vẫn là trọng tài qua lease | Zombie kill-fail có thể ghi checkpoint rác — store write attempt-guarded chặn hậu quả |
| Interrupt SAU work (nháp trước, hỏi sau) thay vì trước | Node interrupt tí hon re-run miễn phí (interrupt() re-chạy node từ đầu khi resume); tái dùng nguyên máy rework; CEO không blốc việc nháp | Trả lời của CEO tốn 1 rework_count |
| P4 fan-out HOÃN | Parallel theo plan sẵn có (7 bước + cap 2); fan-out runtime đụng lõi dispatch, YAGNI risk cao nhất wave | Trình CEO quyết cắt hẳn hay làm khi có nhu cầu thật |
| Tiêu chí GIỮ ngoài plan-hash | Quyết định v13 đã verify (hash byte-compat); amend vẫn là cửa sửa | Khác câu chữ phase file gốc — annotate thay vì đảo thiết kế |
| Follow-up v1 không auto-act trên answer | Ghi nhận + CEO tự hành động (amend/cancel) an toàn hơn auto-reassign | Thêm 1 thao tác tay cho CEO |

## Vấp & học được
- **Review bắt 2 HIGH đúng góc crash wave này sinh ra để xử**: (1) dead-end detector không đếm `waiting_clarify` là in-flight → 1 step fail + 1 step chờ CEO = task bị stall oan, clarify mồ côi; (2) crash giữa interrupt-checkpoint và `mark_waiting_clarify` → dispatch lại trả clarify_id=None + XOÁ nhầm thread resume. Vá: đếm in-flight đủ 3 status; clarify_id móc từ INTERRUPT PAYLOAD (values không bao giờ có); không xoá thread khi status trả về là waiting_clarify.
- Test vá H2 còn bắt thêm bug thứ 3: `update_state` chạy TRƯỚC check pending làm hỏng interrupt của thread khi dispatch sớm — đảo thứ tự, chỉ adopt khi thật sự resume. Bài học: state-machine crash-window phải test qua saver THẬT, SimpleNamespace snapshot không đủ.
- DedupStore không TTL → dedup_hint tĩnh làm rung-3 câm vĩnh viễn sau 1 lần — hint bucket theo NGÀY (1 tin/ngày cho việc kẹt mãi).
- `awaiting_approval` END-state không được short-circuit khi resume (deliver phải chạy lại sau approve) — suite cũ bắt được ngay vì có test đường này từ v13.

## Mở / sang sau
- **CEO quyết P4 fan-out**: cắt hẳn (khuyến nghị) hay làm khi parallel-theo-plan chứng minh không đủ.
- E2E live (kill -9 giữa step LLM thật + interrupt qua Telegram thật): chạy khi CEO bật service daemon — cơ chế đã chứng minh bằng integration test trên saver/graph thật.
- Backlog nhỏ (review lows, chấp nhận có ghi chú): capture telemetry đếm trùng work-cost qua pause/resume (cost cap và step-row không ảnh hưởng); zombie kill-fail ghi checkpoint rác (attempt-guard chặn hậu quả).
