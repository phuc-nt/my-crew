# Crew tự quyết khi kẹt, luôn kết luận
2026-09-02 · ✅ Done · bench 8/8 delivered, 0 stalled không kết luận

## Làm gì

- **Mọi đường stall đều kết luận.** Dead-end, vỡ cost cap, lệch plan hash trước đây để task
  `stalled` không có `final_summary`, phòng họp không nhận gì; nay đường nào cũng ghi kết luận
  và chạy deliver (commit `1895ca5`).
- **Coordinator có nấc "tự làm".** Khi step chết ở cap can thiệp (2 lần), coordinator tự làm
  thay nếu là bước cuối (`coordinator_fallback` trên artifact, header trong deliverable) hoặc
  bỏ qua kèm ghi lỗ hổng nếu là bước giữa; chỉ khi cả hai không được mới `conclude_task_failed`.
- **Rework có chốt chặn không tiến bộ**: vòng rework không giảm số lỗi thì dừng, giao kèm cờ,
  không đốt nốt ngân sách.
- **Judge kẹt thêm ruling `accept`** và được đọc **toàn văn yêu cầu CEO** (2000 ký tự) thay vì
  chỉ title 120 ký tự — `stuck_decision.py`, `stuck_judgement_prompt.py`.
- Bench: 5 case team lanes16 rồi rerun 3 case lanes17; suite BE exit 0, ruff sạch. Báo cáo
  `plans/reports/bench-260902-0703-crew-self-decide-always-conclude-report.md`.

## Quyết định & vì sao

| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| Tự làm chỉ ở cap can thiệp, không sớm hơn | Người được giao có 2 cơ hội với guidance; tự làm sớm là cướp việc và mất dấu ai chịu trách nhiệm | meeting_notes tốn 306s trước khi tự làm |
| Thêm `accept` thay vì nới tiêu chí tự chấm | lanes16 cho thấy artifact tốt bị viết lại vì tự chấm sai; judge đọc lại rẻ hơn một attempt | Thêm một ruling cần test + prompt |
| Đưa full request vào brief judge | Lỗi "brief bị cắt ngọn" ở matrix_canary do judge chỉ thấy 120 ký tự title | Brief dài hơn ~2k ký tự mỗi lần kẹt |
| Escalation self-do vẫn báo CEO qua operator notice | CEO phải biết người được giao không hoàn thành, không chỉ thấy bài nộp | Bench extractor không đếm được (outbox in-memory) |

## Vấp & học được

- **Sửa xong stall lại lộ churn.** Hết stall thì thấy coordinator viết lại một bài đã đạt — gate
  "không kẹt" chưa nói gì về "không lãng phí". Phải đọc deliverable bằng tay mới thấy.
- **Judge sai vì thiếu ngữ cảnh, không phải vì prompt yếu.** Đọc log mới thấy brief chỉ chứa
  title 120 ký tự; thêm request là hết, không cần chỉnh lời prompt.
- **Wall dao động lớn cùng code** (149s ↔ 306s): n=1 mỗi run, mọi con số ở đây là hướng.

## Mở / sang sau

- Cap can thiệp 2 → 1 cho bước terminal khi có `self_do_step`? Chưa quyết, cần thêm mẫu.
- Aggregate cắt bước giữa 500 ký tự làm deliverable 2-step ngắn — thiết kế cũ, xem lại sau.
