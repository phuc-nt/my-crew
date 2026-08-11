# v78 — Phễu định tuyến: router không cần đúng, chỉ cần có lưới đỡ

2026-08-11 · ✅ Done

## Làm gì

- **Lật mặc định** `classify_brief`: v77 whitelist-mới-được-sprint (nghi ngờ → team),
  v78 **mặc định sprint**, chỉ đẩy team khi có tín hiệu CẤU TRÚC — >1200 ký tự,
  >10 thực thể (`_MAX_SPRINT_ENTITIES`), hoặc ≥3 đầu việc tách dòng (`_MAX_DISTINCT_ASKS`).
- **`downgrade_to_sprint`** (`agent/sprint_intake.py`): chạy SAU decompose, TRƯỚC khi
  băm/lưu. Plan suy biến (≤2 bước, 1 người, tuyến tính, không shell/ghi-ra-ngoài) →
  kéo về sprint, **0 lượt gọi model thêm**. Nghi ngờ → trả None, để team chạy.
- **Routing log**: cột `route_json` (`team_task_store`) ghi `mode`/`source`/`reason`/
  `signals` cho MỌI nhánh — prefix, refusal, heuristic, downgrade, dead_end. Chỉ số
  đo được, không chứa nguyên văn đề.
- **Dead-end nối vào log**: sprint bế tắc thì `_mark_route_dead_end` ghi đè `source`
  thành `dead_end` nhưng giữ quyết định gốc dưới `previous`.

## Quyết định & vì sao

| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| Lật mặc định sang sprint | Chi phí route sai **bất đối xứng**: sai về sprint thì dead-end kéo về sau vài phút; sai về team tốn 20m14s/$0.0757 vs 7m48s/$0.0191 CÙNG đề, chấm mù 10 vs 29, **và không ai biết** | Đề to lọt sprint sẽ mất một vòng dead-end trước khi về đúng chỗ |
| Tín hiệu cấu trúc, không phải từ khóa | Whitelist từ khóa là thứ vừa fail: đề tự nhiên ("cho tôi biết giá X, Y, Z") không chứa từ nào trong đó | Đếm dòng bullet không bắt được văn xuôi kể 3 việc trong 1 đoạn |
| Downgrade đặt SAU decompose | Kế hoạch model vừa dựng là bằng chứng mạnh hơn mọi heuristic đọc chữ — nó đã biết roster, đã chia việc | Đã tốn lượt decompose rồi mới hạ; không tiết kiệm được lượt đó |
| `route_json` chỉ lưu số, không lưu đề | Log để auto-tune ngưỡng, không phải để đọc lại nội dung | Không tra ngược được đề nào gây route sai nếu task bị xoá |
| Không backfill task cũ | Task trước v78 không có câu trả lời trung thực về "lớp nào quyết định" | `route_json` NULL trên task cũ, mọi read path phải chịu None |

## Vấp & học được

- **Test cũ đỏ vì đề cũ đổi hướng**: hai test dùng `"chuẩn bị demo cho khách hàng lớn"`
  làm đề-phải-đi-team; lật mặc định xong nó đi sprint. Phải soạn `_TEAM_SHAPED_BRIEF`
  (3 bullet) mới có đề thật sự team-shaped. Học: khi lật một mặc định, test nào dựa
  vào mặc định cũ sẽ đỏ **đúng chỗ nó nên đỏ** — đó là tín hiệu, không phải phiền toái.
- **Lớp downgrade chưa kích hoạt được trên live**: soạn đề 1335 ký tự cho việc một
  người, decompose trả 4 bước / 2 người (tách mỗi dịch vụ một bước + thêm bước `qa`
  riêng) → vượt cả `_MAX_DEGENERATE_STEPS` lẫn guard cùng-một-người. Guard từ chối là
  ĐÚNG hợp đồng, nhưng nó chỉ cứu plan đã suy biến sẵn, **không kéo ngược được plan đã
  bị thổi phồng**. Lưới đỡ còn lại cho nhóm này chỉ là ngưỡng 1200 ký tự.
- **Tải review giảm chứ không tăng**: lo mặc-định-sprint làm phình review là lo sai —
  review mint theo content step, sprint chỉ có một. Cặp benchmark v77: sprint 2 review
  vs team 6 review. Cặp live v78 chốt cùng chiều: 1 review/$0.0098 vs 2 review/$0.0612.
