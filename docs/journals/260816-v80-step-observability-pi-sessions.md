# v80 — Quan sát bước làm việc kiểu pi-sessions: transcript, replay, review/reflection có bằng chứng
2026-08-16 · ✅ Done (5/5 phase, plan `plans/260816-0854-step-observability-pi-sessions/`)

## Làm gì
- **P1 Transcript per-attempt**: mỗi attempt team-step ghi một JSONL (`.data/artifacts/team-tasks/<task>/transcripts/<step>-<attempt>.jsonl`) qua `StepRecorder` contextvar — 3 hook (`LlmClient.complete`, `community_loop_core`, `collect_prefetch`) ghi nguyên văn request/response/tool/prefetch; scrub secret khi ghi; không bao giờ làm hỏng step; hygiene quét sau 30 ngày.
- **P2 Work-order + replay**: artifact `work-order.json` đóng băng đầu vào của attempt + CLI `step-replay` chạy lại một bước ngoài pipeline để chẩn đoán.
- **P3 Review có bằng chứng quá trình**: `transcript_evidence` render tool đã gọi + nguồn đã mở + usage vào prompt peer-review (cap 8000, 0 = tắt) — review chấm quá trình thật thay vì tin lời văn (bài học v72: bảng giá bịa well-formed).
- **P4 Feed hoạt động sống**: recorder bắn `step_activity` (allowlist cứng `{agent, task, step, tool, count, phase}`) vào office room — office thấy "đang gọi web_search (2)" / "đang viết…" giữa hai step_status; FE render 2 dòng i18n vi/en.
- **P5 Reflection + bench**: reflection nhận behavior summary (CHỈ tên tool + số đếm, cap 4000); bench `load_task_metric(..., data_dir=)` phân rã usage LLM per-step từ transcript, ledger vẫn là nguồn sự thật kế toán.

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Transcript là file phụ (best-effort, swallow mọi lỗi ghi) chứ không phải bước pipeline | Quan sát không được phép giết việc thật | Gap im lặng khi đĩa lỗi — chấp nhận |
| Reflection chỉ nhận tên tool + số đếm, không args/kết quả/query | Output reflection ghi vào memory bền mọi sibling đọc — điểm inject giá trị nhất | Bài học thô hơn (không thấy nội dung), đổi lấy an toàn |
| `step_activity` allowlist cứng trong code, không phải filter | PII invariant giữ bằng cấu trúc — không tồn tại code path mang nội dung tới feed | Muốn thêm field phải sửa code, đó là chủ đích |
| ScriptedLlm của fullflow tự ghi `record_event` như seam thật | Double phải trung thực với contract mới của seam, transcript mới sống trong kịch bản fullflow | Harness biết thêm 1 chi tiết của product |

## Vấp & học được
- Refactor `_parse_events` để lại `if not parsed_any` mồ côi trong `extract_review_evidence` → NameError chỉ lộ khi chạy suite cũ. Test cũ chính là lưới an toàn của refactor — chạy chúng ngay sau refactor, đừng đợi đến cuối phase.
- Fullflow lộ bug harness có sẵn: module import GIỮA test (worker, do spawn patch kéo vào) bind bản double của test 1; teardown không biết attr đó, test 2 chạy với cast/data_dir của test 1. Fix bằng marker `_fullflow_double` để sweep nhận cả double sót. Bài học: patch-by-identity mù với module sinh sau khi patch.
- Test fullflow v80 là test đầu tiên đọc artifact theo `settings.data_dir` xuyên test — các test trước chỉ đọc store/outbox nên bug ngủ yên cả v79.

## Mở / sang sau
- Deep-tier `llm_response` là aggregate per loop → `llm_calls` bench ở đó là per-attempt, chưa per-exchange.
- Transcript chưa có surface đọc trên web UI (mới CLI replay + review/reflection tiêu thụ).

Suite: 3320 BE (9 fullflow) + 284 FE, tsc/ruff sạch.
