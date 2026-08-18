# v85 — Sửa thước đo nguồn: reviewer thấy NỘI DUNG trang, không chỉ byte count
2026-08-18 · ✅ Done (đo sống 3 run, arc xác nhận end-to-end) · chưa release

## Làm gì
- Truy tới gốc **vì sao review round 0 cho qua bảng giá bịa của v84** — bằng cách đọc code,
  không suy đoán. Chuỗi: bước `sprint` có `deps_json=[]` → `_read_handoff` trả `""` →
  `build_self_check_messages` lọc `if p` nên khối ĐẦU VÀO **bị bỏ khỏi prompt** → luật chống
  bịa vốn có điều kiện *"nếu có khối ĐẦU VÀO"* không có gì để đối chiếu.
- `content_head` vào event `prefetch` ([collect_prefetch.py](../../my_crew/runtime/collect_prefetch.py))
  và event `fetch` ([sprint_runner.py](../../my_crew/runtime/sprint_runner.py)); `_append_content`
  render dòng `→ nội dung:` trong `transcript_evidence`. Trước đó transcript chỉ ghi
  `queries`/`urls`/`bytes` — chứng minh trang ĐÃ mở, không chứng minh con số nào nằm trên đó.
- `QUY TẮC NHÃN NGUỒN` vào cả prompt review và prompt self-check: gọi "chính thức" một số
  lấy từ báo/blog/đại lý là **sai nhãn** ⇒ nêu ở `failures`; ghi rõ "nguồn thứ cấp" là
  TRUNG THỰC, không phải lỗi — kể cả khi trang chính thức đã mở nhưng không trả về số nào.
- `blind_judge_v2` (sandbox, không vào repo): nhận `--evidence` là nội dung trang mở LIVE,
  đếm `nguon_verified/unverified/contradicted` theo từng số nên điểm **truy được**.
- 3 test mới (TDD ĐỎ→XANH). Suite 3462 passed / 1 skipped (trước 3459), ruff sạch.

## Quyết định & vì sao
| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| KHÔNG sửa luật chống bịa; sửa việc **cấp bằng chứng** | Review round 0 của F2 tự ghi "không tự ý bịa số giá YouTube Music khi thiếu nguồn" và từ chối 2 số thiếu URL — cùng prompt, cùng model, khác duy nhất là F2 có transcript. Luật đúng, đường ống mù | Lỗ chỉ bịt ở peer review; self-check của sprint vẫn chấm trên văn xuôi |
| Đi đường **transcript**, không nới hợp đồng `(text, cost)` của `run_work` | `StepTelemetry` (`team_step_runner.py:70`) đã là tiền lệ cho side-channel; `bundle` là biến local chết cùng `_work` | Bằng chứng chỉ tới grader khi transcript được ghi |
| `content_head` vắng ⇒ **không thêm dòng nào** | Transcript cũ và round bị `skipped` không có nội dung; suy diễn ở đây là bịa bằng chứng | Transcript trước v85 không được lợi |
| Judge coi "nhiều dịch vụ CHUNG một số" là dấu hiệu **trừ** điểm | Chính v1 khen baseline "số liệu nhất quán" — mà sự đồng nhất LÀ chữ ký của bịa | Bảng giá thật mà trùng giá bị nghi oan |
| Ô trống có lý do chấm **cao hơn** ô đầy bằng số không truy được | v1 thưởng độ ĐẦY của bảng, tức thưởng đúng cái cần diệt | Model có thể học cách để trống cho an toàn |

## Vấp & học được
- **Thước đo sửa xong thì phán quyết ĐẢO.** Cùng cặp v84 (baseline vs F1), bằng chứng là
  nội dung 2 trang official mở live (`spotify.com/vn-vi/premium` 6397 ký tự,
  `music.youtube.com/music_premium` 5696 — cả hai ghi **65.000 ₫**): baseline `nguon`
  **9 → 2** (2 số `contradicted`, 0 `verified`), F1 6-7, verdict **F1 thắng ở CẢ HAI** chiều
  đảo nhãn. Judge tự nêu đúng 2 số bịa mà không được mách bản nào là bản nào. Học: một
  thước đo do LLM chấm mà không truy được về dữ liệu thật thì đo **hình thức trích dẫn**,
  và nó gọi đó là "nguồn" — sai không phải vài điểm mà **sai chiều**.