- **Bất biến an toàn sống sót qua replan VÀ chặn được ở cuối đường**: ca `sprint:` +
  "gửi email" kẹt giữa chừng, hệ tự chỉnh kế hoạch; bước ghi-ra-ngoài trong kế hoạch MỚI
  vẫn giữ `external_write=True` + `needs_review=True`, rồi dừng hẳn ở `waiting_clarify`
  xin CEO duyệt trước khi gửi thật. Ba lớp — assign, replan, cổng duyệt — đều giữ.

## UAT nghiệm thu v77+v78 (2026-08-11)

18 task chạy live, $0.61/$1.50, biên bản ở `plans/reports/uat-260811-1230-acceptance-v77-v78-report.md`.

- **13/13 ca định tuyến PASS**; cả 6 lớp phễu có ca sống, kể cả hai lớp trước nay chưa
  từng bắn: nhánh entity (`9b9af162549a`, 12 thực thể) và **decompose-downgrade**
  (`d25e42785bc6`) — trả lời trực tiếp mục "lớp downgrade chưa kích hoạt được" ở trên.
- **0 bug chặn phát hành.** Hai mâu thuẫn nghi là bug, điều tra ra đều không phải.
- **Refusal cứng lọt 2 họ đề**: "clone repo chạy bộ test" (cần shell) và "cần cả team
  cùng làm" đều trượt sang sprint. Lưới dead-end che được cả hai (một `stalled`, một
  agent từ chối bịa rồi done) — đúng luận điểm nhan đề: router không cần đúng, cần lưới.

| Vấp | Học được |
|---|---|
| A13_3: `route_json=downgrade` nhưng bảng step có 3 `work` | Dead-end **lật route rồi lập lại kế hoạch**, nên hàng step lúc terminal mô tả kế hoạch SAU fallback. Mọi audit đọc bảng step để suy ra route sẽ báo dương tính giả. |
| B5: sprint × trusted = **0 review** | Không phải band gây ra: `_build_sprint_task` hardcode `needs_review=False`, trusted chỉ waive review nội bộ, mà sprint 1 bước thì nội bộ là tất cả. Hai quyết định đúng giao nhau thành "0 mắt soát". |
| Hai ca duy nhất chạm trần chi phí đều là team | Không do chia nhiều bước (2 bước chỉ $0.0489) mà do **vòng review→rework→review**: A6 mint 11 review + 7 rework trên 6 bước nội dung. |
| A9 chốt ở **$0.179, vượt trần $0.15** dù đã bấm cancel lúc ~$0.13 | `cancel` **không phải phanh**: nó đổi status, không giết worker đang bay. Đọc code xác nhận — `_kill_pid` chỉ bắn khi **lease hết hạn**, không có đường nào trong nhánh cancel gửi tín hiệu cho tiến trình con. Nên các bước đã spawn chạy nốt và tính tiền thêm ~$0.05 SAU lệnh huỷ. Muốn trần cứng thật phải chặn lúc mint bước (kiểm ngân sách trước khi spawn), không trông vào thao tác huỷ thủ công. |
| Chấm mù C3 khi nửa team chưa terminal | Chấm nhầm bản: lúc đó bản giao mới là `finalize`, nhưng bước cuối `approval` xong sau đó lại **viết lại toàn bộ** thành bản hướng CEO — mới là thứ người đọc nhận. Chấm lại trên văn bản cuối: sprint 11.0 → **9.5**, team giữ 24.5, phán quyết không đổi. Học: **task chưa terminal thì chưa có bản giao để chấm.** |
| Định dựng ca trusted×external_write để trả nợ v76 | Không dựng được: phễu đẩy đề gửi-email sang sprint, sprint hardcode `external_write=False`. Nợ **còn treo**, ghi rõ thay vì nhận bừa. Đổi lại làm sáng kiến trúc: cờ step chỉ là khai báo định tuyến review, quyền gửi thật nằm ở opt-in profile `team_step_egress` → gateway. |
| Kết luận sớm "trần vòng review hỏng" khi thấy task review sang vòng 3 | **Nghi oan.** Test tái hiện lại PASS → mâu thuẫn nằm ở giả thuyết, không ở code. Vòng 3 do `autopilot_sweep` gọi `run_retry_stalled_step` nhân danh CEO (có chặn trên `MAX_AUTOPILOT_ATTEMPTS`). C3 nửa team xác nhận sống: `qa_pricing` dừng sau `review-2`, không sinh `rework-2`, `autopilot_attempts=0`. Học: **test PASS trái với dự đoán là dữ liệu, không phải test sai** — sửa giả thuyết trước khi sửa code. |
| Chấm C2 lần đầu ra hoà 21.5–21.5 | Bộ trích rút chọn "bước nội dung done cuối theo `seq`", mà rework row cấp seq lúc mint nên bước sửa 3 lần nằm trên cả `finalize`. Lấy nhầm bản nháp làm bản giao. Sửa: ưu tiên bước gốc cuối (đỉnh DAG) rồi mới thay bằng rework mới nhất của chính nó → 24.0–19.0. Cùng họ với vấp A13_3: **`seq` không phải thứ tự logic**, hai lần trong một đợt đọc theo seq đều ra kết luận sai. |

