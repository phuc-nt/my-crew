# Một model cho cả fleet — scorecard theo role, policy suy luận, 23 lỗi vá
2026-09-05 · ✅ Done

## Làm gì
- Đồng bộ mọi role về `~deepseek/deepseek-v4-flash-latest` (bỏ ghim Haiku ở advisor
  coordinator theo lệnh CEO), rồi đo model đó tốt ở role nào: bench mới
  `run-sprint-benchmark.py roles` (`my_crew/bench/role_bench*.py`) chạy prompt builder +
  parser thật của 7 role, chấm tất định, Wilson interval, `--compare`; baseline
  `bench/role_baseline_0.17.0.json`.
- Chính sách suy luận theo role `role_reasoning` (`DEFAULT_ROLE_REASONING`): giữ suy nghĩ cho
  plan/review/util/aggregate, tắt cho content/advisor/sprint_low; `LlmResult.reasoning_tokens`.
- Trần `max_tokens` 16 384 + bắt `LengthFinishReasonError` của SDK stream; guard trả-rỗng gọi
  lại cùng request; classifier re-ask khi dead-end; `_keep_ceo_structure` giữ nguyên văn đề;
  `research_gap`/`mark_research_steps`; `repair_terminal_assignee` + coercion id/boundary;
  `brief_context_gap` hỏi lại đề tựa ngữ cảnh không có ("cho họ như lần trước") trước intake;
  `strip_json_fences` lấy object JSON đầu tiên trọn vẹn; extractor slot ép value là một
  mã cho phép khi có gợi ý, và model trả rỗng thì hỏi lại thay vì lưu nguyên câu.
- Vòng đo review sâu (12 lượt self-check/soát chéo trên artifact sạch, dump thô): model để lộ
  phần cân nhắc vào content rồi mới in JSON cuối → `strip_json_fences` lấy object trọn vẹn
  CUỐI khi object đầu hỏng; provider trả rỗng hẳn (0 reasoning) → guard `_said_nothing` gọi
  lại; suy nghĩ đốt trần 16k → KHÔNG gọi lại; `DecomposedTask` đánh số `step_id` thiếu;
  `vietnamese_text.foreign_letters` cách ly note advisor trượt ngôn ngữ; fixture
  office_choice sửa tiền đề (khuyến nghị B mâu thuẫn số liệu).
- Ghi upstream phục vụ lời gọi: OpenRouter xoay alias qua nhiều provider theo từng call →
  `_stream_completion` mang `provider` từ chunk sang body, `LlmResult.provider`, sự kiện
  `llm_response`, cảnh báo guard nêu tên; bench `roles` đóng dấu ` @<provider>` lên từng
  lượt, báo `providers`/`fails_by_provider` theo role. Lượt #3 (9 lỗi/168 call, 5 ở
  OpenInference/17) lộ 4 slip vá bằng code: `confidence` ngoài 0..1 clamp, `notes` chuỗi →
  list, `acceptance` list → chuỗi, `APIError` giữa stream ("Upstream error … stream
  failed") retry như timeout. Ghim từng upstream chạy thử (self-check ×4 + soát chéo ×4
  mỗi provider) lộ slip thứ 5: verdict chấm đủ tiêu chí nhưng quên `passed` → suy ra từ
  `failures`/`criteria`.
