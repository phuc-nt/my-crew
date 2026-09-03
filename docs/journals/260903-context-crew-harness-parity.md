# Context-crew ngang chuẩn harness: brief, nguồn, kết cục thất bại, hiệu chuẩn bộ chấm
2026-09-03 · ✅ Done · plan `plans/260903-1034-context-crew-harness-parity/`

## Làm gì
- Brief giao việc cho worker (`step_delegation_brief.py`): rubric nghiệm thu nguyên văn + tiêu đề
  các bước anh em (tối đa 6, bỏ review/bước hệ thống), vào cả prompt làm lẫn prompt sửa.
- Nguồn đi theo artifact: `ArtifactContract.upstream_sources` — dep có N link mà bước
  `draft`/`final` không còn link nào ⇒ gap bằng code trước khi LLM chấm.
- Hợp đồng kết cục thất bại (`task_failure_mode.py`): 5 mode, nhóm MAST spec/verification/system;
  `_escalate` đóng dấu một lần lên route; `route_stats` thêm mục "Kết cục thất bại".
- H4 `verdict_calibration`: bộ chấm phải vừa ít báo động giả (≤0.25 trên artifact đúng) vừa bắt
  lỗi (≥0.5), mỗi vế sàn mẫu 12; bench 72 lượt chấm trên Haiku.
- Sửa lỗi thật gate code: "cộng đúng 90 triệu" bị đọc thành "≥90 mục".
- Sửa lỗi thật fallback điều phối: trên plan `do_review`, `self_do_step` xoá cờ soát → task đóng
  "sau soát chéo" mà không ai đọc; nay `keeps_planned_review` dùng chung cho cả judge-accept.

## Quyết định & vì sao
| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| Mode thất bại ghi lên route, không bảng riêng | `route_stats` đã đọc route; "lane nào kết thúc thế nào" là một câu hỏi | Chỉ mode đầu tiên được ghi; `source` không đụng |
| H4 hai vế, sàn mẫu riêng từng vế | Bộ chấm "luôn trượt" qua H2, "luôn đạt" qua vế báo động giả — cần cả hai | 24 lượt chấm/bộ chấm mới đủ sàn |
| Không chỉnh prompt bộ chấm dù sát vạch | 6 báo động giả cùng một dòng rubric mập mờ → lỗi ở đề, không ở bộ chấm | Verdict keep mỏng: thêm 1 báo động giả là kill |
| Stub LLM bỏ khối "việc của bước khác" khi khớp rule | Rule khớp theo tiêu đề; brief mới in tiêu đề mọi bước vào mọi prompt | Stub biết một header của product |

## Vấp & học được
- Brief mới làm 5 fullflow đỏ: rule của bước 1 trả lời bước 2 vì tiêu đề bước 1 xuất hiện trong
  khối phạm vi của bước 2 → bước 2 nộp bản ngắn, trượt contract, điều phối tự làm thay. Sửa ở
  stub (khớp ngoài khối phạm vi), không nới assertion.
- Gate code chạy trước LLM nên một regex lệch = artifact đúng đi rework; bench hiệu chuẩn có
  hàng "clean" mới lộ ra — H2 chỉ đo artifact có lỗi thì không bao giờ thấy.
- Bộ chấm LLM không làm số học: tổng cột 95 dưới dòng "Tổng 90tr" lọt 0/3 ở cả hai bộ chấm.
- Live S2 lượt chạy lại: Haiku gộp "viết; soát chéo; hoàn thiện" vào MỘT bước, worker bỏ cuộc,
  điều phối tự viết và cờ soát rơi — cùng lỗi đã vá ở nhánh judge-accept nhưng chưa vá ở nhánh
  self-do. Quy tắc chỉ vá một nhánh thì nhánh kia sẽ lộ ở lần live sau.

## Mở / sang sau
- Quy tắc cộng cột cho gate code; rubric writer phải nói rõ cọc/ngân sách bound cái gì.
- Chạy lại H4 với 24 mẫu clean để thu hẹp Wilson (0.09–0.53 hiện tại).
- Live: lượt đầu 63/66 + 8/8; ba ca đỏ (L2 plan không có dep, A3/A4 lỗi stream provider, A8
  planner quên `needs_web`) chạy lại xanh 4/4 → biến thiên model/provider. S2 đỏ ở lượt chạy
  lại lộ lỗi self-do ở trên, vá xong chạy lại xanh. Planner Haiku vẫn hay gộp 3 việc vào 1 bước.
