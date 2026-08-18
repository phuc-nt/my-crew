# v84 — Sprint đọc trang chính thức thay vì chỉ đọc snippet
2026-08-17 · ⚠️ Đã đo — giả thuyết arc BỊ BÁC bởi thước đo cũ, thước đo được sửa ở v85 · chưa release

## Làm gì
- `official_page_pick.py` — chọn URL trang chủ của entity **bằng code thuần**, đọc lại
  URL đã nằm sẵn trong bundle search (v73 cho URL đi kèm body), không thêm một lượt
  search hay một lượt gọi model nào.
- `official_page_fetch.py` — scrape từng trang độc lập qua `firecrawl_tool` sẵn có, bọc
  qua đúng `format_search_results` mà `web.scrape` đang dùng, trần 3 trang × 8000 ký tự,
  và **tẩy sentinel điều khiển** khỏi text trang trước khi gộp vào bundle.
- Nối một **vòng fetch** vào sprint pipeline giữa prefetch và draft: `prefetch → [pick →
  fetch → gộp bundle] → draft → coverage → revise`. Gate `needs_web and bundle`.
- `record_event({"t": "fetch", ...})` cạnh event `prefetch`, kèm trường `skipped` nêu
  **lý do** không fetch, và nối vào cả 3 consumer transcript: office feed (`web-fetch`),
  review evidence (URL đã mở), reflection (chỉ số đếm).
- 3443 BE / 9 skipped (trước arc 3384), ruff sạch.

## Quyết định & vì sao
| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| Chọn URL bằng CODE, không bằng LLM | Sprint mode tồn tại vì nó code-paced (v77); thêm một call để chọn link là trả lại đúng thứ mode này ra đời để bỏ | Heuristic domain, không hiểu ngữ cảnh như model |
| Fetch lỗi trả `""`, KHÔNG trả sentinel THIẾU | Search hỏng = "không được nhìn"; fetch hỏng = "không có thêm", vì snippet bundle vẫn còn nguyên. Bắn sentinel ở đây là nói dối người đọc | Fetch chết im lặng, chỉ transcript biết |
| Đặt TRƯỚC draft, không sau coverage | Mục tiêu là bản nháp ĐẦU đã có nguồn chính thức, không phải vá nguồn sau khi viết bằng nguồn kém | Trả thêm độ trễ cho cả bước, kể cả khi draft vốn đã đủ |
| Không nới `web_search_tool` khỏi snippets-only | Tool đó dùng chung nhiều đường; nới ở đó là nới cho cả hệ | Sprint phải có đường fetch riêng |
| Khớp host theo **nhãn registrable domain** | Xem "Vấp" | Public-suffix list viết tay 16 mục; suffix lạ thì degrade thành "không official" (an toàn) |
| Tẩy sentinel ở **biên nhập**, không dạy 4 reader nghi ngờ đầu vào | Một chỗ chặn, kiểm được bằng test; 4 chỗ nghi ngờ là 4 chỗ có thể quên khi thêm reader thứ 5 | Marker thật trong text trang bị đổi thành `[…]` — chấp nhận được, vì trang nhà cung cấp không có lý do viết đúng từ vựng nội bộ của sprint |
| Trần 3 trang, không 5 | Ràng buộc là **lease**, không phải context: 5 × 60s timeout = 300s trong một node, trên lease 600s | Ít hơn 2 trang nguồn chính thức mỗi bước |

## Vấp & học được
- **Khớp host bằng substring là lỗ bảo mật, không chỉ lỗi chất lượng nguồn.** URL được
  chọn thì SẼ BỊ FETCH, mà kết quả search là nội dung kẻ khác tác động được. Tự dò tay
  thấy `spotify.com.evil.tld`, `notspotify.com`, `my-spotify-hack.ru`,
  `spotify.evil.com` đều lọt. Học: chỗ nào biến đầu vào không tin cậy thành **đích của
  một request**, chỗ đó phải khớp chính xác, không khớp gần.
- Siết xong thì lộ hồi quy ngược chiều: `Apple Music` không còn khớp `apple.com` — mà
  2/5 entity trong brief đúng dạng đó. Học: mỗi lần siết một matcher, phải chạy lại
  ma trận cả hai phía (giả mạo phải chặn / thật phải nhận), không chỉ phía vừa sửa.
