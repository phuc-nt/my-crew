# v61 — Thư ký = điều phối viên (ops orchestration) + backend English
2026-08-04 · hoàn thành

## Làm gì

- Mở tầng ops-chat cho thư ký: `handle_ops_message` nhận catalog theo domain
  (`catalog_for_domain`) — admin giữ full (byte-identical), personal được đúng 12 lệnh
  ĐIỀU PHỐI (assign/adjust/list/cancel + việc định kỳ + send_message + 4 readonly),
  không bao giờ thấy `create_agent`/`set_enabled`. Gate operator giữ nguyên độ chặt
  (một user id, Telegram DM).
- Backend 100% English: id lệnh personal-pack → `create_event`/`update_event`/
  `delete_event`/`send_email`, arg `luc`→`at`; slot ops `yêu cầu`→`request` (đã nằm
  sẵn trong catalog từ trước, quét ra khi rà chuẩn). Reply/description giữ tiếng Việt.
- Gỡ `assign_task`/`move_task` M12 (v60, mới 1 ngày tuổi): ops assign_team_task
  vượt trội (DAG nhiều agent + confirm + list/cancel) — một bề mặt giao việc duy nhất.
- UAT thật qua bot thư ký: brief phức tạp → decompose DAG 4 bước/3 agent (retry tự
  sửa PIC-rule) → "xác nhận" → ticker dispatch → **15 bước chạy thật** (4 kế hoạch +
  11 soát chéo/rework tự đẻ, 4 agent tham gia: nghien-cuu, noi-dung, kiem-dinh, hr),
  handoff giữa agent hoạt động, sản phẩm thật trong artifacts. Nháp thứ hai hủy sạch
  ở confirm; admin path xác minh không đổi. Tổng chi phí task ~$0.023.

## Quyết định & vì sao

| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Mở tầng ops thay vì xây lệnh giao việc riêng | Dàn nhạc multi-agent (decompose/confirm/tick/review/escalate) đã có đủ và đã red-team nhiều vòng | Thư ký + admin giờ chung engine — catalog subset phải pin bằng test |
| Gỡ giao_viec/chuyen_the sau 1 ngày | Hai bề mặt cho một ý định làm classifier lẫn; giữ cái mạnh hơn | Đảo quyết định v60 — chấp nhận có chủ đích theo directive mới |
| Catalog theo domain, không theo cờ profile | Domain là trục quyền hạn sẵn có của hệ (pack, ops gate) | Domain mới muốn ops phải sửa code (đúng ý — quyền không phải config) |

## Vấp & học được

- UAT lộ calibration: task đồ chơi 4 bước bị soát chéo đẻ thêm 11 bước, bước tổng hợp
  cuối trượt review hết vòng → task `stalled` (escalation `review_rounds_exhausted`
  vào room, mirror DM CEO). Máy chạy ĐÚNG thiết kế human-gate, nhưng bar review cho
  việc nhỏ đang đắt — ghi roadmap cân chỉnh.
- Chuẩn "backend English" phải quét bằng máy: slot `yêu cầu` sống trong catalog từ
  nhiều version mà không ai thấy; đổi id xong grep toàn repo = 0 mới tin.
- `list_tasks` (M15 việc định kỳ) và thẻ việc đội trùng chữ "việc" trong tiếng Việt —
  classifier dễ trộn; mô tả lệnh là chỗ phải phân biệt rõ.

## Mở / sang sau

- Cân chỉnh review cho task nhỏ (số vòng/điều kiện chèn soát chéo theo cỡ việc).
- Task UAT `9ee8a4f028f0` đang `stalled` chờ CEO xử (sản phẩm đã có trong artifacts).
- Backlog giữ nguyên: Postgres cross-agent memory; nhắc-việc-theo-giờ.
