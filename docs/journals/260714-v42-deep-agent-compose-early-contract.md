# v42 — deep_agent compose-early contract (step-budget §9)
2026-07-14 · ✅ Done (2245 BE)

Benchmark-lại (sau vá file-write v40 + lease v41) xác nhận hết crash + hết chết-lease, NHƯNG lộ nút thứ 3: ~25% run research chạy XONG thu thập nguồn (`write_todos` = completed) nhưng đụng trần recursion-loop ĐÚNG lúc chuẩn bị viết report → reply chỉ còn "Let me compile the report" + todo, KHÔNG có báo cáo. Nguyên nhân: **misallocation budget** — dồn hết vòng cho research, không chừa cho compose.

## Làm gì
- **Prompt-contract "viết sớm + refine"** (phương án (a), rẻ nhất): hằng `_DEEP_AGENT_COMPOSE_CONTRACT` nối vào `system` prompt **CHỈ** trong `run_deep_agent_work` (deep_agent). Nội dung: ngay khi có 1 vòng nguồn đủ dùng → ghi BẢN NHÁP report ra `/work/*.md` TRƯỚC (write_file), rồi refine; tuyệt đối không dồn viết ở cuối; luôn đảm bảo /work có 1 file .md report ở mọi thời điểm.
- **0 code lõi**: recursion_limit = `max(2, loop_limit*2)` giữ NGUYÊN (bounded loop = guardrail red-team). Không đụng gateway/sandbox/sanitizer/invariant. Không đụng `build_team_step_messages` (dùng chung nhiều tier).
- **3 unit test** fake deepagents/langchain import → chứng minh contract nối đúng vào `system_prompt` truyền cho `create_deep_agent` (append, không prepend/interleave), không rò số recursion vào prompt.

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Chọn (a) prompt-contract, KHÔNG (b) inject-nhắc-cuối-loop / (c) nâng loop_limit | Rẻ nhất (0 code lõi), giữ bounded loop; report ưu tiên (a), đo lại rồi mới leo thang | Phụ thuộc model tuân prompt — nhưng đã UAT thật xác nhận |
| Contract chỉ ở tier deep_agent, không vào prompt chung | Chỉ deep_agent có sandbox + write_file; native/create_agent không có file để ghi → thêm vào prompt chung là nhiễu | Nối string ở loop thay vì prompt-builder |
| Không rò số recursion (32) vào prompt | Giữ loop-cap là chi tiết nội bộ; agent chỉ cần biết "viết sớm", không cần biết trần | — |

## Vấp & học được
- **`qwen/qwen-3.7` (comment fallback trong .env) KHÔNG phải model-id thật** → OpenRouter 400. Query `/models` lấy id thật `qwen/qwen3-coder` (agentic tool-calling) cho UAT.
- **exit-0 ≠ PASS**: run đầu traceback bị langgraph nuốt-rồi-raise, script vẫn thoát rồi báo lỗi ở stderr — phải đọc output thật, không tin mỗi exit code.
- **UAT thật (Docker + qwen3-coder)**: report 150 từ đầy đủ (3 xu hướng + nguồn) NẰM TRONG reply — đúng thứ trước đây mất. `read-back merged=False` là OK: lần này agent viết thẳng vào reply thay vì file; mục tiêu (report tồn tại, không mất) đạt cả 2 đường. Read-back v41 vẫn là lưới an toàn cho đường ghi-file.

## Mở / sang sau
- Nếu benchmark-lại vẫn còn run mất report → mới làm (b) reserve-budget (inject nhắc khi còn ~2 vòng) hoặc (c) nâng loop_limit có cap. Chưa cần (YAGNI).
