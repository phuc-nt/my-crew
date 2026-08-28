# Vòng can thiệp hội tụ + giao kèm phần đã làm khi bỏ cuộc
2026-08-27 · ✅ Done · chưa release-ready

## Làm gì
- Judge kẹt giờ THẤY guidance đã ra ở các lần can thiệp trước: `build_stuck_brief`
  thêm mục "Chỉ dẫn ĐÃ RA ở (các) lần can thiệp trước" + QUY TẮC HỘI TỤ trong
  `stuck_judgement_prompt.py` (không lặp chỉ dẫn thất bại — chỉ còn hạ chuẩn /
  reassign / give_up) + cấm chữ-thành-chữ leo thang "tên trang → URL".
- `_give_up` giao kèm phần đã làm: quét bước done có `result_text` ≥400c (seq lớn
  nhất), nối sau câu bỏ cuộc, cap 6000c cắt ở ranh giới dòng (`stuck_decision.py`).
- Trần cho 2 kẻ nâng chuẩn còn lại: decompose cấm liệt kê thực-thể-có-tên-riêng
  từ trí nhớ model + cấm "ít nhất N" khi CEO không nêu N; bước THẨM ĐỊNH chấm đúng
  đề gốc, không tự đặt chuẩn mới (`team_task_prompt.py`).
- Bench lanes7 (2 brief × 2 lane, TICKS=60) + đo hội tụ guidance bằng similarity
  chunk-mới giữa các work-order liên tiếp (char SequenceMatcher + token Jaccard).

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Đo hội tụ trên work-order JSON per-attempt, không phải cột `guidance` DB | Guidance tích lũy nhiều dòng; tách chunk mới bằng prefix-removal mới đo đúng "lần này nói gì mới" | Phụ thuộc format prefix "Bối cảnh:" của work-order |
| Salvage vẫn bị `judge_lanes.py` lọc qua `_ABANDON_MARKS` | Salvage không phải deliverable đạt — nó cứu dữ liệu cho CEO, không cứu điểm bench | Số case "giao được" không tăng dù CEO nhận nhiều hơn |
| Không vá nóng finding mới trong phase bench | Risk note phase 4: stall vì lớp mới thì ghi finding, giữ bench là bench | Tên→URL vẫn lọt 1 lần trong lanes7 |

## Vấp & học được
- Đo similarity toàn bộ cột guidance (split newline) ra 6 "chunk" ảo từ 2 lần can
  thiệp — phải quay về work-order per-attempt. Char-similarity cũng mù lặp ngữ
  nghĩa (2 lệnh cùng đòi URL, char=0.09) → thêm token-Jaccard + đọc tay.
- Judge hết lặp nguyên văn thì lộ kiểu leo thang mới: tự chốt danh sách 5 domain
  thành nguồn BẮT BUỘC rồi đánh trượt worker dùng nguồn hợp lệ khác — luật chống
  chỉ định nguồn "uy tín" chưa phủ danh-sách-đóng từ chính kết quả của worker.
- Music stall không còn vì vòng lặp: acceptance đòi MAU/thị phần VN mà web tiếng
  Việt không công khai — lớp "tiêu chí bất khả thi với dữ liệu tồn tại".

## Mở / sang sau
- Câu hỏi gốc v2 (lane nhanh có kém hơn?) vẫn chưa chấm được: 5 vòng bench chưa
  từng có cặp deliverable cả 2 lane cùng giao.
- ~~Ứng viên vá tiếp~~ ĐÃ VÁ 28/08 (`39cf188`): cấm judge chốt danh-sách-nguồn-đóng
  + QUY TẮC SỐ ĐO ĐỊNH LƯỢNG cho decompose. Lanes8 xác nhận cả hai giữ được:
  0 danh sách đóng, acceptance 4/4 case mang escape hatch "nếu nguồn công bố /
  ghi rõ không công khai"; tên→URL dịu thành có lối thoát "Link: [tên miền]".
- Nút thắt còn lại lanes8: worker snippet-only không gom nổi nguồn kiểm chứng
  được cho đề thị trường VN trong 2 lần can thiệp — trần năng lực tra cứu,
  không phải lỗi prompt.
- ~~Task chết một bước là stall trắng tay~~ ĐÃ VÁ 28/08: degrade-and-continue
  (skip-with-gap `fc6ebf4`) + fix vòng review đè bước đã drop (`213f119`,
  `ee57ce3`) — chi tiết ở entry 260828-degrade-and-continue-review-drop-guard.
