# v6 M14a — CEO chat-ops: quản lý đội bằng hội thoại tiếng Việt

2026-07-03 · ✅ Done (M14a — engine + DM Telegram; web chat box + dashboard Việt hóa defer → M14b)

Mục tiêu lõi v6: **CEO không cần terminal**. DM agent admin bằng tiếng Việt tự nhiên → tạo nhân sự ảo, bật/tắt, hỏi trạng thái/chi phí đội. Phạm vi M14a (chủ dự án chốt): engine + đường DM Telegram trước; web chat box React + dashboard Việt hóa để M14b.

## Làm gì
- **Ops engine = M12 áp vào mặt phẳng QUẢN TRỊ** (`ops_chat.py` + `ops_catalog.py`): LLM chỉ CLASSIFY (lệnh nào) + EXTRACT (1 giá trị slot); CODE chạy catalog. Catalog CORE-fixed (không pack đóng góp — quản trị fleet là việc nền tảng), KHÔNG có lệnh xóa agent → injection "xóa hết agent" không có entry. 4 lệnh: create_agent (slot-filling), set_enabled, get_status, get_cost.
- **Multi-turn state machine** (khác M12 single-turn): conversation store SQLite (`ops_conversation_store.py`, 1 draft/operator, TTL 1800s) → 3 pha: collecting slot → awaiting_confirm → run. Draft clear TRƯỚC run (chống double-run khi re-poll).
- **Confirm 2 bước thay Lớp B**: admin config-writes (tạo agent/registry) KHÔNG qua Action Gateway (quyết định M7 — không phải external mutation); thay vào đó mọi write bắt buộc preview đầy đủ + xác nhận rõ ràng. `create_agent` gọi ĐÚNG primitive wizard M7 (`agent_create.create_agent`).
- **Operator gate** (`qa_answer._is_ops_operator`): chỉ user id = `telegram.ops_operator_id` trên agent domain=admin qua Telegram mới chạm ops engine; check trên `mention['user']` bất biến, không trên text → "tôi là operator" vô hiệu. Người khác/agent non-admin/transport khác → M11/M12 path byte-identical.

## Review (DONE_WITH_CONCERNS, 0 CRITICAL/HIGH — mọi bất biến bảo mật verify + test-proven) → vá 2 MEDIUM
- **Domain choices hardcode** pm/hr/admin không theo pack mới → thêm guard test (`discover_domains() ⊆ choices`, đỏ nếu thêm pack mà quên map alias).
- **Confirm exact-match** loại "ok tạo đi" → nới thành word-membership (`_confirm_decision`): confirm word ở bất kỳ đâu → confirm; cancel word ở bất kỳ đâu → cancel (thắng, fail-safe: "không, tạo đi" = cancel, CEO gõ lại); không rõ → unclear = hủy (không bao giờ write nhầm).

## E2E LIVE — CEO tạo nhân sự ảo 100% qua hội thoại (bắt 3 bug UX thật)
DM admin bot tiếng Việt: "đội mình mấy agent, tốn bao nhiêu?" → liệt kê 3 agent + chi phí (data fleet thật). "Tạo agent mã sales-pm, vai trò quản lý dự án" → bot hỏi báo cáo → **gõ `DAILY]` (hoa + ký tự thừa)** → engine chuẩn hóa `daily` → preview → **`XÁC NHẬN`** → **agent `sales-pm` tạo thật** (profile + registry, load chạy được).
- **E2E bắt 3 bug UX** đối thoại người dùng "bẩn" hơn test tưởng: (1) LLM extract "quản lý dự án" nguyên văn → thêm `choices` map alias VN→mã (pm/hr/admin); (2) id/reports chữ hoa bị pack từ chối → thêm `lower` normalize; (3) giá trị lạ → validate reject + hỏi lại. Vá + thêm test cho cả 3.

## Verified
998 pytest (27 mới) + ruff clean. Test chứng minh: operator gate (6 tổ hợp), confirm không double-run khi re-poll, stale draft bỏ, xác nhận không rõ → hủy, normalize VN→mã, guard domain-choices.

## Bài học
- **E2E thật là bộ test UX không thể thay thế**: 3 bug chuẩn hóa slot chỉ lộ khi người thật gõ "quản lý dự án" / "DAILY]" — không unit test nào tưởng tượng ra "gõ dư dấu ]". Đối thoại người dùng luôn bẩn hơn fixture.
- **Confirm phải fail-safe hai chiều**: exact-match quá chặt (mất confirm hợp lệ → khó chịu), quá lỏng thì write nhầm. Chọn: cancel word THẮNG confirm word, không rõ = hủy → không bao giờ write ngoài ý muốn, chỉ tốn CEO gõ lại.
- **Tách read-only khỏi write ở catalog**: get_status/get_cost chạy ngay không confirm (không write); create/set_enabled bắt buộc preview+confirm. `readonly` flag giữ ranh giới rõ.

## Unresolved / defer
1. M14b: web chat box React (SSE sẵn từ P6) + dashboard "Đội của bạn" tiếng Việt.
2. Confirm word-membership trong pha COLLECTING vẫn exact (an toàn hơn — "không" lúc thu slot có thể là giá trị); chỉ nới ở pha confirm.
3. Duyệt approval qua chat (CEO "duyệt #5") vẫn NGOÀI v6 (trust ladder — quyết định chủ dự án).
