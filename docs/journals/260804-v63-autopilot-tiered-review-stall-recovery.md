# v63 — Autopilot toàn quyền + review theo cỡ việc + gỡ-stall một chạm
2026-08-04 · hoàn thành

## Làm gì

- Review theo cỡ việc: `external_write` trên step (vào plan_hash CONDITIONAL như
  `needs_shell` — DAG cũ hash y nguyên); waiver code-side task ≤3 bước nội bộ → bỏ
  peer review; verdict `passed_with_notes` không mint rework, góp ý vào aggregate.
- Gỡ-stall một chạm: `accept_stalled_result`/`retry_stalled_step`/`drop_stalled_step`
  (`ops_stalled_task.py`) + store primitives guard trạng thái (`reopen_stalled`,
  `reset_step_to_pending`, `mark_step_dropped`); escalate kèm evidence pack (failures
  wrapped) + 3 lệnh gợi ý điền sẵn task_id.
- Autopilot (CEO chốt "Toàn quyền thật"): `company.yaml::autopilot` + `set_autopilot`;
  tự confirm kế hoạch (tái dùng nguyên đường `team_task_auto_confirm`), tự gỡ stall
  (thang định trước retry→accept/drop, trần 2 lượt/task, không LLM — `autopilot_sweep`),
  tự duyệt Lớp B trong ticker (`transition_if_pending`, scoped đúng store của
  `assigned_to`). Opt-out per-task: "để anh duyệt" → `require_ceo_approval`. Audit =
  office event `autopilot_decision` → admin mirror DM (không plumbing mới).
- `list_team_tasks` (bảng thẻ việc + retro soát/sửa/chi phí) — "liệt kê các thẻ việc"
  hết rơi unsupported; digest chống quên KHÔNG xây vì `follow_up_sweep` v34 đã làm.
- Suite 2499 BE xanh (+40 so v62); UAT sống: task kẹt `9ee8a4f028f0` gỡ bằng lệnh
  qua Telegram-path thật, autopilot tự accept nấc 2 và tự chạy nốt rework.

## Quyết định & vì sao

| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Autopilot duyệt cả Lớp B external write | CEO chốt rõ ("Toàn quyền thật") dù được khuyên mức thấp hơn — chống bottleneck | Classifier sai khi bật = write thật đi ra; bù bằng notify-after + audit + opt-out per-task; Lớp A + cost cap bất biến (pin test) |
| Flag ở company.yaml, không SQLite store mới | Tiền lệ `team_task_auto_confirm` y hệt nhu cầu (persist, đọc tươi) | Lệch plan ban đầu — ghi deviation vào phase file |
| Thang gỡ-stall định trước, không LLM | Chính là default plan mô tả; tái lập được, không thêm bề mặt injection | Kém "thông minh" hơn LLM choice — đủ cho 2 nấc |
| Waiver "≤3 bước VÀ không external_write" | CEO chọn kết hợp; gate theo hậu quả đúng chuẩn HITL | LLM quên set external_write → bước ghi-ngoài thoát review; Lớp B action-time vẫn chặn |

## Vấp & học được

- Reviewer đối kháng bắt được C1 nghiêm trọng mà test tự viết che mất: test mô phỏng
  re-stall bằng `set_task_status` tay thay vì chạy tick thật — retry hóa ra vô dụng vì
  ticker re-stall TRƯỚC khi dispatch rework. Bài học: hành vi xuyên-tick phải test bằng
  `run_one_tick` thật, không mô phỏng trạng thái trung gian.
- Approval id là AUTOINCREMENT per-FILE (mỗi agent đếm 1,2,3…) — scan cross-store theo
  bare id là đường trúng nhầm hàng của agent khác; docstring cũ khẳng định sai
  "process-wide unique". Write path giờ scoped theo `assigned_to`.
- plan_hash task cũ lệch sau migration v62 "vô hại vì task đã terminal" — SAI khi v63
  cho phép MỞ LẠI task terminal: reopen là dispatch là verify hash. Đã fix data 1 task;
  quy tắc mới: migration đổi id phải recompute plan_hash mọi task, kể cả terminal.
- `deepagents` lại rơi khỏi venv giữa phiên (uv sync không `--extra deep`, lần 2 sau
  v56) — 1 test đỏ + 67 test skip lặng lẽ; số test tụt là tín hiệu sớm hơn test đỏ.

## Mở / sang sau

- `_approval_status` (read half) vẫn scan cross-store theo bare id — wrong-row READ
  còn tiềm ẩn, đã ghi caveat trong docstring, cần scope theo assigned_to như write half.
- Backlog giữ: Postgres/SQLite cross-agent memory · nhắc-việc-theo-giờ · A2A clarify
  (đo lại sau khi waiver chạy thật một thời gian).
