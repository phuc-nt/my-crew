# v86 — Thin tool loop tự chủ thay LangChain create_agent ở react tier
2026-08-18 · ✅ Done (6/6 phase, plan `plans/260818-1053-thin-loop-harness-conventions/`)

## Làm gì
- **Thin loop** (`my_crew/runtime_backends/thin_tool_loop.py` + `typed_tool_specs.py`): vòng lặp tool-calling tự chủ trên OpenAI SDK thay `langchain.agents.create_agent` — wire rules W1-W6 (assistant content `""` không bao giờ null; reasoning passback nguyên văn chỉ ở turn tool-call; tool result rỗng → `(no output)`; cost EXACT từ usage extras OpenRouter; args bịa bị drop + echo lại), typed snake_case specs với required + repair hook, guard length-finish (batch không chạy) + repeat-batch (nhắc thay vì chạy lại y hệt).
- **Dispatch A/B** (`tool_calling_runtime._make_work_override`): `loop_engine: thin|langchain`, default `thin`; LangChain path giữ selectable — quyết định sau bench: GIỮ cờ để còn A/B về sau.
- **Vệ sinh context**: cap hằng số thống nhất + footer continuation, contract tool per-tool ngắn.
- **Đếm lỗi tool-call** (`transcript_evidence.summarize_tool_errors`): 5 lớp (guard/invented_tool/bad_args/repeat_batch/length_batch), mỗi tool_result đếm tối đa MỘT lớp; bench wiring: `StepMetric` thêm tool_calls/errors/kinds, transcript lookup quét cả jail `agents/*/`, bảng `run-sprint-benchmark tasks` thêm cột rounds/tools/t-err.
- **Bench live 3+3 run** interleaved, cùng brief, web thật: thin pass-rate 3/3 = langchain 3/3 (blind judge 3 vote), prompt token rẻ **3.5×** (78k vs 278k/run), wall **1.6×** nhanh (76s vs 124s), tool errors 0/45 vs 0/77, chỉ thin có cost exact ($0.060/run). Report: `plans/260818-1053-thin-loop-harness-conventions/reports/bench-thin-vs-langchain.md`.

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| A/B ở mức engine seam (`_run_work`), không full-task | Prefetch gate trên CÙNG web_search opt-in + brave key với tool loop → live key hoạt động thì prefetch thành công, step route native, không engine nào chạy | Không đo phần pipeline quanh step; đổi lấy cô lập đúng biến engine |
| Marker lỗi pin vào chuỗi producer thật, mỗi result tối đa 1 lớp | Tránh double-count (errors ≤ calls) + test grep marker không grep giá trị (bài học v85) | Đổi message producer phải sửa marker test — chủ đích |
| Giữ LangChain path sau bench | Còn dùng làm baseline A/B; xóa không thu được gì ngoài bớt dep | Dep langchain vẫn trong tree |

## Vấp & học được
- Định bench full-task rồi mới phát hiện: work step chỉ tới ToolCallingRuntime khi prefetch FAIL — nghĩa là tier này trong production là fallback/rework/intervention path, không phải đường chính. Đọc `resolve_step_runtime` TRƯỚC khi thiết kế bench, không sau.
- langchain-r2 đâm trần `recursion_limit=32` phải salvage-synthesize từ 49 message; thin không run nào chạm trần 16 — vòng lặp gọn không chỉ rẻ mà còn ổn định hơn.

## Mở / sang sau
- Answer thin ngắn hơn (~1.2k vs ~2.2k chars) — judge không trừ vì acceptance không yêu cầu độ dài; theo dõi khi đổi brief.
- LangChain transcript vẫn 1 `llm_response` aggregate/loop → bench "rounds" ở path đó chỉ là proxy tool calls.

Suite: 3525 BE + ruff sạch.
