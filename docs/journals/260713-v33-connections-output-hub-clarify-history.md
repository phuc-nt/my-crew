# v33 — Màn Kết nối, design-system pass, hub Kết quả, clarify buttons, tìm lịch sử
2026-07-13 · ✅ Done (P1-P5 một phiên cook, E2E thật per phase; suite 2032→2066 BE + 186→200 FE)

## Làm gì
- **Màn Kết nối** (`/connections`): UI của `.env` theo catalog CỐ ĐỊNH — card per-connection (status sống từ `integration_health` + presence key, không bao giờ lộ value) + form ghi qua đúng `merge_env`/whitelist cũ + nút Restart nói thật (launchd vs chạy tay, `_restart_web_service` giờ trả bool).
- **Design-system pass**: 30 → 2 font-size hard-code trong App.css (token `--fs-*` + thêm `--fs-2xs`); office header 1 hàng + hint gập `<details>` + 3 zone title thống nhất; media query màn thấp (3D 30vh, feed 30vh, rooms 34vh) → **1280×800 thấy đủ 3D + phòng + feed + kết quả + composer**.
- **Hub "Kết quả"** (`/outputs`, nav mới): index cross-task mọi step artifact done + file xuất (artifact dir), lọc agent/ngày theo ts của item, viewer MD tái dùng, download path-confined symlink-safe; kèm **kanban team-task read-only** trong Duyệt (lane theo status store, card → phòng việc).
- **Clarify buttons**: agent hỏi CEO qua target `"ceo"` trong propose-consult (options đi kèm) → `clarify_store` (first-answer-wins, cap 3 pending/agent, expire 48h trong ticker) → Telegram DM qua bot admin ops (gateway, inline_keyboard) + section "Đội đang hỏi bạn" trong Duyệt; câu trả lời inject vào handoff bước SAU (`answered_context_for_task`). E2E thật: câu hỏi lên Telegram CEO + web answer + 409 double.
- **Tìm lịch sử** (`history.search` + ops chat `search_history`): FTS5 disposable side-DB index step artifacts + audit JSONL (watermark + dedup `indexed_refs`), query escape, kết quả có trích nguồn; E2E data thật trả 6 hit đúng task cũ.

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Clarify notify qua bot ADMIN ops (không per-agent bot) | 1 bot 1 chat CEO, gateway + audit sẵn (M21); line agent không cần telegram config | Mọi câu hỏi dồn 1 kênh — chấp nhận, đúng vai "hỏi sếp" |
| v33 clarify = fire-and-forget (không dừng graph) | Không đụng step-status enum/checkpointer; v34 nâng lên `interrupt()` trên CÙNG store (`resume_token` chừa sẵn) | Bước đang chạy phải tự đi phương án an toàn |
| `answerCallbackQuery` gọi Bot API thẳng (không qua gateway) | Pure UI-ack (tắt spinner), không publish nội dung — cùng tier getUpdates read-ack; reviewer đồng ý carve-out | Ghi rõ docstring để không thành tiền lệ |
| `history.search` luôn bật, internal-only | Read nội bộ không key; external audience bị strip qua `_INTERNAL_ONLY_READS` | Đổi contract `build_read_toolset` (3 test cập nhật chủ đích) |
| gws WRITE cắt khỏi plan | Grep code: đã ship v31 (`gws_write.py` + allowlist registry) — brainstorm đề xuất thừa | — |

## Vấp & học được
- **Review HIGH bắt đúng lỗ hổng thật**: value chứa `\n` ghi qua `merge_env` sẽ append dòng `KEY=...` thứ hai → lách whitelist (vd WEB_AUTH_PASSWORD_HASH). Lỗi có từ wizard v7 nhưng màn Connections mở rộng exposure — vá tại `merge_env` (từ chối control char) + red test. Bài học: chốt whitelist phải soi cả VALUE, không chỉ key name.
- Callback Telegram ban đầu chỉ check chat allowlist — reviewer chỉ ra group chat thì ai bấm cũng được → thêm identity gate (ops_operator_id / DM chat==user).
- `fetch_new_messages` đổi thành wrapper của `fetch_new_updates` (callback_query) — giữ back-compat cho 7 chỗ test stub, chỉ inbox dùng hàm mới.
- Sweep FTS5 2 process đua nhau (ticker + search) → dedup bằng bảng PK `indexed_refs`, không dựa watermark; audit re-parse cả file mỗi sweep → tripwire log >5s, tối ưu byte-offset để backlog.

## Mở / sang sau
- CEO bấm thử nút Telegram (mã #1 đang chờ trên máy) khi chạy service daemon (`uv run python -m src.runtime.service`) — tap được xử lý ở inbox poll của admin.
- Backlog: byte-offset cho audit sweep (khi audit.jsonl lớn); `kind=` filter cho /outputs; v34 (plan sẵn: checkpointer + interrupt + follow-up + fan-out + criteria review) `blockedBy` v33 — sẵn sàng cook.
