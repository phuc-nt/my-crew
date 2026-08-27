# Chuẩn nguồn thực tế trước release — vá 3 tầng, đo trước sửa sau
2026-08-27 · ✅ Done (KHÔNG tuyên release-ready)

## Làm gì
- Đóng hồ sơ "lỗi 4" bằng đo lường: kẻ leo thang tiêu chí KHÔNG phải reviewer mà là
  `guidance` của stuck judge (`STUCK_JUDGE_SYSTEM`) — 4 bằng chứng độc lập, acceptance
  sạch trong mọi case; grader chỉ chấm theo guidance nguyên văn.
- Vá 3 tầng, mỗi tầng một commit: `a335e32` anchor ngày cho worker/grader; `ce7cd7f`
  port luật nguồn của intake sang `_DECOMPOSE_SYSTEM`; `a8c832b` anchor ngày cho stuck
  judge + trần guidance ("không nâng chuẩn quá Tiêu chí đạt; tên trang hoặc link là đủ").
- Bench verification lanes6 (2 brief × 2 lane, TICKS=60): sprint/ecommerce là case ĐẦU
  TIÊN toàn arc giao được báo cáo thật (4990c, $0.085); 3 case còn lại give_up trung thực.
- Release gate ghi thành văn trong report bench v2: 4 PASS / 1 FAIL (chưa có cặp
  deliverable để judge mù chấm lane vs lane).

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Không sửa reviewer/`EVIDENCE_RULES` | Verdict phase 2: không có bằng chứng lọt từ tầng đó | Nếu đo thiếu, phải quay lại |
| "Blindspot 23%" trên lanes6 → sửa script đo, không sửa code | Một event `prefetch` gói NHIỀU truy vấn (angle rotation v81); đối chiếu từng case 9=9, 30=30, 4=4, 18=18 → 0% thật | — |
| KHÔNG tuyên release-ready dù 3 bản vá đều hiệu quả | 3/4 case vẫn stall vì lớp lỗi khác (dưới) | Chậm release thêm một vòng |

## Vấp & học được
- Suýt kết luận "bug-6 tái phát" từ con số 23% — bài học cũ lặp lại: dump MỘT dòng
  end-to-end (event prefetch chứa list queries) trước khi tin số tổng hợp.
- Luật cấm siêu dữ liệu hiệu quả đúng lớp của nó (0 đòi ngày truy cập/tác giả/Statista,
  0 ngày bịa) nhưng judge lách sang chiều khác: "tên trang → URL thực tế", lạm phát chi
  tiết (giá gói, chất lượng âm thanh...) — chặn theo danh sách thì model đổi chiều leo.
- Finding mới cho vòng sau: guidance lặp gần nguyên văn giữa attempt 2/3 (không hội tụ);
  decompose lỗi kiến thức (đếm "Zing MP3, NCT, NhacCuaTui" = 3 nền tảng — NCT là
  NhacCuaTui); bước QA tự nâng chuẩn làm task give_up dù báo cáo đã viết xong ở step-3.

## Mở / sang sau
- Vòng can thiệp không hội tụ: guidance lặp nguyên văn + leo chuẩn chiều nội dung —
  ứng viên chính cho arc kế.
- Câu hỏi gốc plan v2 (lane nhanh có kém hơn?) vẫn chưa chấm được — cần ≥1 cặp cùng giao.
