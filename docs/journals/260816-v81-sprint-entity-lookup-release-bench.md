# v81 — Sprint entity-lookup v2 + release bench 4 trục
2026-08-16 · ✅ Done

## Làm gì
- Parser entity cho sprint goal v2 (`sprint_runner.py`): nhận prose-list sau "của" (opt-in `prose=True`), goal deliverable-head ("Tóm tắt ngắn về…" → tiêu thụ head + lead-in, còn chủ đề thật), phrase-governor back-off khi word-cut cắt đôi "gói cá nhân", prose-list KHÔNG có "và" (floor 3 tên viết hoa; 2 tên vẫn cần connector).
- Bench release 4 trục (`my_crew/bench/release_bench.py` + `scripts/run-sprint-benchmark.py release`): 8 brief-case chuẩn (2 case mới = goal intake-rephrase live verbatim), 3 lần lặp check determinism, JSON so sánh được giữa revision.
- Đo thật vs v0.10.0 cùng brief C3: baseline stall 2 lần ($0.0915 mất trắng, 1 query kitchen-sink); candidate done/delivered 5.6 phút sprint, $0.0544, 5 query trúng đích. Offline 8/8 đóng coverage (baseline 4/6). Report: `plans/reports/benchmark-260816-1325-sprint-lookup-v2-vs-v0100-report.md`.
- Web song song (Task B): design report redesign (`plans/reports/brainstorm-260816-1457-web-redesign-sprint-features-design.md`) + 2 fix — artifact panel nhận step `sprint` là delivered (`DELIVERED_STEP_TYPES` mirror server), feed filter "Bước" giữ `step_activity`.

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Fix parser bằng goal live verbatim, không phải paraphrase | Paraphrase từ trí nhớ pass/fail khác hẳn goal thật — đã vấp | Phải query DB lấy text |
| 2 case bench mới đóng băng từ 2 lần intake-rephrase live | Intake rephrase không deterministic — mỗi biến thể là 1 shape parser phải chịu | Suite gắn với intake hiện tại |
| Floor 3 tên cho list không connector | 2 tên + phẩy quá dễ là câu thường ("Notion, Figma là…") | List 2 phần tử mất "và" sẽ bị bỏ qua |
| Không judge mù v78 lần này | Baseline không có deliverable (stall notice) — không có gì để so mù | Trục chất lượng chấm trực tiếp theo acceptance |

## Vấp & học được
- **A/B tự nhiên trong 1 task**: attempt-1 spawn trước khi fix land → chạy code cũ, fail đúng kiểu cũ; attempt-2 worker mới import repo editable → 5 query, done. Cùng brief cùng model — bằng chứng sạch nhất cả đợt, không cần dựng thí nghiệm.
- Transcript per-attempt (v80) ghi vào data-dir CỦA AGENT (`.data/agents/<actor>/artifacts/team-tasks/…`), không phải root — mất một hồi tưởng transcript không ghi; `lsof` trên worker pid mới lộ. Route transcript-tab web sau này phải resolve theo actor.
- Verify bằng text thật từ DB, không tự dựng lại goal: bản paraphrase trả entities rỗng trong khi goal thật pass.

## Mở / sang sau
- Task B phase A/C/D: api-cache + paginate + N+1, surface sprint (badge/route_json/transcript tab/metrics), i18n + test.
- `over_cap` searches 8→14 đúng thiết kế scaled-cap nhưng đáng theo dõi cost brief nhiều entity.