- **Bundle plain-text đang là control plane, và vòng fetch mở nó cho bên ngoài.**
  `sprint_runner` đọc chính marker của mình NGƯỢC ra khỏi bundle làm tín hiệu điều khiển
  (`_source_refused`, `_has_results`, `missing_note`, gate `_NO_CAPABILITY`) — marker được
  tin chỉ vì nó *xuất hiện*, không có gì ghi ai viết nó. Sống được khi mọi byte đến từ
  snippet provider; vòng này gộp cả **thân trang**, nên một dòng giả trong trang scrape
  làm pipeline tự khai "nguồn tìm kiếm gặp lỗi" khi search thật ra thành công. Đo được:
  prefetch 2 vòng → 1 (mất vòng search bù gap), note cho CEO đổi từ "đã tìm nhưng không
  đủ kết quả dùng được" thành lời cáo lỗi sai sự thật. Học: **spotlight của
  `format_search_results` không che được lớp này** — nó chặn injection nhắm vào MODEL,
  còn marker nhắm vào CODE (`quarantined=0` với text chứa nguyên dòng sentinel).
- **Cửa sổ không heartbeat là cách mất lease.** Vòng fetch nằm gọn giữa
  `_beat("sprint_prefetch")` và `_beat("sprint_draft")`: 5 trang × 60s (DNS thì không có
  timeout) = 300s im lặng trên lease 600s. Watchdog đòi lại bước ⇒ worker thứ hai chạy
  lại ⇒ tốn LLM hai lần và bản ghi của attempt này bị coi là stale. Học: thêm một vòng
  I/O vào node có sẵn thì phải hỏi "node này còn đập nhịp không", không chỉ "vòng này có
  nhanh không".
- **Trường thêm để "run sống kiểm được" lại do chính run sống chỉ ra là chưa phủ hết.**
  `skipped` phủ 3 nhánh, nhưng nhánh thứ 4 — Firecrawl CÓ cấu hình, URL ĐÃ chọn, mọi
  trang fail — vẫn ghi `bytes: 0` với `urls` đầy và không có lý do. Test tất định không
  bắt được vì 3 nhánh cũ đều `return ""` trước khi tới dòng đó; chỉ transcript của một
  attempt chạy code cũ mới cho thấy dạng dữ liệu mơ hồ đó trông như thế nào. Học: nhánh
  nào chỉ tồn tại khi phụ thuộc ngoài **có thật** thì test tất định mù với nó — phải đọc
  transcript thật.
- **Bằng chứng sống đầu tiên là của PICKER, không phải của fetch.** Trên bundle prefetch
  thật của brief C3, picker chọn đúng 4 trang chủ — `spotify.com/vn-vi/free/`,
  `apple.com/apple-music/`, `zingmp3.vn/`, `nhaccuatui.com/` — gồm cả ca
  `Apple Music → apple.com`, tức luật bỏ từ sản phẩm chung chạy đúng trên dữ liệu thật.
  Vẫn KHÔNG phải bằng chứng cho trục `nguon`: chưa fetch nổi trang nào.
- **Test xanh chưa chắc test có kiểm gì.** `test_a_reseller_url_in_the_bundle_is_never_fetched`
  vẫn xanh khi tắt hẳn `_is_aggregator` — vì chỉ riêng luật khớp nhãn đã từ chối
  `www.amazon.com` cho entity "Spotify". Học: guard mới thì phải mutation-test chính
  guard đó (tắt đi, test phải ĐỎ), không tin màu xanh.
- **`reassign` được chọn ở nơi không tồn tại người thay thế.** Run xác nhận 3 stall:
  sprint `needs_decision` sau 3 vòng review → judgement chọn đổi người sang `analyst` →
  `_can_do_step` từ chối (step `needs_web=1`, analyst không có `web_search`) → `_give_up`,
  task `stalled`, $0.1676 (≈2× một run thành công) mà không giao được gì. Gate từ chối là
  ĐÚNG (thà kết luận trung thực hơn để analyst bịa số), nhưng lỗ ở tầng trên: với brief
  `needs_web` mà chỉ `researcher` có tool, "đổi người" **không bao giờ** là lối ra —
  can thiệp cuối đáng ra phải là `retry_with_guidance`. Học: khi một nhánh quyết định
  phụ thuộc vào việc *tồn tại* một ứng viên đủ điều kiện, phải kiểm sự tồn tại đó TRƯỚC
  khi chọn nhánh, không phải để nhánh chết ở gate rồi mất luôn lượt.
  Đã sửa: nhánh `reassign` bất khả thi **degrade thành `retry_with_guidance`** (giữ bước
  cho người đang giữ — người DUY NHẤT đủ tool) thay vì `_give_up`; trần can thiệp vẫn kết
  luận task khi đã hết lượt thật. Sửa xong lộ hồi quy do chính mình gây: escalation mất
  chữ "công cụ", chỉ còn "giao lại kèm chỉ dẫn" — một test CÓ SẴN bắt được, nên thêm
  `escalate` nêu đúng tên năng lực thiếu ("X thiếu công cụ bước này cần"), vì CEO chỉ hành
  động được khi biết chọn giữa *cấp thêm tool* hay *chấp nhận thiếu*. Học lần hai: test cũ
  là thứ bảo vệ mình khỏi bản sửa của chính mình — 51 test xanh sau sửa.
