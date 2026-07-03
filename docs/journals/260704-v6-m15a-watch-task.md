# v6 M15a — Giao việc & theo dõi nhiều ngày (watch-task)

2026-07-04 · ✅ Done (M15a — watch-task; report-task/qa-task + web board → M15b)

Bậc 4 thang trách nhiệm: từ "nhờ được" (M12, 1 lệnh → 1 action → xong) lên "**giao việc sống nhiều ngày**". CEO giao "theo dõi PR #45 tới khi merge, nhắc mỗi sáng" → agent tự check theo nhịp, cập nhật, xong tự báo + đóng. Phạm vi M15a (chủ dự án chốt): watch-task trọn vòng đời trước; report-task/qa-task + web board /tasks để M15b.

## Làm gì
- **TaskStore per agent** (`task_store.py`, SQLite như ApprovalStore): id/kind/params/schedule/status/fail_streak/history. Vòng đời `open → running → done | cancelled | stalled`. Cap `MAX_OPEN_TASKS=10` chặn phình (R1). Persist qua restart (task giao thứ Hai vẫn theo dõi thứ Tư).
- **watch-task check CODE-only** (`watch_task.py`): đọc state PR qua `gh pr view --json state` → stop condition bằng CODE (MERGED/CLOSED → done; deadline 14 ngày → done timeout; else → nhắc). **LLM KHÔNG quyết "xong rồi"** — watch check tốn 0 token. Reminder text deterministic.
- **Task runner** (`task_runner.py`) hook vào service tick qua pseudo-kind `tasks` (như inbox M11): check mỗi task open, post reminder/done/stalled qua Action Gateway. Watermark discipline: INFRA_ERRORS → giữ status+streak, retry (lỗi mạng thoáng qua KHÔNG stall task khỏe); content error → bump streak → stalled sau STALL_AFTER=3; 1 task lỗi không dừng task khác. Dedup reminder per-day.
- **Giao qua ops chat M14**: 3 command `watch_pr` (write, confirm 2 bước), `list_tasks` (readonly), `cancel_task` (write, confirm). Không lệnh xóa nguy hiểm; pr_number validate pattern số.
- **Schedule wiring** (`task_scheduling.py`): `_effective_schedule` chỉ thêm `tasks` kind khi agent CÓ open tasks (has_open_tasks mở store read-only mỗi tick — rẻ, indexed COUNT). Không task → byte-identical pre-M15.

## INVARIANT — task KHÔNG nới quyền
Mọi mutation của task qua `gateway.execute` đúng phân loại cũ. E2E chứng minh sống động: reminder post tới channel EXTERNAL của default agent → **vào Lớp B chờ duyệt** (approval #26), không auto-post. Task chỉ là lịch + stop condition bọc quanh năng lực sẵn có; guardrail nguyên vẹn.

## E2E LIVE — vòng đầy đủ bậc 4
1. **Giao qua chat** (ops engine LLM thật): "theo dõi giúp PR số 1 của agent default tới khi merge" → preview → "xác nhận" → task #1 tạo thật.
2. **Check lần 1** (gh THẬT): PR #1 "Feature: retention push notifications" OPEN → task vẫn open, history ghi nhắc, post Slack → Lớp B (channel external) → approval queue. Guardrail đúng.
3. **Check lần 2** (stub gh MERGED — không đụng PR thật, theo chốt chủ dự án): stop condition CODE quyết "đã merge" → task **tự done** + history 2 dòng đầy đủ.

## Review (DONE_WITH_CONCERNS) → vá 1 CRITICAL + 2 HIGH + medium/low
- **C1 (CRITICAL) — feature chết trong service, test mù**: `has_open_tasks` đọc `settings.data_dir/tasks.sqlite3`, nhưng service load profile KHÔNG truyền data_dir → `settings.data_dir` = global `.data/`, còn store thật ở `.data/agents/<id>/`. `path.exists()` luôn False → service KHÔNG BAO GIỜ fire `tasks` kind → runner không chạy. CI xanh vì `has_any_inbox` (pattern copy) đọc config FIELD không đọc filesystem, còn test đều inject data_dir=tmp_path nên không chạm đường load thật của service. E2E của tôi cũng mù vì gọi runner trực tiếp. **Vá**: `has_open_tasks` derive store dir từ `agent_data_dir(profile_id)` (khớp `_task_store_for`); thêm test drive `_effective_schedule` qua ĐÚNG đường load service (không inject data_dir) — xác nhận sống.
- **H1+H2**: copy "nhắc mỗi sáng" sai (runner không đọc per-task cron, chỉ dedup per-day + service tick hàng giờ; TZ local vs UTC lệch) → sửa copy "mỗi ngày" + xóa dead code `_is_due`/`_STATE_FILE` (cơ chế cadence để M15b).
- **M1/M2/L2/L3**: byte-identical guard length-based → flag-based; bọc lỗi không leak path profile vào chat; docstring bỏ issue/Jira target (M15a chỉ pr); empty gh state → content error (bump streak) thay vì spam nhắc.

## Verified
1024 pytest (20 mới, gồm service-path scheduling test bắt C1 + empty-gh content-error) + ruff clean.

## Bài học
- **Pseudo-kind là điểm mở rộng rẻ**: inbox (M11) rồi tasks (M15) đều cắm vào service tick qua cùng cơ chế `_effective_schedule` synthesize kind + worker branch. Không cần polling loop riêng.
- **"Task không nới quyền" phải verify ở RUNTIME, không chỉ nói**: E2E vô tình chứng minh khi reminder external bị Lớp B chặn — đúng là điều cần (task chạy dài nhưng mọi post vẫn qua guardrail cũ). Nếu chỉ test internal channel sẽ bỏ sót bằng chứng này.
- **Stop condition CODE-only là bất biến an toàn cốt lõi**: nếu để LLM quyết "PR xong chưa" thì một prompt injection trong title PR có thể lừa done sớm. State string từ gh + deadline là nguồn sự thật.
- **Copy pattern có thể copy luôn cả cái bẫy** (C1): `has_open_tasks` bắt chước `has_any_inbox` nhưng `has_any_inbox` đọc config FIELD (miễn nhiễm data_dir default), còn `has_open_tasks` đọc FILESYSTEM (không miễn nhiễm). Service load profile không truyền data_dir → path sai. Bài học: khi copy pattern check-điều-kiện, kiểm nguồn dữ liệu (field vs filesystem) có cùng độ nhạy data_dir không. Và test phải drive qua ĐÚNG đường caller thật (service), không chỉ inject fixture — nếu test luôn set data_dir=tmp thì mọi lỗi data_dir-mismatch đều tàng hình.

## Unresolved / M15b
1. report-task (chạy report kind theo lịch riêng) + qa-task (câu hỏi lặp qua đường M11).
2. Web board `/tasks` (danh sách + tiến độ + nút hủy) + wire Team view đếm việc đang chạy.
3. Giao task qua mention agent (chat_command M12) — hiện chỉ qua ops chat CEO (M14). Operator-gate cho mention = quyết định sau.
4. watch-task target='issue' (Jira) — M15a chỉ 'pr'.
