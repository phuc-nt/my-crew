# Degrade-and-continue + routing guard — và vòng review đè lên bước đã bỏ qua
2026-08-28 · ✅ Done · chưa release-ready

## Làm gì
- P1 skip-with-gap (`fc6ebf4`): bước chết (failed/timeout/needs_decision) được
  `drop_step_with_placeholder` đóng dấu done-không-lease + artifact placeholder,
  task đi tiếp và giao kèm header khoảng trống thay vì stall trắng tay.
- P2 routing guard (`05675b1`): `_MAX_DEGENERATE_STEPS = 3` + check chain thẳng
  một người — decompose suy biến bị kéo về sprint.
- Fix vòng review đè bước đã drop (`213f119` + `ee57ce3`): `is_dropped_step`
  (done ∧ attempt_id rỗng — chữ ký độc quyền của `mark_step_dropped`) gác cả 3
  cổng mint review: `effective_needs_review` (thắng mọi band, kể cả supervised),
  `maybe_handle_review_done` (parent drop → kết thúc chuỗi; chính review row bị
  drop → kết thúc chuỗi), `maybe_insert_review_after_rework` (rework row bị drop
  → không mint vòng kế). 6 test `tests/test_review_over_dropped_step.py`.
- Bench 3 run (lanes9/9b/9c, 2 case × 2 lane): số đo + nguyên nhân từng case ghi
  ở `plans/260825-1509-fast-crew-lane-routing-v2/reports/bench-260827-two-lane-quality-judge.md`.

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Chữ ký drop = done ∧ lease rỗng, không thêm cột | Sweep xác nhận mọi mark_done production đều qua reserve (lease luôn có); khỏi migration | Fixture test dựng done tay phải reserve trước, 5 file test phải sửa |
| Guard `hasattr(attempt_id)` fail-open về "không drop" | Object pre-persist/`TeamStepPlan` không có field lease; "không biết" thì thà thừa 1 review | SimpleNamespace thiếu field không bao giờ được coi là dropped |
| Chặn mint ở upstream, giữ nguyên `locked_version` runner | Mint là gốc; sửa runner chỉ che triệu chứng stale | Review mint TRƯỚC drop vẫn dispatch 1 lần vô ích rồi mới kết thúc |
| Không vá reviewer flip-flop trong phase bench | Bench là bench — finding mới ghi lại, không vá nóng (rule risk-note từ v81) | lanes9b kẹt 3/4 case vì lớp này |

## Vấp & học được
- Review mint dù `needs_review=0`: manh mối là CHỈ bước analyst bị — band store
  thật của repo (analyst=supervised) leak vào bench qua `settings.DATA_DIR`;
  `effective_needs_review` với band supervised bỏ qua hoàn toàn cờ per-step.
  Supervised là config hợp lệ → bug production thật, không phải artifact bench.
- Fix H1 làm lộ vòng lặp bậc hai: drop retire lease → `locked_version=''` không
  khớp version placeholder → review stale → verdict None → mint lại CÙNG vòng →
  6 re-review đốt sạch budget trên task mà content đã done 100%.
- Reviewer M1/M2 đúng: CEO `drop_stalled_step` không lọc step_type nên drop
  được cả review/rework row — hai cổng còn lại cũng phải gác, thêm 2 test.
- Post-fix lộ 2 failure mode mới: reviewer flip-flop khi đề có 2 đáp án tùy định
  nghĩa (YouTube vs Zing MP3) → hết cap rework → stall dù content xong; và gap
  cascade — skip bước research đầu chuỗi thì bước tổng hợp cuối thiếu input,
  worker thú nhận bịa số rồi fail trung thực.

## Mở / sang sau
- Reviewer flip-flop → stall-at-cap: cân nhắc "hết cap thì giao kèm ghi chú
  reviewer" thay vì stall, hoặc verdict phải chỉ ra tiêu chí bất định.
- Gap cascade: cap số gap / chấm whole-block (option C) — đo thêm rồi quyết.
- Re-mint verdict-None không truyền `source_step_id` → review vòng ≥1 chấm
  artifact content, trái docstring `_insert_review_step` (L, tồn tại từ trước).
- Bench driver nên tự chọn band store thay vì ăn theo `.data/` của repo.
