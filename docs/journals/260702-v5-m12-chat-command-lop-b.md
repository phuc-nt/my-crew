# v5 M12 — Chat-command qua Lớp B ("đồng nghiệp nhờ được")
2026-07-02 · ✅ Done

Bậc 3 của thang trách nhiệm: từ "trả lời được" (M11) lên "**nhờ được**". Mention agent với một yêu cầu tiếng Việt tự nhiên → agent soạn action → **LUÔN vào hàng chờ Lớp B** → người bấm duyệt → action chạy thật. Chat mở rộng *phạm vi yêu cầu*, không mở rộng *quyền thực thi* — THE INVARIANT nguyên vẹn.

## Làm gì
- **2 primitive core generic mới**: `ActionGateway.enqueue_for_approval` (ép Lớp B theo origin — classify Lớp A/allowlist TRƯỚC, action bị chặn thì refuse-not-queue, audit deny; không đụng ngữ nghĩa `classify()`/`needs_interrupt()`) + **jira dispatch** (`jira_write.py` + nhánh trong `approved_dispatch` — jira createIssue/addComment được allowlist từ v1 nhưng chưa từng có đường thực thi; giờ approve mới chạy được).
- **Catalog = pack asset** (`commands.py:COMMANDS`): trần cứng của những gì chat được phép YÊU CẦU. Validate lúc load: probe `classify()` từng command (tool red-line/ngoài allowlist → RuntimeError ngay khi load pack, không đợi runtime), `build_args` phải callable, COMMANDS rỗng fail-loud. pm-pack v1 = đúng 1 lệnh `create_issue` (projectKey lấy từ CONFIG của agent — người yêu cầu không trỏ được sang project khác vì field lạ bị reject).
- **An toàn cấu trúc, không prompt-hope** (bài học M11): LLM chỉ PHÂN LOẠI ({question|unsupported|command_id+args}, JSON; parse hỏng → question); args validate bằng CODE theo schema (required/độ dài/pattern, field lạ reject); action build bằng CODE. LLM không bao giờ viết action dict.
- **Wire vào M11**: `answer_mention` rẽ nhánh command trước Q&A (pack không catalog → không gọi classifier, byte-identical M11); reply "⏳ chờ duyệt #id + nơi duyệt" qua cùng đường sanitize + gateway + dedup; re-poll không double-enqueue (marker mention-ts trong reason của approval).

## Review (DONE, 0 HIGH — reviewer xác nhận "no path executes a chat-requested action without human approval") → vá 3 điểm
- **M1**: classifier nuốt lỗi hạ tầng thành "question" → provider timeout biến "tạo ticket" thành câu trả lời Q&A và lệnh mất vĩnh viễn → vá: `INFRA_ERRORS` (chung với inbox, chuyển về fallback_policy) re-raise → watermark giữ, lệnh được retry.
- **M2/L5**: `build_args` không callable âm thầm dùng args thô + COMMANDS rỗng âm thầm tắt catalog → cả hai fail-loud lúc load.
- Ghi nhận không vá (chấp nhận, có test/backstop): approve dưới DRY_RUN tiêu thụ approval (pre-existing); jira dispatch tool-generic (chỉ tới được sau duyệt người + Lớp A re-check); cost classifier cho câu hỏi thường không vào run-event (budget tracker vẫn tính đủ).

## E2E LIVE — vòng đầy đủ bậc 3
Mention thật: *"@default tạo ticket giúp mình: lỗi đăng nhập trang admin, người dùng bị văng ra khi refresh trang"* → classifier trích đúng summary + description từ câu tiếng Việt → reply thread "⏳ Đã xếp hàng chờ duyệt **#23**: create_issue (projectKey=SCRUM, …)" — **Jira lúc này chưa có gì** → `mpm agent approve default 23` → **SCRUM-23 tạo thật** trên Jira Cloud → re-poll `no_mentions`, approval consumed. (Issue SCRUM-23 để lại làm fixture test tenant.)

## Verified
940 pytest (18 mới) + ruff clean; red-line tests: action Lớp A không bao giờ được queue; catalog cấm khai tool cấm; LLM output dị dạng không bao giờ thành action.

## Bài học
- "Ép Lớp B theo origin" không cần sửa ngữ nghĩa guardrail — một method MỚI chặt hơn (refuse-or-queue) giữ INVARIANT sạch hơn là thêm cờ vào đường execute cũ.
- Fallback an toàn ("mọi lỗi → question") vẫn có thể là bug: phải tách lỗi-hạ-tầng (retry) khỏi lỗi-nội-dung (degrade) — lần thứ 2 pattern này xuất hiện trong 1 ngày (inbox M11, classifier M12).
- Jira write "allowlisted nhưng chưa từng dispatch" — allowlist mà không có executor là quyền trên giấy; khi thêm executor phải nhớ nó mở rộng hiệu lực của MỌI approval jira cũ, không chỉ feature mới.