- **Chọn đúng NHÀ nhưng sai TRANG: vòng fetch chạy hoàn hảo mà không mang về con số nào.**
  Run sống đầu tiên có Firecrawl (`e905215baf03`) ghi `fetch {"bytes": 18079}`, nội dung
  vào đúng prompt draft ở `role=content seq=7`, bọc đúng `[EXTERNAL_DATA
  source=www.spotify.com rank=1]` — nhưng **0 token giá** trong prompt. Bundle có sẵn 4
  trang spotify (`/vn-vi/free/`, `/vn-vi/premium/`, `/vn-en/free/`, `/vn-vi/signup`);
  picker lấy **trang khớp host đầu tiên theo rank** rồi `break`, nên chọn `/free/`. Đo
  trực tiếp 2 trang: `/free/` = 1785 ký tự, **0** token giá; `/premium/` = 6651 ký tự,
  **27** token giá ("33.000 ₫ cho 3 tháng, sau đó là 65.000 ₫/tháng"). Học: **rank của
  provider trả lời "trang nào liên quan tới CÂU TRUY VẤN", không trả lời "trang nào chứa
  CON SỐ"** — hai câu hỏi khác nhau, và vòng fetch chỉ có giá trị khi trả lời câu thứ hai.
  Đã sửa: `_pricing_affinity` xếp hạng giữa các trang **của cùng một host đã được nhận là
  official** (+1 path có `premium|pricing|gia|goi|...`, −1 có `free|signup|download|...`,
  0 trung tính), rank giữ nguyên làm tie-break. Xếp hạng **không bao giờ** đổi host — chạy
  sau `_is_official_host`, nên lookalike có path giá đẹp vẫn thua trang trơn của host thật
  (có test pin). Trên đúng tập URL sống, pick đổi từ `/free/` sang `/premium/`, 2 pick còn
  lại không đổi. Mutation-verified 2 chiều: tắt điểm affinity ⇒ 3 test ĐỎ, bỏ riêng nhánh
  −1 ⇒ 1 test ĐỎ.
- **Fix không verify sống được thì chưa tính là verify.** Đọc transcript run xác nhận
  1: hai bước rework gọi `web_search` 21 và 27 lượt, `web.scrape` **0 lượt** — grep cả
  task không có chữ đó, tức tool chưa từng được mời (sandbox không có key Firecrawl).
  Đồng thời sửa một chẩn đoán của chính mình: rework chạy **tool-calling loop**, không
  chạy sprint pipeline, nên fix rework-search của v83 tới giờ vẫn chưa bắn live lần nào.
- Trong kết quả rework-0 có sẵn `www.spotify.com`, `www.apple.com`,
  `www.nhaccuatui.com` — đúng các trang chính thức cần, nhưng chỉ ở dạng snippet. Chẩn
  đoán gốc rễ được chính dữ liệu run xác nhận nó.
- **Verify cái thước trước khi tin con số nó cho.** Arc này có đủ số đo sống, nhưng thước
  đo lại là thứ sai: đọc riêng điểm judge ⇒ kết luận "arc thất bại, candidate tệ hơn";
  đọc riêng bytes fetch ⇒ kết luận "arc thành công". Cả hai đều sai. Chỉ khi **mở đúng
  những URL mà baseline tự dẫn** mới thấy nó bịa số, và chỉ khi **đếm giá theo từng
  version artifact** mới thấy phần lớn công là của rework tool loop. Bài học tổng quát:
  một thước đo do LLM chấm mà không truy được về dữ liệu thật thì thưởng **hình thức**
  (bảng kín, citation trông đẹp) chứ không thưởng **sự thật** — và nó thưởng mạnh nhất
  đúng cái ta muốn diệt.
- **Giả thuyết mở plan chỉ đúng một nửa, và nửa sai nằm ngay trong repo.** Câu "trên
  đường sprint không tồn tại đường nào dẫn tới việc mở một trang web" đúng với bước
  `sprint` nhưng bỏ sót `rework` — vốn luôn có tool loop, và review với brief dạng này gần
  như luôn sinh rework. Học: khi kết luận "không tồn tại đường nào", phải kiểm mọi
  **loại bước** của pipeline, không chỉ bước đang sửa.

## Mở / sang sau
- **Vòng fetch đã bắn thật** (user bật Docker): F1 `e905215baf03` done $0.147 đạt review
  ngay round 0; F2 `74c1f9192c78` done $0.185 qua 3 review + 2 rework. Cả hai mở trang
  official thật, không reseller. F1/F2 khác code base (F2 có fix picker) nên không phải
  2 mẫu cùng phiên bản.
