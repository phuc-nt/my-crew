# Một model cho cả fleet — scorecard theo role, policy suy luận, 15 lỗi vá
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
  `strip_json_fences` lấy object JSON đầu tiên trọn vẹn.
- Vòng đo review sâu (12 lượt self-check/soát chéo trên artifact sạch, dump thô): model để lộ
  phần cân nhắc vào content rồi mới in JSON cuối → `strip_json_fences` lấy object trọn vẹn
  CUỐI khi object đầu hỏng; provider trả rỗng hẳn (0 reasoning) → guard `_said_nothing` gọi
  lại; suy nghĩ đốt trần 16k → KHÔNG gọi lại; `DecomposedTask` đánh số `step_id` thiếu;
  `vietnamese_text.foreign_letters` cách ly note advisor trượt ngôn ngữ; fixture
  office_choice sửa tiền đề (khuyến nghị B mâu thuẫn số liệu).
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

## Mở / sang sau
- `sprint_intake` fail-open vẫn tạo việc từ JSON rác thật sự (đã bớt ca "Extra data") — cân nhắc
  hỏi lại CEO sau 2 lượt hỏng.
- review/clean vẫn báo lỗi giả do model bịa về input (không phải parse): cân nhắc `role_models`
  riêng cho review; effort/budget OpenRouter không chặn được suy nghĩ của model này.
- Kiểm tra ngôn ngữ advisor mới ở mức ký tự; trượt sang tiếng Anh thuần ASCII chưa bắt.
