# v35 — Tool-error resilience + memory consolidation
2026-07-13 · ✅ Done (2128 BE)

Backlog #1+#2 từ research 260713 (autonomy/memory/tool-call). Hai phase độc lập, cook 1 phiên.

## Làm gì
- **P1 tool-error resilience**: `tool_error_guard(name, fn)` bọc mọi read-tool ở `_shim` + `_as_lc_tools`. Exception thân tool (network/API) → chuỗi "⚠️ tool X lỗi: …" trả về LLM; `ToolPolicyError` → "bị từ chối" (phân biệt để LLM không retry policy-block). Trước đây exception thân tool NỔ cả graph invoke của create_agent → step failed, mất việc LLM đã làm.
- **P2 memory consolidation**: `src/memory/consolidation.py` — sweep nền 3h sáng rút gọn section AGENT-MEMORY của MEMORY.md (ngưỡng 8000 chars, cooldown 24h/agent) bằng 1 LLM call, validate + archive bản gốc trước khi ghi. `replace_agent_section` (swap thay merge) trong memory_mirror.
- Wiring: `_consolidate_memories_best_effort` trong service.run_tick, best-effort cạnh sandbox reaper, gate hour==3.
- Kiểm chứng sống: E2E P1 (model thật + jira 503 giả → step ra text sạch, $0.0006); LLM thật P2 (18→14 fact, 793→597 chars, dedup + bỏ mục lỗi thời đúng, giữ nghĩa).

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Vá ở tầng my-crew (`_shim`/`_as_lc_tools`), KHÔNG dùng middleware langchain | Spike xác minh pinned create_agent bọc ToolNode chỉ trả `ToolInvocationError` cho LLM; mọi exception thân tool RAISE. Vá tầng mình → không phụ thuộc nội bộ langchain, bản sau đổi API không vỡ | Phải tự re-raise `GraphBubbleUp` (interrupt) — bọc rộng nên cần danh sách loại trừ tường minh |
| Deep tier KHÔNG vá thêm | Sandbox tools của deep đã degrade tại nguồn (Firecrawl/OpenAlex/history mỗi cái `except→"(… lỗi)"`); sandbox exec trả ExecuteResponse không raise | — |
| Consolidation = code gọi 1 LLM call có validate, LLM KHÔNG ghi tự do | Giữ moat guardrail: memory là user-data, LLM không được free-write | Cần validate đủ chặt (marker-injection, shrink, control char, fact-count) |
| Archive nguyên bản trước MỌI ghi + không bao giờ load vào prompt | MEMORY.md user-data — undo tay được; archive không nhiễu prompt | File archive phình dần (chấp nhận: chỉ ghi khi thật sự consolidate, hiếm) |
| Cooldown stamp ON ATTEMPT (không chỉ khi thành công) | Model lỗi/output rác không được gọi lại mỗi tick trong đêm | — |

## Vấp & học được
- Reviewer subagent chết giữa chừng (limit Fable 5) — tự hoàn tất review: ruff (7 E501 + 1 unused-import ở code MỚI, sửa hết; repo có 10 E501 cũ nhưng code mới phải sạch) + tự soi adversarial (classify audit vẫn fire trước khi block→string; không caller nào phụ thuộc ToolPolicyError raise; archive không bị load; marker-injection bị `replace_agent_section` re-emit 1 cặp sạch + `_validate` chặn).
- Ngưỡng 8000 là no-op hôm nay (fleet MEMORY.md mới 69–249 bytes) — chủ đích, dành cho agent già; đã ĐO thật trước khi chốt số.

## Mở / sang sau
- #3 structured-output (đã vá tạm strip_json_fences) + #4 semantic-recall (chờ đo ngưỡng đau) vẫn hoãn.
- v36 (storage hygiene + template hybrid) đã plan xong, chờ cook.