**Benchmark 3 cặp mới, chấm mù**: C1 (content) sprint thắng — cost 52%, điểm 95%, nhanh
2.95×. C2 (phân tích) sprint thắng cả hai trục — cost **18%**, điểm **126%**. Cổng định
trước (sprint thắng-hoặc-hoà ≥2/3) **ĐẠT ở 2/3**, độc lập với C3. Cộng 2 cặp cũ:
**4/5 cặp sprint thắng**.

Số đắt giá nhất: nửa team C2 chạy 6 review + 3 rework mà judge vẫn bắt lỗi số học trong
bản giao ("79−59 = 20 chứ không phải 14") và một chỗ lẫn giá trước/sau VAT — trong khi
nửa sprint 1 review được khen "thành thật ghi rõ *ước lượng*". **Thêm 9 lượt soát/sửa
không mua được độ chính xác.**

C3 (research ~900 ký tự) là cặp DUY NHẤT team thắng, và thắng đậm: **24.5 vs 9.5**
(team hơn 158%, ngưỡng team-thắng là 30%). Nửa sprint rẻ hơn 15× nhưng 5/7 mục trả
"không tìm thấy dữ liệu" — rẻ mà không dùng được thì rẻ vô nghĩa. Áp luật đăng ký TRƯỚC
khi chấm: vì nửa team **tìm được** số thật
(gồm chi tiết phủ định kiểu "Figma không có gói Individual" — bịa không ra được), chênh
lệch quy về **năng lực bước**, routing vô can. Cơ chế: team tự tách bước lúc chạy
(`research_alt` → `sub1`/`sub2`/`gather`), dành một lượt model cho mỗi dịch vụ; sprint
một bước không có đường làm thế. Thứ mua kết quả là **số lượt tra cứu**, cấp được cho
sprint mà không cần đụng ngưỡng. → C3 **không** phải cớ để hạ ngưỡng 1200.

Bảy lần độc lập agent từ chối bịa dữ liệu, gồm một lần ở tổ hợp quyền cao nhất
(trusted + 0 review + sprint): hỏi clarify thay vì tự bịa nội dung cuộc họp khách hàng.
Không lớp nào trong hệ *ép* nó nói "không biết" — 0 review là không ai soát — mà nó vẫn
chọn báo thiếu thay vì bịa đủ.

## Mở / sang sau

- Ngưỡng 10 thực thể / 1200 ký tự: UAT thêm 3 điểm dữ liệu (A9 12 thực thể, A11 637 ký
  tự, C3) — **đều route đúng**, chưa có ca sai nào để biện minh cho việc đổi. Giữ nguyên.
- Nợ B1 (trusted×external_write) chỉ test được khi có agent đầu tiên bật opt-in
  `team_step_egress` — chạy lại NGAY trước khi agent đó nhận việc thật.
- Ba đề xuất chờ CEO quyết: buộc sprint luôn mint 1 review; đặt trần vòng review/rework
  cho team; vá 2 họ từ khoá refusal còn lọt.
- Cần ≥20 dòng `route_json` có outcome mới auto-tune được ngưỡng từ dữ liệu thật.
