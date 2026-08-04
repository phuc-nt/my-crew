# v65 — Nhắc-việc-theo-giờ + đóng đuôi treo (round-robin, approval read scope)
2026-08-04 · hoàn thành

## Làm gì

- **Nhắc hẹn giờ một lần** (CEO duyệt cùng ngày): lệnh M12 `set_reminder`/`cancel_reminder`
  (personal-pack) → native type `reminder_create`/`reminder_cancel` (nhánh Lớp A riêng:
  secret-scan, text ≤500, due_at RFC3339-kèm-offset; actor-bound — không agent nào ghi
  được store của agent khác) → `reminders.db` per-agent → pseudo-kind `reminder-sweep`
  mỗi phút CHỈ mọc khi còn nhắc pending (probe không tạo file) → no-LLM đọc-hàng-đến-hạn
  → `telegram_send` dedup `reminder:{id}` → mark sent (deny giữ pending, thử lại tick sau).
  Snapshot thư ký thêm `upcoming_reminders` (#id · giờ · nội dung) để hỏi/huỷ theo id.
- Đuôi v64 đóng trước đó cùng chiều: **round-robin stateless** (task hoạt-động-cũ-nhất
  trước — max spawned_at/last_seen, task chưa chạy = "" luôn đứng đầu, nuốt rule
  chống-đói; test pin 2 task bận luân phiên) + **`_approval_status` scope theo
  assigned_to** như write-path (id per-FILE AUTOINCREMENT, đọc chéo store trúng nhầm hàng).
- Suite 2518 BE (+12 so v64); UAT sống end-to-end: "đặt nhắc lúc 15:51..." qua bot →
  tin "⏰ Nhắc hẹn" về Telegram CEO 15:59 (trễ do 2 vấp dưới), row `sent`.

## Quyết định & vì sao

| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Reminder là năng lực CORE generic, pack chỉ sở hữu lệnh | "Gửi X lúc T qua telegram của agent" không có logic domain; giữ luật lõi-không-chứa-domain | Thêm 2 native type vào vetted set (pin test cập nhật có chủ đích) |
| Pseudo-kind mọc theo pending (probe rẻ) | Agent không có nhắc giữ schedule byte-identical, không tick thừa | `_effective_schedule` chạy mỗi tick nên nhắc mới đặt ăn ngay, không cần restart |
| `reminder-sweep` MIỄN trần spawn/tick | Trần sinh ra chặn tải LLM; kind no-LLM tức thời mà xếp hàng là đói ĐỊNH MỆNH (UAT: pending mãi sau 4 inbox/team-tick, thứ tự registry lặp y hệt mỗi phút) | Bỏ outer-break: tick đầy trần vẫn quét nốt agent sau để tìm kind miễn trần |

## Vấp & học được

- **Ops layer nuốt lệnh M12 mới**: ops-classifier của thư ký trả "unsupported" là chặn
  luôn bằng listing ops — `set_reminder` không bao giờ được hỏi tới. Fix: domain personal
  unsupported ⇒ RƠI XUYÊN xuống catalog M12 (admin giữ listing — không có M12 phía sau).
  Bài học: chồng 2 tầng classifier thì tầng trên phải có đường nhường rõ ràng.
- **Trần spawn làm đói kind đúng-giờ**: log "deferring secretary/reminder-sweep" lặp mỗi
  phút — deferral + thứ tự ổn định = starvation vĩnh viễn, không phải "chậm một nhịp".
  Đói lịch là chủ đề lặp lại trong ngày (ticker task, giờ tới service spawn) — mọi hàng
  đợi có trần cần trả lời câu "ai bị đói ĐỊNH MỆNH?".

## Mở / sang sau

- Cross-agent memory: CEO chốt SQLite-trước — cần phiên thiết kế riêng (schema, seam
  `resolve_memory_text` provider thứ 3, ranh giới đọc/ghi, red-team injection bề mặt
  trí nhớ chung) trước khi code.
