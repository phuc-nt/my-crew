# Vòng rework mù suốt từ đầu — và bản vá trước khi cắt v0.14.0
2026-08-27 · ✅ Done · đã tag v0.14.0

## Làm gì

- **Sửa lỗi gốc: bước `rework` chưa bao giờ nhận được lời soát chéo.** Nó đọc artifact của
  bước trước theo `seq` của CHÍNH dòng review, trong khi review chỉ ghi
  `step-<seq_bước_bị_chấm>-review-<vòng>.json`. Đọc trượt → handoff rỗng → bước sửa lại
  viết từ đầu chỉ với cái tiêu đề. Đo trên toàn fleet: danh sách lỗi tới được **0/87** dòng
  rework; sau vá **87/87**.
- **Xếp lỗi lên đầu query tra web.** Query cắt ở 44 từ (Brave trả HTTP 422 nếu quá 50 → 0
  kết quả), mà bản nháp bị loại nằm trước danh sách lỗi trong brief — nên vòng sửa tiêu hết
  ngân sách từ để tra lại đúng cái vừa bị bác.
- **Sửa lỗi thứ hai:** `DEFAULT_JUDGE_MODEL` trỏ `google/gemini-3-flash` — provider đã gỡ,
  HTTP 400, mọi lượt chấm mù chết ngay phiếu đầu.
- **Sửa lỗi thứ ba:** `self_check` cộng dồn lỗi mọi vòng rồi ghi cả cụm vào artifact, nên
  bản giao mang theo lời phê về những bản nháp đã bị thay.
- Cắt **v0.14.0** (`e41b5f0`), bổ sung cả ba lỗi vào CHANGELOG.

## Quyết định & vì sao

| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| Đặt `REWORK_FAILURES_HEADING` ở module PARSE, `review_graph` import ngược lại | Bên sinh và bên đọc dùng chung một literal; đổi chữ tiêu đề không thể âm thầm làm vòng sửa quay về tra bản nháp cũ | Chiều import ngược trực giác, phải có comment |
| Cắt query theo TỪ, không theo ký tự | 44 từ là giới hạn cứng của provider; cắt theo ký tự là sai trục và trượt im lặng — bản đầu đã hỏng đúng kiểu đó | Tiếng Việt có dấu vẫn có thể dài byte, nên còn `MAX_QUERY_CHARS` làm chốt phụ |
| Buộc danh sách lỗi vào đúng bản nháp được giao, dùng chung swap keep-best | keep-best có thể lùi về bản nháp cũ hơn; nếu báo lỗi của vòng cuối thì hai thứ lệch nhau | Thêm một trường state (`best_failures`) |
| Tag v0.14.0 trước khi sửa nốt lỗi 3 | Lỗi có trước v0.14.0, tag không làm xấu thêm; bản vá rework mới là thứ đáng ghi vào release | CHANGELOG phải sửa lại sau khi vá tiếp |

## Vấp & học được

- **Hai lần tự đo sai, cả hai đều tự bắt được trước khi báo.** Lần 1 quét mọi dòng bắt đầu
  bằng `-` nên vớ phải mục "Đạt ✓" của reviewer (ra 20/87 bịa). Lần 2 quên tiền tố `- ` mà
  query giữ lại nên báo "LEADS 0/87". Bài học: mọi con số tổng hợp phải dump một dòng
  end-to-end để đối chiếu trước khi tin.
- **Chẩn đoán đầu tiên sai hoàn toàn** ("rework chạy mù, 0 lượt gọi tool") — `audit.jsonl`
  cho thấy có 3 lượt `web_search:brave`, `result_count: 5`. Nguyên nhân thật là handoff rỗng.
- **Fix 2 hầu như không kích hoạt trong thực tế.** Cả 3 vòng rework live đều có tiêu đề
  44–62 từ, dài hơn cả ngân sách query, nên danh sách lỗi không chen vào query được. Chúng
  sửa đúng là nhờ fix 1. Suýt nữa ghi công nhầm cho fix 2.
- **Một task stall hoá ra không phải hồi quy.** `74e16044cb6f` dừng ở `self_check` (bước
  `work`, `needs_review=0`, chưa từng đi qua đường rework). Truy tiếp mới lòi ra lỗi 3:
  4/8 lời phê trong artifact SAI so với chính bản văn được giao, và `stuck_decision` đưa
  đúng cụm đó cho điều phối — nó chấm bước theo lỗi không còn tồn tại, đốt 4 lần can thiệp.

## Mở / sang sau

- Tiêu đề bước dài quá 44 từ vẫn chiếm hết query (5/87 dòng). Chặn/cắt ở khâu decompose?
- `MAX_REVIEW_ROUNDS = 2`: đo live thấy một case đang hội tụ thật (6 → 3 → 2 lỗi) thì hết
  ngân sách vòng và stall. Có nên nới khi số lỗi còn đang giảm?