- **Tự sai attribution rồi tự bắt được bằng md5.** Đã báo "candidate thua với `nguon` 3-4"
  và ngầm hiểu bản bị chấm là F2. Đối chiếu `mapping-round*.txt` + kích thước
  (`cand-f1.md` 4609 B vs `cand-f2.md` 6340 B) cho thấy bản bị chấm là **F1** (`nguon`
  5/6.5/7), và **F2 chưa từng được đưa ra chấm**. Học: khi bench đánh nhãn A/B ẩn danh, phải
  truy lại file thật bằng hash trước khi gán số cho một biến thể — nhãn A/B không mang danh tính.
- **"Peer review trượt" là chẩn đoán sai, và bằng chứng phản bác nằm ngay trong dữ liệu cũ.**
  `step-47-review-0.json` của F2 từ chối `59.000₫` (Apple Music) + `49.000₫` (Zing MP3) vì
  thiếu URL xác minh — đúng những con số baseline bịa và được v1 cho 9 điểm. Học: trước khi
  kết luận "gate yếu", phải tìm một ca mà gate đó CHẠY ĐÚNG; nếu có, vấn đề là đầu vào của
  gate chứ không phải gate.
- **Luật có điều kiện là luật có thể bị vô hiệu hoá bởi hình dạng dữ liệu.** *"nếu có khối
  ĐẦU VÀO"* nghe vô hại, nhưng bước `sprint` không deps thì tiền đề vĩnh viễn không thoả —
  luật im lặng, không cảnh báo. Học: mỗi tiền đề trong prompt là một nhánh cần biết ai làm
  cho nó FALSE.
- **Giả định "Firecrawl không render JS" là SAI — đã xác nhận trên đúng ca SPA.**
  `zingmp3.vn/vip` trả 965 ký tự có giá thật ("Chỉ từ 13.000đ/tháng" Plus, "41.000đ/tháng"
  Premium); `www.nhaccuatui.com` render nhưng redirect sang trang Google Play. Kết luận v84
  chính thức bị đảo: fetch official page hoạt động cả trên SPA.
- **Run sống sau v85 (task 805d6b68f76d) lộ đúng MỘT chỗ đứt ống: review tìm transcript
  sai thư mục.** Producer đúng (event `fetch` có `content_head` 2063 ký tự chứa `65.000`),
  nhưng worker ghi transcript vào jail riêng `.data/agents/<id>/…` còn `_run_review` glob
  root chung → best-effort nuốt lỗi, review lại mù. Học kép: (1) `65.000` xuất hiện trong
  prompt review là **false positive** — nó nằm trong bảng của chính bài bị chấm, phải grep
  marker khối (`BẰNG CHỨNG QUÁ TRÌNH`) chứ không grep giá trị; (2) đường ống best-effort
  degrade im lặng thì phải xác minh bằng run sống, test đơn vị cùng-một-thư-mục không bắt
  được lệch layout. Fix: `ReviewStepInput.graded_assignee` + lookup jail-first fallback
  root chung (commit `f179788`), khớp tiền lệ `routes_office_artifacts`.
- **Run sống #2 (ed30096396ea) xác nhận khối bằng chứng ĐÃ vào prompt review — và lộ bug
  thứ hai cùng lớp:** `_append_content` cắt `content_head` bằng hằng tool-result 500 ký tự,
  trong khi `65.000 ₫` nằm sau vị trí 500 của head 2063 ký tự → khối chỉ dùng 1622/8000
  budget mà con số cần đối chiếu vẫn bị mất. Fix: `_CONTENT_CHARS = 4000` riêng cho nội
  dung trang (commit `540e7af`). Học: một tiêu chí "grep được giá trong prompt" phải chạy
  đến CÙNG — mỗi run sống bóc đúng một tầng cắt xén mà unit test cùng-fixture không thấy.

## Mở / sang sau
- **Self-check của bước sprint vẫn mù** (bảng phạm vi trong plan): peer review — cửa quyết
  định `passed` — đã có bằng chứng, nhưng self-check thì chưa. Bịt được bằng side-channel
  kiểu `StepTelemetry`; là scope riêng, chưa làm.
- ~~Run sống xác nhận~~ **ĐẠT** ở run #3 (task b1fb6f39cb62, done/delivered, $0.26): khối
  `BẰNG CHỨNG QUÁ TRÌNH` trong prompt review round 0 chứa nội dung trang official đã mở,
  `65.000` xuất hiện 4 lần TRONG khối bằng chứng (không phải text bài bị chấm) — reviewer
  đối chiếu được giá với trang thật. Verdict round 0 passed=True, failures=[].
- `retry_round > 0` vẫn chưa bắn trên run sống nào (nợ từ v83/v84).
- Đã commit theo arc (`e3eef5b`…`f179788`); chưa release — chờ quyết định người dùng.
