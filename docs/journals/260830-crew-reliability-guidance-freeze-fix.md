# Crew reliability — guidance đóng băng, bench vòng 7 ĐẬU
2026-08-30 · ✅ Done (plan `plans/260830-1026-crew-reliability-chain-signature/`)

## Làm gì
- Taxonomy bước chết vòng 6 trên transcript thật (15 verdict / 30 vòng review; false-fail
  33%, genuine_gap 67%) → nguyên nhân top: **guidance điều phối đóng băng cả attempt** —
  perceive chạy 1 lần/attempt, vòng rework 2 bị nhắc sửa đúng thứ vòng 1 vừa sửa.
- Fix (`team_task_graph._strip_guidance` + `GUIDANCE_HEADER`/`WAKE_CONTEXT_PREFIX`): chỉ
  vòng rework đầu tiêu thụ guidance; strip giữ dòng wake-context `Bối cảnh:` của rework
  soát chéo, anchor `rfind` chống header bị nội dung nhại. Test mutation-checked.
- Đo giả thuyết chữ ký routing `multi_deliverable` → **HỦY**: 0 từ vựng tách được 3 case
  thắng 3-0 khỏi 6 case thua; biến dự báo judge-win là run có sạch hay không.
- Bench vòng 7 (lanes15, re-run 4 case chết trên `91b7c88`): gate khóa trước ≥2/4 sống
  sạch → **ĐẬU 3/4** (baseline 0/4); drop 2→0, salvage 2→0, failed 3→1; cost team −60%.
  Judge mù: 2 case lật 0-3→3-0. Kiểm chứng routing thật: đúng 7/11 = luôn-chọn-sprint.

## Quyết định & vì sao
| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| Hủy P2 sau khi đo, không cố tìm chữ ký khác | 0 từ chung giữa nhóm thắng/thua — tín hiệu từ vựng là ngõ cụt; sạch mới là biến trung gian | Routing tiếp tục không có nhánh đẩy team |
| Strip guidance ở perceive thay vì re-run coordinator mỗi vòng | Rẻ (0 LLM call), đúng ngữ nghĩa "chỉ dẫn cho lần sửa kế tiếp" | Vòng rework sau mất ngữ cảnh chỉ dẫn cũ — chấp nhận, vì chính ngữ cảnh cũ là thứ gây kẹt |
| Không re-run bench trên `babcdbd` (2 fix review) | 4 case đều 0 drop/salvage nên không đi qua 2 đường vừa sửa; ghi commit-under-test vào report | Report phải mang caveat thay vì số "sạch" |
| Sửa bug bộ lọc judge nhưng KHÔNG re-roll verdict vòng 6 | Kết luận hành động (P2 hủy, gate trượt) đứng vững hoặc vững hơn dưới dữ liệu đã lọc | Tally 7-4 vòng 6 phải kèm chú thích vĩnh viễn |

## Vấp & học được
- **Bộ lọc judge vô hiệu từ đầu**: `run_judging` chấm mọi file chung tên hai thư mục,
  `goals` chỉ cấp tiêu chí — filter phía caller in "bỏ" rồi vẫn chấm; một thông báo bỏ
  cuộc 1812 ký tự "thắng 3-0". Bài học: filter phải đứng ở tầng dữ liệu (temp dir chỉ
  chứa case usable), không ở tầng tham số mà hàm không đọc.
- Cost giảm 60% NGƯỢC rủi ro dự đoán ("nới rework tăng cost") — hết đốt vòng rework vô
  ích thì cả cascade drop/salvage phía sau biến mất; reliability fix cũng là cost fix.
- 2 tín hiệu routing đang chạy đều khớp-chuỗi sai nghĩa ("đặt lịch" = rào ghi-ngoài,
  "trong tuần" = hạn chót) — giá trị ròng 0 so với luôn-chọn-sprint.
- Case meeting_notes vẫn stalled vì mơ hồ phân rã ("Rà soát và chốt biên bản" = phán
  quyết hay bản cuối?) — đúng class taxonomy dự đoán fix guidance không chạm tới;
  degrade-and-continue dừng chờ người đúng thiết kế.

## Mở / sang sau
- Rõ hóa phân rã bước review-and-finalize: tách "chốt bản cuối" khỏi "phán quyết".
- Xét lại tín hiệu `'trong tuần'`→nhiều-giai-đoạn; bộ đề ≥30 case cho routing + đo
  tương quan sạch→thắng phi-cơ-học (loại cặp có lane chết).
- Trần chất lượng team khi sạch: churn sạch vẫn thua judge 1-2 — chưa rõ vì sao.
