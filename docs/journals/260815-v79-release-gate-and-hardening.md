# v79 — Model 3 tầng, phanh thật cho trần chi phí, và cổng release 0.10.0
2026-08-15 · ✅ Done

## Làm gì

- **Model 3 tầng** (`7b5f917`): fleet → per-agent → per-role (`role_models` trong
  profile). Fleet mặc định chuyển sang `deepseek/deepseek-v4-pro-0813` (`573c86b`).
- **Phanh in-flight cho trần chi phí** (`e4be8f3`): chạm trần là halt các bước ĐANG
  chạy + reap sweep khi cancel — trả nợ vấp A9 của v78 ("cancel không phải phanh").
- **Harness fullflow in-process** (`eaaa978`, `2d14f14`): chạy nguyên pipeline
  intake→decompose→work→review→aggregate trong 1 tiến trình test, LLM giả có kịch
  bản; 8 kịch bản người-dùng-thật (clarify, autopilot, sprint...), mutation-verified.
  Hướng dẫn ở `docs/fullflow-testing-guide.md`.
- **Chuỗi fix chất lượng giao việc**: bản giao terminal đưa NGUYÊN VĂN không cắt
  500 ký tự (`44f21ec`, `56e2457`); review truy số liệu về đầu vào của bước thay vì
  chấm mù (`60706e1`); hết flood Telegram sau hoàn thành (`59a4ffa`); verdict đạt
  trả nguyên bản trước đó, không dính appendix lỗi (`771b51b`); rework thừa kế
  quyền web của bước nó làm lại (`a5d7c93`).
- **Cổng release 0.10.0**: delta-UAT sống 4/4 hành vi trên model + Telegram thật
  (`plans/reports/uat-260815-1205-delta-v79-release-gate-report.md`), 2 phát hiện
  cosmetic sửa xong trước khi phát hành (`c9ff1a7` sprint tool-less bỏ máy search,
  `46c6234` tiêu chí độ tươi dữ liệu) rồi re-verify sống lần nữa — bản giao sạch.

## Quyết định & vì sao

| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| Trần chi phí chặn lúc mint + halt in-flight, không trông vào cancel | A9 (v78) đo được: cancel xong vẫn cháy thêm ~$0.05 vì worker đã spawn chạy nốt | Bước bị halt giữa chừng mất công đã chạy |
| Sửa 2 phát hiện cosmetic TRƯỚC release thay vì ship kèm known-issue | CEO chọn "cải thiện xong mới release"; cả 2 đều chạm mặt người dùng (boilerplate PHẦN THIẾU, số liệu 7/2024 cho câu hỏi 2026) | Release chậm ~1 ngày |
| `needs_web=False` gạt TOÀN BỘ máy search sprint, không chỉ ẩn note | Thank-you note vẫn chạy prefetch định-sẵn-thất-bại rồi ship disclaimer về việc tra cứu nó không hề cần | Bước intake đoán sai needs_web sẽ không có coverage round |
| Tiêu chí độ tươi không được loại số cũ khi không có nguồn mới hơn | Đòi hỏi chặt hơn khả năng của snippet search là tái diễn vấp v77 "trượt vĩnh viễn qua mọi vòng soát" | Số cũ vẫn qua được review, chỉ bị bắt ghi chú thời điểm |

## Vấp & học được

- **Venv mang shebang của repo đã đổi tên**: `uv run pytest` chết 86 collection error
  trong khi `uv run python` import mọi thứ bình thường — entry-point scripts còn trỏ
  `my-project-manager/.venv`. `uv sync --all-extras --reinstall` viết lại toàn bộ.
  Học: đổi tên thư mục repo thì venv phải rebuild, và "python import được nhưng
  pytest không" là chữ ký của shebang cũ, không phải thiếu package.
- **Milestone-mirror "no_new_milestones" không có nghĩa là chưa gửi**: coordinator
  fast-path gửi thẳng chat CEO lúc aggregate rồi cắm cờ `delivered_direct=1`; mirror
  bỏ qua đúng thiết kế. Suýt kết luận nhầm "delivery hỏng" khi audit log.

## Mở / sang sau

- Nợ v76 còn treo: ca sống trusted×external_write (chờ lần cấp `team_step_egress`
  đầu tiên, luật thường trực đã ghi).
- Hướng cấp thêm lượt tra cứu cho sprint (trả lời C3) đã duyệt, chưa triển khai.
