# v28 — Runtime consolidation: migrate tools-tier loop to `create_agent` + DRY
2026-07-12 · HOÀN TẤT (1871 BE + 178 FE xanh, ruff/tsc sạch; live UAT 3-engine model thật; code-review SHIP)

## Làm gì
Scope THU HẸP sau red-team 4-reviewer (bỏ taxonomy churn + cắt report path). Chỉ 3 việc:
- **DRY loop core** (`community_loop_core.py` MỚI): `record_loop_result` (post-invoke tail chung: text + `sum_usage_metadata` + `estimate_cost` + `telemetry.record`) + `invoke_capped` (recursion cap + catch `GraphRecursionError`→degrade empty + tracing-off). react_loop + deep_agent_loop cùng gọi. Cố tình KHÔNG gộp agent-build/system-prompt (mỗi tier tự sở hữu).
- **Migrate tools-tier** `langgraph.prebuilt.create_react_agent` → `langchain.agents.create_agent` (community-standard). Shell-tier `deepagents.create_deep_agent` GIỮ NGUYÊN.
- **Deps**: `langchain>=1.3,<1.4` vào base `[dependencies]` (trước chỉ vào qua extra `deep`).

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Cắt report-for-community + giữ 2 kind (không taxonomy `community`) | Red-team: `.build_report()` dead-code 0 caller; report thật qua `pack.report_kinds`. Taxonomy = churn đổi-tên 0 lợi ích chức năng, blast radius lớn | Report vẫn native-only; "chuẩn cộng đồng" chỉ ở factory, không ở taxonomy |
| Giữ multiplier recursion `*2` (không hiệu chỉnh) | Đo empirical: create_agent VÀ create_react_agent đều 8 vòng ở limit=16 — parity | — |
| `invoke_capped` catch-degrade empty | GraphRecursionError vượt cap → step FAILED cứng (sẵn có cả 2 factory); degrade→deliver rỗng tốt hơn | Mất output khi overflow (nhưng không FAILED) |
| `_tracing_off()` env-blank thay `callbacks=[]` | `callbacks=[]` KHÔNG tắt tracer — CallbackManager tiêm LangChainTracer từ env | Mutate os.environ process-global (an toàn: 1 loop/subprocess) |

## Vấp & học được
- **`callbacks=[]` KHÔNG tắt LangSmith tracer** (kiểm-độc-lập bắt trước code-reviewer): khi `LANGCHAIN_TRACING_V2=true`, `CallbackManager.configure` vẫn tiêm `LangChainTracer` từ env bất kể callbacks list. Fix đúng: blank env quanh invoke (`_tracing_off` context manager) → 0 handler (verified). Test phải assert `tracing_is_enabled()` THẬT, không assert config dict.
- **Đo lúc cook đảo 2 finding red-team**: RT-1 (recursion mất vòng) SAI — parity thật; RT-3 (langsmith là hồi quy v28) SAI — `langgraph.prebuilt` production đã kéo 28 module langsmith từ trước. Red-team hữu ích để BẮT ĐIỂM CẦN ĐO, không phải kết luận cuối — đo thật mới chốt.
- **Live test cap giả-định quá chặt**: test đầu dùng `rounds*2=6`, model thật chatty → overflow. Cap runtime THẬT = `MAX_LOOP_STEPS*2=16` rộng hơn. Test N-round phải dùng cap runtime thật, không cap tự-bịa.

## Mở / sang sau
- `_tracing_off` giả định 1 loop/process (team-step chạy subprocess riêng — an toàn nay). Fan-out in-process tương lai cần per-invoke isolation.
- Degrade path ghi `cost_source="estimated"` với token None (nhất quán pre-refactor, không hồi quy) — dọn sau nếu cần độ chính xác provenance.
