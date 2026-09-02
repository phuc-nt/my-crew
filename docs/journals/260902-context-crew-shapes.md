# Context-crew — vai là bộ công cụ, đội chỉ còn hai dạng
2026-09-02 · ✅ Done · bench H1/H3 chết, H2 giữ

## Làm gì

- **Vai = bộ (tier, web, mail, model)**, không phải nhân vật: `Capability` suy từ profile, hai
  bước kề nhau cùng bộ gộp làm một (`crew_shape`, `step_artifact_contract`).
- **Hand-off là artifact có hợp đồng**: bước `findings` phải có URL nguồn, bước `final` phải có
  thân bài thật; code kiểm trước, LLM tự chấm sau.
- **Router chỉ giữ đội khi có ranh giới** (`classify_shape`): chuỗi quyền (shell / ghi ngoài /
  mail) hoặc làm + soát độc lập; còn lại là sprint với `route.source="shape"`. Route ghi
  `shape` + 3 tín hiệu (`independent_sources`, `needs_independent_review`, `sensitive_tool`).
- **Bench giả thuyết có vạch chết cố định** (`my_crew/bench/hypothesis_stats.py`, Wilson 95%):
  4 brief × 3 run, judge mù 3 phiếu. H1 toả ra/gộp lại thắng 4/12 ở 1.51× chi phí; H3 chuyên
  viên rẻ thắng 4/12 ở 0.59×; H2 reviewer độc lập bắt 10/12 artifact cài lỗi (29/36 lỗi), bất
  đồng 8%. Dạng `fanout` rút khỏi router. Báo cáo
  `plans/reports/bench-260902-1140-context-crew-h1-h3-keep-kill-report.md`.
- Live (haiku): full run 70 passed / 2 failed / 2 errors trong 57:05; hai vòng rerun tuần tự,
  vòng cuối 5/5 xanh (L1, L2, L3/L5) sau sáu sửa sản phẩm ghi ở mục vấp bên dưới.

## Quyết định & vì sao

| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| Rút `fanout` khỏi `classify_shape` thay vì hạ ngưỡng | Vạch chết đặt trước khi đo (≥2/3 cặp); 4/12 không phải sát nút, và nhánh rẻ cũng thua | Brief nhiều nguồn giờ là sprint; vùng ≥12 thực thể chưa đo |
| `permission_chain` không bench, không rút | Ranh giới quyền là an toàn, không phải chất lượng — không có judge nào đo được | Đội chuỗi quyền có thể đắt hơn sprint mà không ai biết |
| Giữ nhãn `fanout` trong `route_stats` | Route cũ trên đĩa vẫn mang nhãn này; thống kê phải đọc được lịch sử | Một nhãn "chết" tồn tại trong bảng |
| Test đổi tiền đề, không nới assert | S1/A2/A8 mất ranh giới vì sản phẩm đổi; S1 ép `team:` ⇒ `custom`, A2/A8 ⇒ sprint | Ba live case không còn chứng minh đội thắng — vì nó không thắng |
| T1 canh heartbeat thay vì dòng log reaper | Reaper chỉ log khi Docker tắt; tiền đề cũ chỉ đúng trên máy không có Docker | Test phụ thuộc file `coordinator.heartbeat` |

## Vấp & học được

- **Đội thua ngay ở đề "hợp đội" nhất.** Brief 4–6 nguồn độc lập là ca đẹp nhất cho toả ra,
  nhưng sprint có ngân sách truy vấn co giãn (`sprint_query_budget`) nên một agent tra đủ,
  rẻ hơn và không mất gì ở hand-off. Ranh giới context không tồn tại ở độ rộng này.
- **Rẻ hơn không cứu được chất lượng.** H3 tiết kiệm 41% nhưng judge thích sprint 8/12 — "bằng
  chất lượng" là điều kiện, không phải chi phí.
- **Giết một dạng làm đổ stub dùng chung.** `_wire` trong `test_sprint_router` là plan toả ra;
  đổi sang chuỗi quyền để các test router khác vẫn có một plan đội thật.
- **Live chạy giữa lúc đổi code cho kết quả cũ.** live_b nạp S1/A2/A8 bản trước kill; phải chạy
  lại ba case riêng để có số đúng.
- **Full live lòi ba lỗi sản phẩm unit không thấy.** (1) reviewer trả rỗng giết cả task → hỏi
  lại một lần (`review_graph`); (2) brief thư kẹt `plan_hash mismatch` trước bước đầu vì hàng
  lưu thiếu `needs_mail` mà hash có; (3) `do_review` mất reviewer vì accept của judge kẹt xoá
  cờ soát — giữ cờ theo `route.shape`. Cả ba đều có unit test cài lại từ số đo live.
