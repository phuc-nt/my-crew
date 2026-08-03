# v57 — Thư ký riêng CEO trên Telegram (personal-pack)
2026-08-03 · ✅ 4/5 phase (P4 web-search chờ API key) · **Plan:** `plans/260803-1816-personal-secretary-agent/` · **Suite:** 2418 BE + 280 FE + 8 e2e · 6 commit trên main

## Làm gì

- **Domain pack thứ 5 `personal`** — thư ký riêng của chủ máy, tham chiếu năng lực agent
  Pong (openclaw): chat DM tức thì, Morning Briefing 7:00 + Weekly Review CN 8:00 (2 report
  kind pack tự sở hữu — không sửa core scheduler), đọc Gmail/Calendar qua CLI `gws` (OAuth
  sẵn của CLI), lệnh ghi `tao_lich` (catalog `gws_write`, argv cố định), daily-notes memory.
- **Telegram listener** (`runtime/telegram_listener.py`): thread long-poll peek 45s per
  telegram agent → có tin spawn đúng worker inbox subprocess. Trả lời ~1-2s thay vì chờ tick
  phút; tick lịch giữ làm fallback; rate-cap 6 run/60s chống flood đốt LLM.
- **Chat có trí nhớ** (`agent/chat_memory.py` + `memory/daily_notes.py`): trước v57 đường
  chat quên sạch sau mỗi reply. Giờ: reply gửi xong → trích fact (prompt "đáng nhớ" riêng
  cho thư ký) → `profiles/<id>/memory/YYYY-MM-DD.md` + mirror MEMORY.md; context nạp 7 ngày
  gần nhất (cap 4K/ngày + 8K tổng). Opt-in `memory.daily_notes` — agent khác byte-identical.

## Quyết định & vì sao

| Quyết định | Vì sao | Trade-off |
|---|---|---|
| "Full-ga trong khung": autonomous + dry_run off, GIỮ Lớp A | CEO muốn không hạn chế; Lớp A chỉ chặn 3 thứ thư ký không bao giờ cần hợp lệ | Không có host-exec/browser kiểu openclaw |
| Pack sở hữu kind `briefing` ngay P1 | Chat M11 bắt buộc ground qua `pack.tools.read(kind)`; sẵn kind thì P2 chỉ còn cron | — |
| Listener peek-then-spawn, không xử lý trong thread | Giữ bất biến LLM-trong-worker-subprocess + tái dùng nguyên pipeline inbox đã test | 1 lần getUpdates thừa mỗi batch |
| Bỏ tool `memory.search` | Chat M11 không có tool-loop — tool chỉ phục vụ team-step; cửa sổ 7 ngày đã phủ "tuần trước dặn gì" | Tra note >7 ngày phải chờ pain signal |
| Email KHÔNG vào catalog chat | v31 P2 cấm `email_send` trong vetted-types by design — nới là quyết định an ninh riêng | Thư ký chưa gửi mail được |

## Vấp & học được

- **`{} or None` hồi sinh allowlist mặc định**: copy dòng gateway từ hr-pack (allowlist
  non-empty nên `or None` vô hại) vào pack allowlist-rỗng-có-chủ-đích → default-DENY thành
  allowlist rộng. Office-pack đã cảnh báo đúng bẫy này trong comment. Reviewer bắt; sửa cả
  cùng-bẫy ở `qa_answer.py`.
- **Phantom coverage lần 2**: argv `calendar events insert` của chat-ops v39 thiếu path-param
  `calendarId` — chưa từng chạy nổi với Google thật, test vẫn xanh vì pin đúng argv hỏng.
  UAT thật mới lộ (thêm lỗi handler chỉ đọc stderr, noise keyring che JSON lỗi ở stdout).
- **Classifier thiếu mốc thời gian** → "9h sáng mai" bịa ngày; chèn `BÂY GIỜ:` vào prompt
  phân loại. Và classifier tạo lịch quá tay ("nhắc anh…" → sự kiện thật) → siết description.
- **Prompt cấm ≠ đảm bảo**: markdown `**` vẫn lọt ra Telegram dù qa-system cấm → strip cấu
  trúc trong `sanitize_reply` (bài học sanitize cũ lặp lại: hope-level → guarantee).

## Mở / sang sau

- P4 web-search: chỉ chờ `TAVILY_API_KEY`/`BRAVE_API_KEY` vào .env rồi bật cờ.
- Thư ký chưa biết roster crew (gợi ý giao việc nói chung chung) — cần capability block chứa
  danh sách staff; gửi email từ chat = quyết định nới vetted-types riêng nếu CEO cần.
- Xác nhận briefing 7:00 sáng 04/08 tự đến (điểm mở cuối của P2).