- **Blind judge đã chạy — và bác giả thuyết của arc.** Bản được đưa ra chấm là **F1**
  (đối chiếu md5/kích thước với `mapping-round*.txt`: `cand-f1.md` 4609 B); **F2 chưa từng
  được chấm**. Qua 3 lượt: `nguon` F1 **5 / 6.5 / 7** vs baseline **8 / 9 / 9** — candidate
  thua, và không phải thiên lệch vị trí (đổi chỗ A/B vẫn cùng kết luận).
  *(Đã sửa: bản ghi đầu của mục này viết "3-4 vs 9" và ngầm hiểu là F2 — cả hai đều sai.
  Kết luận "candidate thua" không đổi.)*
- **Nhưng baseline thắng bằng số BỊA** — kiểm từng ô bằng Firecrawl: baseline ghi cả 5
  dịch vụ đều "59.000đ" kèm URL official + "truy cập 26/04/2026" (4 tháng trước ngày
  chạy); trang thật trả **65.000₫** cho cả Spotify và YouTube Music, còn
  `zingmp3.vn/vip` + `nhaccuatui.com/vip` là SPA trả 909/260 ký tự, **0 token giá**.
  Candidate ghi 65.000₫ = đúng trang thật. Truy tiếp: `59.000` chỉ có trong `result_text`,
  **không** trong bất kỳ bundle đầu vào nào ⇒ model tự nghĩ ra, và **peer review cho qua
  ngay round 0** dù prompt ĐÃ có luật chống bịa. Đây là phát hiện quan trọng nhất của arc,
  và nó không nằm trong phạm vi arc.
  *(Truy tiếp ở v85 và sửa lại chẩn đoán: luật chống bịa có điều kiện — "**nếu có khối ĐẦU
  VÀO**" — mà bước sprint có `deps_json=[]` nên handoff rỗng và bị lọc khỏi prompt; baseline
  cũng không có transcript. Reviewer chấm trên văn xuôi vì **bị bỏ đói bằng chứng**, không
  vì luật yếu: review round 0 của F2 — có transcript — tự từ chối 2 số thiếu URL nguồn.)*
- **Công của vòng fetch nhỏ hơn tưởng.** Đếm giá phân biệt theo từng version của F2:
  sprint (có fetch) = 3 → rework-0 = 6 → rework-1 = 7 (review pass). Rework dùng **tool
  loop có sẵn từ trước arc** (46 tool call). Plan mở đầu bằng "trên đường sprint không tồn
  tại đường nào dẫn tới việc mở một trang web" — đúng với bước `sprint`, nhưng bỏ sót
  rework, mà brief này gần như luôn sinh rework. Vòng fetch góp 3/7.
- ⇒ **Chưa nghiệm thu được trục `nguon`**, và lý do không phải "thiếu số đo" mà là
  **thước đo sai chiều**. Việc tiếp theo: sửa judge để đối chiếu số với trang thật; truy
  vì sao peer review trượt số bịa; buộc nhãn "chính thức" truy được về URL đã thật sự mở.
  → **Cả 3 đã làm ở v85** (`260818-v85-source-integrity.md`): thước đo sửa xong thì
  **phán quyết đảo** — baseline `nguon` 9 → **2**, F1 thắng ở cả 2 chiều đảo nhãn.
- Chưa phát hành theo yêu cầu ("không release trước").
- Rework vẫn chỉ có snippet trên đường sprint-rework nếu Firecrawl chưa cấu hình —
  cùng gốc rễ, khác đường.
- Tẩy marker là fix ĐỦ cho vòng này nhưng chưa sửa gốc: tín hiệu điều khiển vẫn đi cùng
  kênh với dữ liệu không tin cậy. Fix cấu trúc (`prefetch_queries` trả `(bundle, status)`
  thay vì nhét sentinel vào text) rộng hơn diff này — để riêng.
- `listed_entities` / `_proper_noun_items` / `retry_round` **đã review xong** (2 lần
  delegate agent đều chết API 529 nên tự review, báo cáo ở
  `plans/reports/from-code-reviewer-to-planner-260817-2050-...`). Kết luận có truy nguồn:
  entity list đến **duy nhất** từ `goal`+`acceptance` do operator viết — kết quả search
  không đi vào đó — nên đây là lỗi chất lượng, **không** phải lỗ bảo mật. 3 thay đổi sạch
  về correctness. Vẫn nên tách commit riêng.
- **3 run xác nhận: 2 done / 1 stalled** (không phải 3/3). Baseline cùng brief stall 2
  lần, nên có tiến bộ — nhưng n=3 và còn 1 lần stall, chưa được ghi "đã hết stall".
- Lỗ `reassign`-khi-không-có-ứng-viên ở `stuck_decision` **đã sửa** (xem "Vấp"); là việc
  riêng ngoài arc fetch nên nên đứng commit riêng.
- `retry_round > 0` vẫn **chưa** bắn trên run sống nào (F1 đạt ngay round 0 nên không có
  retry) — cùng dạng nợ "fix chưa verify sống" của v83.