- **Socket không im thì timeout đọc không bao giờ nổ.** OpenRouter giữ socket kẹt bằng byte
  keep-alive; một decompose ngồi quá 900s nhận 23k ký tự trắng, delegate đồng bộ không bao giờ
  trả lời CEO. Trần wall-clock 240s thử trước là sai cữ: cùng tối đó model trả ~23 token/s,
  một review 4.5k token hợp lệ mất 190s. Đổi sang stream mọi call + trần **im lặng**
  (`_STREAM_IDLE_S` 120s không chunk) + hai lần im liên tiếp thì bỏ model (`client.py`);
  usage + `cost` vẫn về ở chunk cuối, kế toán không đổi.
- **Fleet live chạy sai model suốt từ đầu.** `cast.LIVE_MODEL` khai haiku, `.env` home ghi
  haiku, transcript nào cũng deepseek: tiến trình pytest đã mang `OPENROUTER_MODEL` từ `.env`
  repo (nạp lúc import), child load `.env` home không override; dòng `ROLE_MODEL_*` thì không
  key nào của config đọc. `serve_env()` đặt model tường minh; guard offline
  `tests/test_live_topology_fleet_model.py`. Các case đỏ M2/X2b trước đó đo tốc độ model
  sai, không phải lỗi sản phẩm.
- **Hai worker khởi động cùng lúc đua nhau migrate `.data/`.** Cả hai qua guard, rename đầu
  thắng, worker thứ hai chết ở `main()` vì `FileNotFoundError` — store đã nằm đúng chỗ. Nhận ra
  việc của sibling và bỏ qua (`legacy_migration.py`).
- **Điều kiện dừng của harness không nhận ra task đã đứng.** M2 trên haiku: bước thư parked
  `waiting_clarify` (hỏi CEO) sau 20s, hai bước sau `pending` chờ nó; coordinator log
  `no actionable step` 14 phút, case đỏ trên đồng hồ dù mọi assert đều đúng. `is_settled` giờ
  coi bước pending kẹt sau dependency đã đứng (đệ quy) là đứng — vẫn không dừng khi dep đã
  `done` hoặc đang chạy (`tests/test_live_topology_settle_predicate.py`).
- **Kiểm định lượng: precision hơn recall.** `demanded_entities` từng lấy cả "ví dụ: A, B"
  và thuộc tính viết thường làm thực thể bắt buộc → false positive fail bước đúng. Giờ chỉ
  nhận thực thể viết hoa ngoài mệnh đề ví dụ; "liệt kê đúng N" đọc được; dòng dữ kiện nói
  rõ chiều ("không ít hơn … nhiều hơn KHÔNG phải lỗi") — grader từng đọc "(tiêu chí đòi 2)"
  với 28 mục thành lỗi.
- **Grader chấm phạm vi bước, không phải phạm vi đề.** Bước (1a) bị fail vì thiếu (1b)/(2)
  của đề gốc; rework duy nhất tiêu vào một lời từ chối, bước phụ thuộc không bao giờ chạy.
  Quy tắc trần chung nay nói bước là MỘT phần, phần tiêu chí không nhắc là việc bước khác.
- **Bản nháp đụng trần chi phí là kết cục ngân sách, không phải lỗi worker.** Rework dưới
  cùng trần chỉ tiêu thêm rồi ghi đè ghi chú trần bằng một lời từ chối. Nay draft có ghi chú
  trần ⇒ fail lần đầu là chung cuộc, giao nguyên bản cho CEO quyết.
- **Planner phải thấy ranh giới công cụ.** Roster chỉ ghi domain nên bước "tra lịch sử" rơi
  vào secretary native 1/4 lần. Đúng tinh thần context-crew (vai = công cụ + quyền + model):
  mỗi dòng roster kèm gợi ý năng lực suy từ `Capability`, prompt có QUY TẮC CÔNG CỤ.
- **Hai file live chạy song song thì delegate/HTTP timeout.** Chạy tuần tự trong một chuỗi
  nền; traceback Telegram 404 là nhiễu fixture, có cả ở run xanh.

## Mở / sang sau

- Bench lại fan-out chỉ khi có bằng chứng sprint hụt ở ≥12 thực thể (chưa có).
- `do_review` mới đo trên artifact cài lỗi; tỉ lệ báo động giả trên artifact sạch chưa đo.
- UI cho dạng đội (phase 4 của đề xuất) chỉ làm cho `do_review` và `permission_chain`.
