# v26 — Capture Telemetry + Session Log thống nhất
2026-07-12 · HOÀN TẤT (1842 BE + 178 FE xanh, ruff sạch, UAT 3-engine live LLM: 6 capture rows đủ field)

## Làm gì
- **Bảng `captures` riêng** (`capture_store.py`, `.data/captures.sqlite3`) — port "capture tầng 1"
  của my-dandori: 1 row/step-ATTEMPT (grain = `attempt_id`, `reserve_step` cấp mới mỗi spawn kể
  cả review/rework). 17 cột: ai/việc/engine/status/step_type/cost/tokens/timing. Pattern
  team_task_store (WAL + busy_timeout multi-writer, CREATE IF NOT EXISTS). Internal-only, KHÔNG
  qua Action Gateway.
- **Session log thống nhất (unify cost)** — 2 engine langchain (create_agent, deep_agent) trước
  trả `cost=None` (ChatOpenAI bypass LlmClient). Nay: SUM `usage_metadata` qua mọi AIMessage ×
  giá per-model (`model_pricing.py` + `config/model_prices.yaml`) → `cost_source=estimated`;
  native giữ cost thật OpenRouter → `exact`. Model thiếu giá → cost=None, tokens vẫn ghi.
- **Side-channel collector** (`step_telemetry.py`) — `run_work` là contract 2-tuple `(text,cost)`
  CỨNG; tokens+cost_source đi kênh phụ `StepTelemetry` (kwarg như search-hook), không phá tuple.
- **Hook + timing** tại `run_team_step` (3 engine hội tụ) — `time.monotonic()` bao quanh work
  TRONG worker process (không `spawned_at` cross-process); `_record_capture` best-effort
  log-WARNING-không-raise.
- **Remember-node cho team-step** — rewire `deliver→remember→END` (tái dùng `add_remember_node`,
  trước chỉ report graph). Extract từ `result_text` (OUTPUT, không chạm PII-gate chặn INPUT);
  `CostedMemoryExtractor` cộng cost extract vào `cost_usd` → capture trung thực (work+memory).

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Bảng captures RIÊNG (không cột team_steps) | Tách concern telemetry vs task-state; dễ mở ROI sau | 1 DB nữa (đã theo path team_tasks) |
| Cost 2 engine = token×giá config | usage_metadata có sẵn, không cần tiktoken; luôn có số | Giá config PLACEHOLDER, operator verify vs OpenRouter |
| native=exact + cột cost_source | Giữ độ chính xác đang có; learn biết độ tin | cross-engine grade PHẢI tách theo source |
| Remember gộp v26 + cộng cost vào capture | Nếu bỏ cost extract → row 'exact' nói dối (red-team F4) | memory_node phức tạp hơn (costed flag) |
| Team-step remember = MEMORY.md-only | build_team_task_graph chưa có store seam; sibling cross-read defer (YAGNI) | Không cross-read Store trong v26 |
| KHÔNG git-delta/grading/flywheel/UI | my-crew office-task; flywheel governance cho fleet ≠ one-person | Tầng 2/3 để sau |

## Vấp & học được
- **Code-review bắt CRITICAL suite xanh giấu (C1)**: `_run_review` gọi với `telemetry=` nhưng
  signature không nhận → TypeError MỌI review step production. Suite xanh vì 0 test drive review
  qua `run_team_step` (chỉ work step + review-store trực tiếp). Bài học: green suite ≠ path
  covered; thêm test drive đúng nhánh review. Fix 2 dòng + regression test.
- **Worker spawn subprocess → picks up disk code**: UAT chạy dưới coordinator cũ (PID load
  trước fix) nhưng review row VẪN capture đúng — vì mỗi step spawn subprocess re-import từ đĩa.
  C1 fix có hiệu lực ngay không cần restart coordinator.
- **Red-team F2 phát hiện bug tiềm ẩn có sẵn**: `external_write` (team_step_runner.py:294) splat
  vào build_task như kwarg lạ — TeamTaskDeps FIELD không phải build_team_task_graph param, KHÔNG
  runtime nào pop. Sống được CHỈ vì `_resolve_external_write` trả None mọi agent (đường egress
  chết). Không viện dẫn làm precedent; seam telemetry thêm param TƯỜNG MINH (F1).
- **getattr-tolerant cho test double**: native `_run_work` fill collector từ `result.prompt_tokens`
  — `_FakeResult` trong test cũ không có → `getattr(result,'prompt_tokens',None)` (honest degrade,
  không crash test/production LlmResult vẫn có field thật).

## Mở / sang sau
- **Grading/ROI (tầng 2)**: đọc captures → grade per-engine (calibrate TRONG-engine, KHÔNG
  cross-engine vì deep_agent đắt/chậm theo thiết kế). Chỉ sau khi captures đủ dữ liệu.
- **Sibling cross-read Store cho team-step remember**: thêm store seam vào build_team_task_graph.
- **Giá model_prices.yaml**: placeholder — operator verify vs OpenRouter thật.
- **Failed-path cost=None** (M1): step fail sau khi tiêu consult/rework → cost mất khỏi capture
  (nhất quán với mark_failed). Cân nhắc thread state cost nếu cần.
