# v43 — deep-team in-sandbox coordination
2026-07-14 · ✅ Done (2267 BE)

Ảnh benchmark báo "MPM team-of-deep-agents CHƯA support — dispatch step tới deep_agent raise Phase 2/3". Verify code: **premise phần lớn SAI** — deep_agent ĐÃ chạy như 1 team-step, ĐÃ propose split (đẻ sub-team native), "Phase 2/3 not implemented" CHỈ ở đường report. Chốt với CEO: làm **Mức 2** — cho deep_agent điều phối trợ lý con TRONG sandbox (deepagents `task` tool đã ON sẵn + moat-clean) cho tử tế: opt-in + trung thực cost + chặn wall-time.

## Làm gì
- **Flag `deep_team` opt-in** (theo pattern web_search/academic_search/gws_context) → wire profile→team_step_runner→DeepAgentRuntime→run_deep_agent_work. Khi bật: pass 1 declarative `general-purpose` subagent spec (compose-early one-level-down) + prompt clause "giao ≤3 việc con, mỗi con ghi /work/<tên>.md".
- **Cost-honesty (P2)**: `UsageMetadataCallbackHandler` gắn ở `invoke_capped` → bắt token CẢ cha + trợ lý con (langgraph propagate callback vào nested subagent.invoke); `record_loop_result` lấy tổng từ handler thay messages-walk. None-path giữ nguyên (native/create_agent/non-deep-team byte-identical). UAT thật: handler bắt 156k-219k input token (>> parent-only → chứng minh gộp token con).
- **Hard-cap (P3)**: `TaskCapMiddleware.wrap_tool_call` đếm `task` call, từ chối quá 3 bằng error ToolMessage (không gọi handler). deepagents không có knob sẵn → middleware qua `middleware=` param (không fork).

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Làm Mức 2 (in-sandbox subagent), không Mức 1 (native fan-out đã có) | Niche thật: 1 report cần sub-câu-hỏi ngữ cảnh lớn riêng biệt (context-siloing) — native split không phục vụ (sub không phải deliverable riêng) | Cost gộp không tách nhãn |
| Chỉ declarative SubAgent spec, cấm CompiledSubAgent/AsyncSubAgent | Declarative không có field backend → deepagents ép qua sandbox backend của cha (moat); Compiled mang runnable riêng, Async = remote LangSmith off-moat | — |
| Cost gộp 1 total/step (không breakout per-subagent) | Đủ giữ bất biến v26; breakout cần callback riêng, ROI thấp | Không soi được cha vs con |
| Cap cứng 3 (hằng số, không config) | YAGNI; prompt bó + compose-early là lớp mềm, middleware là backstop | Chưa cho chỉnh per-agent |

## Vấp & học được
- **Review bắt High THẬT trong chính cơ chế an toàn**: `TaskCapMiddleware._count` KHÔNG thread-safe — docstring tôi tự viết "sequential sync execution" SAI: langgraph ToolNode chạy parallel tool-call trên thread pool. Nếu model phát 2 `task` cùng lượt → race, cap có thể vượt. Vá: `threading.Lock` quanh check-increment (như UsageMetadataCallbackHandler tự làm) + test 24 thread. Bài học: đừng khẳng định "race-free" khi chưa đọc executor thật.
- **Bug latent tiền-v43**: `DeepAgentRuntime.build_task` KHÔNG pop `gws_context` (v39 thêm vào _extra cho mọi non-native) → leak vào `build_team_task_graph` (chữ ký cố định) → mọi deep_agent team-step THẬT crash TypeError. Chưa lộ vì UAT v40-42 gọi thẳng run_deep_agent_work bỏ qua build_task. Vá + regression test.
- **UAT lộ 404 flaky (~33%)**: trợ lý con song song race exec → `exec_run` transient lỗi → `execute()` KHÔNG guard → raise chết cả run. Không phải OOM (diagnostic: OOMKilled=False, container running lúc pass). Vá: guard `execute()` degrade-to-error ExecuteResponse (như upload/download đã guard). Sau vá: 2/2 probe PASS (trước 0/2). Bài học: guard mọi exec container, không chỉ file I/O.
- **cost=None lúc UAT KHÔNG phải bug**: qwen3-coder vắng trong price table → estimate_cost trả None trung thực (cả baseline). Fold đúng ở tầng TOKEN (đã đo 156k-219k), không phải tầng giá.

## Mở / sang sau
- Thêm giá qwen3-coder vào model_prices.yaml (cần giá OpenRouter thật, không bịa) để cost ra số.
- Cap `_MAX_TASK_CALLS` per-agent config nếu có task cần >3 nhánh.
- Điều tra sâu vì sao container thi thoảng bị remove lúc parallel exec (guard đã che triệu chứng; chưa rõ cái gì remove — auto_remove/teardown race).