- Cổng: offline 4720 passed; reliability k=5 8/8; journey j1+j2 4 passed 185 s; live full
  65/74 → 9 ca chạy lại 5/9 → 4 ca chạy lại sau fix s1/a1/a2 xanh, b4 đỏ (lỗi #9: đề "cho họ như lần trước" vẫn tạo hàng planning) → vá cổng `brief_context_gap` → b4 chạy lại xanh (1/1, 323 s).

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Không dùng effort `low` làm mặc định | 2/5 trả rỗng, toàn bộ completion là reasoning lỗi; `off` 3/3 sạch | Role cần suy luận vẫn trả giá thời gian ở `model` |
| Guard trả-rỗng gọi lại CÙNG request thay vì tắt suy luận | Tắt suy luận trên prompt có cấu trúc trả văn xuôi (intake fail-open tạo việc) và một decompose 903 s; rỗng là ngẫu nhiên (2/51) | Lượt hai vẫn có thể rỗng → caller xử lý rỗng |
| Không gọi lại khi suy nghĩ đốt trần `max_tokens` | Gọi lại y hệt đốt trần tiếp 5/6 (10 phút, $0,004 mỗi lượt); effort `low` và `reasoning.max_tokens` đo không chặn được suy nghĩ của model này | self_check fail-open, review qua đường lỗi; trần 16k vẫn là 5–11 phút chết |
| Parser lấy object JSON CUỐI khi object đầu hỏng | Dump thô 2/12: object đầu bỏ dở, lan man, rồi "Use the final." + object hoàn chỉnh cuối — đó là câu trả lời thật | Không có object trọn vẹn nào → vẫn lỗi parse như cũ |
| Sửa slip decompose bằng code (PIC, id, boundary, needs_web) thay vì thêm prompt | Prompt đã in đậm quy tắc mà model vẫn phạm 3/9; mỗi lần phạm = một re-prompt 60–300 s | Bench phải chấm qua cùng repair để đo đúng plan CEO thấy |
| Chữ CEO là đặc tả: slot `brief` mất cấu trúc thì lấy nguyên văn | Bản chép của model rơi "(1)(2)(3)" → đổi lane; chỉ thay khi ĐO được mất mát | Tiền tố `team:` đi theo nguyên văn — đã có `_restore_mode_prefix` |
| Ghi provider trước, ghim provider sau | Lượt bench #2 hỏng (review 0,67, sprint_low 0,33, "ư ư ư", tiếng Ba Lan) trong khi cùng prompt 30 phút sau 6/6 sạch; không có dấu provider thì không tách được model/code/định tuyến | Thêm một trường trên mọi kết quả; chưa sửa được gì cho tới khi số đo chỉ đích danh upstream |
| Cổng hỏi-lại bằng code trong preview, không giao cho prompt | Cả prompt phân loại lẫn intake đã dặn "bỏ trống slot chưa rõ", model vẫn điền và viết lại đề trôi chảy (b4 3/3) | Chỉ bắt hình dạng hẹp (≤25 từ, có cụm quy chiếu, không mỏ neo); đề dài "như lần trước" vẫn đi tiếp |

## Vấp & học được
- `max_tokens` làm finish_reason "length" xuất hiện lần đầu → SDK ném exception thay vì trả
  body; test unit bắt được ngay khi giả stream. Thêm trần phải kiểm tra đường cắt.
- Guard "tắt suy luận rồi gọi lại" đo 3/3 sạch trên prompt VIẾT nhưng hỏng trên prompt JSON —
  một fix đo trên một loại prompt không suy ra loại kia.
- Trace live chỉ có trigger/telegram/reply, không có sự kiện LLM → chẩn đoán phải dựa log
  pytest; muốn dựng lại phải bật `-o log_cli`.
- Review "sai" trên artifact sạch hoá ra hai chuyện: fixture có tiền đề mâu thuẫn (khuyến nghị
  B trong khi số liệu C rẻ hơn) và model bịa về input (bảo thiếu khoảng cách B/C dù prompt in
  ra có) — phải dump thô từng lượt mới tách được, điểm bench không nói.
- Lần thứ hai fixture "sạch" sai tiền đề: `CLEAN` sales_trend nói "15tr/tháng chia đều" khi
  đầu vào T5/T6 là 60tr chia 3 — self-check bắt đúng, bench chấm là false fail. Mỗi
  "review sai trên artifact sạch" phải đối chiếu lại fixture trước khi đổ cho model.
- Dấu provider chỉ nói nơi lỗi tụ, không nói tại sao: bench #4 dồn 6/7 lỗi vào Sail
  Research nhưng ghim riêng nó 8/8 đúng, chỉ chậm (soát chéo tới 210 s). `empty` sau guard
  phần nhiều là đốt hết trần suy nghĩ, không phải upstream trả rỗng. Ngoại lệ: prompt slot
  2 giây của util, Sail Research trả thân rỗng 3/6 thật — và fallback nguyên câu biến
  "à để tôi dùng SCRUM nhé" thành framework; đo riêng k=6 mới thấy.
- Bench chạy lại trên code đã vá lại TỤT (review 0,88 → 0,67, sprint_low 1,00 → 0,33) dù
  diff chỉ chạm parser + fixture; probe thô 6/6 sạch 30 phút sau → thủ phạm là định tuyến
  OpenRouter (response `.provider` đổi giữa DeepSeek/OpenInference). Điểm bench một model
  qua alias không tái lập được nếu không ghi upstream.

## Mở / sang sau
- Đã chốt 2026-09-06 (4 vá thêm, xem CHANGELOG): intake gọi lại 1 lần khi JSON rác rồi mới
  fail-open; self-check bỏ finding "thiếu '…'" khi draft chứa nguyên văn cụm đó; đốt trần
  16k → gọi lại 1 lần tắt suy nghĩ VÀ né upstream vừa đốt (đo review tắt suy nghĩ 23/24 đúng,
  1–23 s; nhưng bench k=3 ở HEAD đốt trần 4/4 qua DigitalOcean và gọi lại trên đó 0/4); knob
  opt-in `provider_ignore` (`OPENROUTER_PROVIDER_IGNORE`) cho upstream trả rỗng — không đặt sẵn.
- Bench k=3 chạy lại ở HEAD: util 1,00, review 0,82 "watch" — 9 lỗi gom ở DigitalOcean/
  OpenInference, 0 lỗi ở 8 upstream khác → giữ baseline #5; review tắt suy nghĩ k=6 = 0,89
  "watch" → giữ suy nghĩ mặc định cho review.
- Effort/budget OpenRouter không chặn được suy nghĩ của model này: ghi nhận, không vá.
- Kiểm tra ngôn ngữ advisor mới ở mức ký tự; chưa thấy lọt ca nào nên để nguyên.
