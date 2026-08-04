# v60 — Thư ký thành cổng điều phối + sửa/xoá lịch
2026-08-04 · hoàn thành

## Làm gì

- Thư ký giao việc cho crew qua chat: `giao_viec`/`chuyen_the` vào personal-pack —
  reuse nguyên type `team_task_create`/`team_task_move` đã vetted + handler
  actor-bound; card sinh ở `planning`, coordinator lo tiếp. Description `giao_viec`
  chèn mã đồng nghiệp từ `assignable_staff()` lúc pack load (fallback tĩnh khi
  registry vắng).
- Sửa lịch `doi_lich` (patch, giữ nguyên thời lượng cũ khi chỉ đổi giờ) + xoá lịch
  `xoa_lich`: resolver tiêu đề→eventId qua read-only `calendar_events_window`
  (gws_read có prefix `calendar events list` mới); 0/nhiều khớp ⇒ hỏi lại, arg `luc`
  (prefix ngày/giờ) phân biệt trùng tên.
- Carve-out Lớp A cho xoá: `_is_calendar_event_delete` — chỉ argv đúng 5 phần tử,
  params đúng 2 key, calendarId=primary, eventId đúng shape mới thoát vòng marker
  DATA_LOSS; security markers/secret-scan/prefix giữ nguyên. Test pin 9 biến thể xấu.
- Reply ✅ giờ nối summary của handler — mã thẻ nằm ngay trong reply để "hủy thẻ <id>"
  (classifier không có hội thoại cũ).
- UAT thật: giao nghien-cuu (card `9fd1006b6b78` by=thu-ky) → hủy qua chat; tạo→dời
  10h→14h (giữ 30')→xoá event thật; title ma → "không thấy"; 2 event trùng tên →
  hỏi lại rồi xoá đúng bằng `luc`.

## Quyết định & vì sao

| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Carve-out delete bằng shape-check cấu trúc, không nới marker | CEO cho xoá lịch nhưng marker DATA_LOSS phải giữ cho mọi thứ khác | Thêm 1 nhánh đặc-cách trong `_hard_deny_gws` phải pin kỹ |
| Resolver hỏi lại khi mơ hồ, không đoán | Sửa/xoá nhầm event tệ hơn nhiều so với một câu hỏi lại | Cần thêm arg `luc` cho vòng trả lời thứ hai |
| Duplication builder team-task giữa office/personal pack | Pack module load standalone, không import chéo pack được | ~25 dòng glue lặp, mỗi pack tự sở hữu catalog |
| Backlog Postgres (cross-agent memory) + nhắc-việc-theo-giờ ghi roadmap | CEO chốt làm sau khi thư ký hoàn thiện | — |

## Vấp & học được

- Reply ✅ chỉ in args preview nên mã thẻ (nằm trong summary handler) không tới tay
  người dùng — "hủy thẻ vừa giao" bất khả thi vì classifier không có hội thoại. Bài
  học: thiết kế lệnh có bước 2 phải hỏi "bước 2 lấy tham chiếu từ đâu?".
- UAT trùng tên lộ reply gợi ý "kèm giờ" trong khi resolver chưa lọc theo giờ —
  thông điệp hứa trước tính năng. Vá ngay bằng arg `luc` trong cùng vòng.

## Mở / sang sau

- Nhắc việc theo giờ (one-shot reminder) — chưa chốt thiết kế với CEO.
- Cross-agent memory: Postgres + `project_group` (backlog, sau hoàn thiện thư ký).
- "Hủy thẻ vừa giao" tự nhiên hơn cần classifier có ngữ cảnh hội thoại ngắn — để mở.
