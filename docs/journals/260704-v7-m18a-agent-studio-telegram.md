# v7 M18a — Agent Studio: agent chạy-ngay (bind Telegram) + trang agent hợp nhất

2026-07-04 · ✅ Done

Lấp gap "gãy flow" của wizard tạo agent (M7): trước đây tạo xong dừng ở "copy .env template đưa người kỹ thuật" — agent CHƯA chạy được. Giờ: tạo agent → gắn bot Telegram từ web (dán token) → nhắn được ngay. Không đụng terminal/.env tay.

## Làm gì
- **bind_telegram** (`routes_agent_knowledge.py`): dán token → **getMe validate** (token sai → 400, không ghi gì) → ghi `<AGENT>_TELEGRAM_BOT_TOKEN` vào .env (qua env_writer, whitelist telegram-token pattern) → thêm `telegram:` block vào profile.yaml (validate-then-atomic) → **override-load** key vừa ghi → token có hiệu lực NGAY. KHÔNG cần restart như M17 session-secret: `resolve_bot_token` đọc os.environ PER-CALL (mỗi lần gửi), khác session-secret bind-once ở create_app.
- **telegram_recent_chats**: getUpdates → hiển chat id vừa nhắn bot (CEO bấm chọn thay vì mò chat id).
- **AgentPage** (`/agents/:id`): trang hợp nhất — header (tên/domain/trạng thái/việc chờ duyệt) + tab Hoạt động (chi phí + lịch sử chạy, gom API status/cost/runs SẴN CÓ) + tab Kênh Telegram (bind panel). Team click agent → trang này; wizard tạo xong → redirect trang này với banner "gắn bot → nhắn được ngay".

## An toàn (đường ghi env SAU setup)
Khác M17 (setup, chưa auth): M18a chạy SAU setup → session-gated (AuthMiddleware chặn chưa-login). Chỉ ghi key telegram-token pattern (whitelist), write-only (response chỉ trả bot_username + env_name, KHÔNG trả token). Cùng trust level route admin write sẵn có (create/enable/delete — no-gateway config write, session-gated). Không nới quyền.

## Review 1 CRITICAL + 1 HIGH → vá
- **C1 (CRITICAL) partial write**: bind KHÔNG chat_id → `merge_env` ghi token vào .env TRƯỚC, rồi `save_profile_yaml`→`build_telegram` RAISE (chat_ids rỗng) → .env có token mà profile không có block. Đây cũng là workflow UI chính (bind trước, lấy chat sau) → deadlock: getUpdates cần token, bind cần chat. Vá: (1) require ≥1 chat_id, **400 SỚM trước mọi ghi** (getMe không gọi); (2) `recent_chats` chuyển POST nhận token pasted (chưa persist) → lấy chat TRƯỚC bind, phá deadlock; (3) UI nút Gắn bot disable khi thiếu chat_id.
- **H1 (HIGH tự vá trước review) rebind ghi đè block**: rotate token qua web ghi đè toàn `telegram:` block → mất `ops_operator_id`/chat_ids nhập tay. Vá: merge vào block cũ (giữ field khác, chỉ cập nhật bot_token_env + chat_ids nếu cấp).
- **M1 test phantom**: test cũ stub `save_profile_yaml` no-op → validate thật không chạy, che C1. Vá: stub gọi build_telegram thật → block sai fail ngay trong test.

## Verified
1080 pytest (8: token pattern, getMe validate+persist, C1-400-sớm-no-partial-write, recent-chats-token-pasted, rebind-giữ-chat_ids, bad-token, bad-agent-id, empty-token) + 44 vitest + ruff + build. **E2E LIVE data thật (sau C1 fix)**: bind không chat_id → 400, .env KHÔNG có token (no partial write) → recent-chats token pasted OK → bind với chat_id → `@phucnt_my_pm_bot` → .env có token → agent load chạy được. Dọn fixture.

## Bài học
- **Không phải mọi ghi-env đều cần restart**: M17 session-secret bind-once ở create_app → buộc restart. M18a token đọc per-call (`resolve_bot_token`) → override-load đủ. Phân biệt "config đọc 1 lần lúc build" vs "đọc mỗi lần dùng" quyết định có cần restart.
- **Validate TRƯỚC persist**: getMe trước khi ghi .env/profile → token sai fail loud trong wizard, không đẻ bot chết im lặng. Đây là điều M13 (setup tay) thiếu — giờ web validate hộ.
- **Trang hợp nhất = gom view sẵn có, backend 0 đổi**: AgentPage chỉ compose status/cost/runs API cũ; đường write duy nhất là bind telegram. Đúng nguyên tắc v7 "mặt tiền, không đụng backend logic".

## Bài học thêm (từ review)
- **Ghi 2 nơi phải all-or-nothing hoặc validate-trước-write**: ghi .env rồi ghi profile — nếu profile fail, .env đã bẩn (partial). Đúng: validate ĐỦ điều kiện (chat_id) TRƯỚC mọi ghi, fail sớm. Bài lặp: M17 whitelist all-or-nothing, giờ M18a chat_id-check-trước-write.
- **Test stub che validate = phantom coverage**: stub `save_profile_yaml` no-op làm C1 pass CI. Stub phải giữ lại phần validate load-bearing (build_telegram), không chỉ "ghi nhận đã gọi".
- **UI cho phép cái backend cấm = bug chờ nổ**: nút Gắn bot chỉ check token, nhưng backend cần chat_id → user bind được cái sẽ fail. UI phải phản ánh đúng ràng buộc backend.

## Unresolved / next
1. M18b: SOUL/PROJECT thành form (↔ markdown 2 chiều) + skills picker.
