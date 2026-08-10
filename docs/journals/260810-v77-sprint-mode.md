# v77 — Sprint mode: việc một người làm trọn, do code điều nhịp
2026-08-10 · ✅ Done

## Làm gì

- **Sprint mode** = team task suy biến: đúng 1 bước work gắn `step_type="sprint"`, đi
  qua nguyên bộ máy cũ (review ladder, clarify, escalate, delivery) — không nhánh
  runtime thứ hai.
- **Pipeline code-paced** trong `runtime/sprint_runner.py`: prefetch (Python chọn
  truy vấn) → draft (LLM) → `coverage_gaps` (Python) → targeted-search + revise
  (LLM, ≤2 vòng) → done. `MAX_REVISE_ROUNDS=2`, `MAX_TOTAL_QUERIES=8`.
- **Router + override** (`agent/sprint_intake.py`): CEO gõ tiền tố `sprint:` / `team:`.
  4 trường hợp KHÔNG override được: ghi ra ngoài, cần shell, nhiều nhân sự, dài hơi.
- **Đo thật** (`plans/reports/benchmark-260810-0654-v77-sprint-vs-team-mode-report.md`):
  nhanh hơn 3.6–7×, rẻ hơn 4.1×, chấm mù **28 vs 8** — sprint thắng cả tốc độ lẫn
  chất lượng.

## Quyết định & vì sao

| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| Code điều nhịp, không react-loop | Đo được: 1 bước synthesis kiểu react tốn 780s vs 60–120s native trên fleet model | Pipeline cứng, không tự nghĩ ra bước lạ |
| Sprint là team task suy biến, không runtime riêng | Thừa kế sẵn review/clarify/escalate/delivery; không phải bảo trì 2 nhánh | Vẫn tốn 1 row review khi band supervised |
| Giao artifact **nguyên văn**, bỏ qua `make_aggregate` | Artifact sprint CHÍNH LÀ thứ CEO cần; tóm tắt lại sẽ cắt còn 500 ký tự | Mất lớp "viết lại" từng che lỗi format — chính là bug 6 |
| Không hạ ngưỡng router xuống ≤3 thực thể | Ở mức 5 thực thể sprint vẫn thắng team cả 2 mặt; hạ ngưỡng là bỏ phần thắng đậm nhất | Ở 5 thực thể thỉnh thoảng còn 1 vòng rework |

## Vấp & học được

- **Cắt topic giữa cụm danh từ** → truy vấn `"Nghiên cứu so sánh 5 dịch Spotify"`: 5 từ
  nói về ĐỀ BÀI, từ thứ 6 đứt giữa cụm. Search trả về blog so sánh thay vì trang giá →
  4/5 dịch vụ thiếu giá. Học: cắt theo số từ phải tôn trọng ranh giới cụm; tiếng Việt
  viết danh từ riêng thành nhiều âm tiết hoa rời nên "Việt|Nam" trông như 2 từ.
- **Intake tự siết tiêu chí thành bất khả thi**: CEO chỉ viết "Nêu rõ nguồn", intake
  nâng thành "tên trang + **ngày truy cập**". Snippet search không bao giờ có ngày truy
  cập → cả 3 vòng soát trượt CÙNG một tiêu chí, trong khi báo cáo đã đúng và đủ. Học:
  tiêu chí chặt hơn đề bài không làm chất lượng cao hơn, chỉ tạo bế tắc vĩnh viễn.
- **Chain-of-thought lọt tới CEO**: bỏ qua `make_aggregate` cũng là bỏ luôn luật
  "bắt đầu NGAY bằng tóm tắt" mà prompt tóm tắt đã mang từ lâu. ~2000 ký tự
  "The user wants me to… / Wait, the prompt says…" đến thẳng CEO. Học: khi bỏ một
  lớp xử lý, phải hỏi lớp đó đang **âm thầm** gánh luật gì.
- **Escalation nói điều CEO đã biết**: "trượt sau 3 vòng" — thứ duy nhất CEO tự thấy
  được. Nay trích tối đa 3 failure còn sót. Học: thông điệp bế tắc phải mang thứ
  người đọc KHÔNG tự tra được.
- Lỗi cắt output khi một bước ôm nhiều thực thể là bệnh của **team mode** (bản team
  Benchmark B thiếu hẳn phần liên kết ghi chú sau 31 phút) — sprint tránh được vì
  Python chia sẵn 1 truy vấn/thực thể.

## Mở / sang sau

- ~~Bug cắt output của team mode khi gói nhiều thực thể trong 1 bước~~ — fixed cùng
  ngày (`1333e8e`, `fanout_split` code-side) cùng bug plan_hash sau stuck-reassign
  (`4e933f4`). Benchmark C post-fix (đề học online 5×3, có replan tự-chữa
  end-to-end): sprint 7m48s/$0.0191/mù 29 vs team 20m14s/$0.0757/mù 10 —
  `plans/reports/benchmark-260810-1602-v77-postfix-team-vs-sprint-report.md`.
- Cân nhắc gộp release 0.10.0 (kèm soak autonomy band đang chờ).
