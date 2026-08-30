# Step-death salvage — nháp trượt không bị vứt + luật gộp thu thập
2026-08-30 · ✅ Done

## Làm gì
- `drop_step_with_placeholder` đọc artifact TRƯỚC khi ghi đè: nháp trượt cuối (≥200c,
  cap 4000c cắt tại ranh dòng) được đính dưới marker `BẢN NHÁP CHƯA ĐẠT SOÁT` sau
  placeholder + reason line — skip-with-gap không còn vứt trắng công sức đã viết.
- Gom quy tắc khoảng trống thừa kế (lặp nguyên văn ở 2 grader) về hằng chung
  `INHERITED_GAP_RULE` trong grading_rules.py, thêm vế nháp: hạ nguồn ĐƯỢC dùng nháp
  nếu dán nhãn 'dữ liệu chưa qua soát'; lan nhất quán 5 tầng prompt (worker/_REVIEW/
  _CHECK/_REWORK/SOURCE_RULE).
- Decompose thêm QUY TẮC GỘP THU THẬP: cấm bước chỉ-tra-cứu 1 thực thể đứng riêng —
  hình dạng chết của team matrix lanes12 (bước trần thừa hưởng tiêu chí định lượng).
- 9 test ghim mới (3 contract placeholder + cap/nesting + xuyên tầng + quarantine);
  bench lanes13/13b + judge; report vòng 5.

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Chặn nháp/reason khớp `_INJECTION_MARKERS` ngay lúc GHI | Live lanes13: nháp chứa cụm vô hại "bỏ qua yêu cầu tìm kiếm" → handoff cách ly TOÀN BỘ artifact, mất cả placeholder | Mất nháp lành hiếm hoi khớp marker; đổi lại không nới tầng quarantine (threat model giữ nguyên) |
| Nháp đính SAU CÙNG, placeholder vẫn là byte đầu | Aggregate detect drop bằng startswith; reason scan theo line-prefix | Không có |
| Chấm dứt dùng matrix_canary làm trục so lane | lanes13b: CẢ HAI lane give_up khi search chỉ trả nguồn thứ cấp — kết quả dao động theo search, không theo lane | Mất 1 case bench; giữ làm canary trung thực |

## Vấp & học được
- Tầng an toàn ăn thịt tầng cứu hộ: fix salvage xong mới lộ quarantine nuốt cả
  artifact vì 1 cụm tiếng Việt vô hại → mọi nội dung tự sinh đi qua handoff phải được
  rà marker từ phía NGƯỜI GHI, không đợi phía đọc.
- Checker với luật mới bắt đúng 1 vụ "rửa nhãn" live: worker tự dán 'dữ liệu chưa qua
  soát' lên nguồn thứ cấp dù không có khối nháp nào — luật thiết kế 2 chiều (cho phép
  + điều kiện) tự phòng lạm dụng.
- Gộp thu thập dồn rủi ro vào 1 bước: bước gộp là bước content duy nhất thì chết là
  give_up cấp task, salvage bước không có dịp chạy — đường ống salvage trọn vẹn cần đề
  chuỗi ≥2 bước content chết bước GIỮA, 2 vòng live chưa có lần nào.

## Mở / sang sau
- Gate trao quyền material_transform: decision team đã hoàn thành SẠCH (điều kiện
  no-salvage completion có bằng chứng đầu tiên) — chờ re-bench ~9 cặp chữ ký.
- Give_up cấp task chưa đính nháp của bước đang chết (chỉ lấy best DONE) — cân nhắc
  mirror salvage bước lên tầng task.
- Query prefetch lấy nguyên văn tiêu đề bước ("Tra cứu và lập bảng so sánh Zoom") —
  rất yếu, đáng có derive query riêng.
