# QA rescue ô không công khai + tín hiệu material_transform cho router
2026-08-30 · ✅ Done

## Làm gì
- Vá 4 tầng prompt để ô ghi trung thực "không công khai" kèm nguồn đã tra được
  chấm ĐẠT thay vì chết chuỗi: `NONPUBLIC_RULE` chung trong
  `my_crew/llm/grading_rules.py` (tự lan sang self_check + peer review), quy tắc
  worker + escape-hatch decompose trong `team_task_prompt.py`, quy tắc "không
  phải bế tắc" cho stuck judge trong `stuck_judgement_prompt.py`.
- Bench lanes12: 3 đề dò trục mới (quyết định số cấp sẵn / kế hoạch ngân sách /
  phê bình + viết lại nháp) + matrix_canary, chạy cả 2 lane, judge mù 3 phiếu/case.
- Tổng hợp 11 case đã chấm (lanes9-12) thành chữ ký "đề hợp team"; thêm tín hiệu
  `material_transform` vào `route_signals` (sprint_intake.py) — CHỈ ĐO, chưa đổi
  lane, theo tiền lệ effort_high.
- Test ghim: rule có mặt đủ 4 tầng (`test_grading_rules_shared.py`), tín hiệu chỉ
  bật đúng bộ ba hint và không đổi lane (`test_sprint_router.py`).

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Rule dùng chung 1 chỗ trong grading_rules thay vì sửa từng prompt chấm | 2 tầng chấm (self_check, peer) join cùng EVIDENCE_RULES — sửa 1 lần, test ghim 1 lần | Câu chữ phải đủ tổng quát cho cả 2 ngữ cảnh |
| material_transform chỉ ghi số, chưa được đổi lane | n=3 (2 thắng / 1 thua), sprint-default đang rẻ hơn 2-4×; đo route thật trước khi trao quyền | Router chưa hưởng lợi ngay từ phát hiện này |
| Judge mù A/B thay vì tự chấm | Tự chấm bài mình sinh ra là xung đột lợi ích; 3 phiếu đảo thứ tự khử lệch vị trí | Thêm ~$0.01/case + phụ thuộc model ngoài |

## Vấp & học được
- Kỳ vọng "team thắng đề nhiều phần" SAI hoàn toàn: team thua MỌI đề lắp ráp
  (launch kit, 4 phần, lưới N×M) vì tầng tổng hợp làm mỏng 2-4×. Chữ ký thắng
  thật: chất liệu cấp sẵn + phân tích→sản phẩm 2 tầng + bước cuối tự viết trọn
  deliverable gọn (draft_critique team thắng 3-0, còn rẻ + nhanh hơn sprint).
- QA rescue cứu được lane sprint (matrix 0/2 → bảng 3×3 đủ, ô thiếu ghi nguồn)
  nhưng KHÔNG cứu team: decompose tách "thu thập dữ liệu X" thành bước riêng →
  bước chỉ-thu-thập vẫn trượt rồi skip-with-gap, tầng ghép nhận 0 dữ liệu.
  Họ lỗi mid-chain step death, không phải họ give_up nữa.
- 2 test pin `set(signals)` nổ khi thêm key mới — đúng thiết kế của pin, sửa pin
  chứ không sửa tín hiệu.

## Mở / sang sau
- Mid-chain step death (bước no-web chết sau 2 can thiệp → skip) giờ là nguồn thua
  số 1 của team — họ gap-cascade, đã hoãn có chủ đích.
- Ngưỡng trao quyền cho material_transform: cần đủ mẫu route thật tín hiệu=1 kèm
  outcome trước khi cho đổi lane.
