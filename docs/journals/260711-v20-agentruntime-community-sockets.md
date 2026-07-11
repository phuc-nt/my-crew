# v20 — AgentRuntime multi-runtime + community sockets
2026-07-11 · HOÀN TẤT (1768 BE + 177 FE xanh, ruff/tsc sạch, E2E LLM thật)

## Làm gì
- **AgentRuntime seam** (`src/runtime_backends/`): tách agent-loop khỏi điều phối. Protocol
  2-method; `resolve_runtime` chọn backend theo `agent_runtime:` (field TOP-LEVEL riêng, không
  đụng `runtime:` infra). `NativeGraphRuntime` byte-identical; `RUNTIME_FORCE_NATIVE` kill-switch;
  None→native; report-guard fail-loud non-native (đóng "âm thầm native" 4 caller).
- **ToolCallingRuntime**: tool-calling loop qua `create_react_agent` (langgraph tree, +dep
  `langchain-openai` — KHÔNG `langchain` full). Swaps CHỈ `run_work` (`build_team_task_graph(
  work_override=)`) → deliver→gateway giữ native = invariant #1 bằng cấu trúc. Positive
  read-allowlist + classify shim mọi tool + audience-aware + per-loop recursion cap.
- **DeepAgentRuntime**: optional/experimental, lazy import (app không cần dep), fail-loud sớm.
- **3 ổ cắm community**: skill agentskills.io folder-form (trust theo provenance) · pack-MCP
  spawn gate (default-deny + env scrub) · `_template-pack` + PACK-AUTHORING.md.

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| ToolCallingRuntime swaps chỉ run_work | deliver→gateway giữ native → invariant #1 KHÔNG cần logic mới | loop chỉ thay tầng "work", không toàn graph |
| `create_react_agent` (langgraph) + langchain-openai, KHÔNG langchain full | `create_agent` không có trong langchain-core, relocate v1.1.0, kéo meta-package churn (red-team C3) | langchain-openai là dep mới nhẹ |
| positive read-allowlist, KHÔNG denylist | pack write-allowlist là permit-list 11 tool → complement vẫn chứa deletePage (red-team C2) | phải liệt kê tay tool read |
| classify shim mọi in-loop tool | tool-calling loop = egress path 2 gateway không thấy (red-team C1) | mỗi tool call thêm 1 classify |
| DeepAgent refuse chạy tới khi vendor-review | deepagents ship shell middleware + network dep in-process với gateway+token (red-team C5) | deep_agent chưa dùng được thật (create_agent thay thế) |
| researcher-pack → template skeleton | team-step + web_search đã phục vụ researcher (red-team Y2) | không có researcher graph riêng |
| `agent_runtime:` field riêng | `runtime:` đã là infra block M2-P8 ở 10 profile (red-team H1) | thêm 1 top-level key |

## Vấp & học được
- **Red-team 4 reviewer bắt kế hoạch gốc PHÁ moat**: bind tool vào loop = egress path 2 gateway
  không thấy; read_only_toolset denylist để deletePage lọt; deepagents shell. Giữ 3 runtime theo
  ý CEO NHƯNG áp fix thiết kế → moat nguyên. Red-team-plan-trước-cook lần nữa cứu cả kiến trúc.
- **E2E LLM thật là bằng chứng quyết định**: chạy react loop với model thật → model GỌI tool
  `github.prs` → `classify` THẤY tool call. Chứng minh egress-path-2 đã đóng bằng thực thi, không
  chỉ assert design (red-team C1 dặn "test instrument, không chỉ design").
- **StructuredTool schema**: `_call(args=None)` không nhận kwargs model gửi → đổi sang `@tool`
  1-string `query`. Loop chạy thật mới lộ.
- **create_agent thật sự không có** trong stack (langchain-core only) — red-team C3 đúng; fallback
  `create_react_agent` (langgraph) là đường đúng, không kéo meta-package.

## Đính chính (2026-07-11, sau red-team v20.5)
- Câu "team-step output → deliver→gateway" trong journal này là **over-claim**. Sự thật:
  team-step deliver CHỈ ghi artifact nội bộ; hook `external_write` (để step egress công ty)
  đã thiết kế nhưng CHƯA nối (`deps.external_write=None`, grep=0 chỗ gán). Egress công ty đi
  qua **report graph** (wire gateway đầy đủ). → v20 KHÔNG có lỗ hổng (team-step vốn không ra
  ngoài được); nhưng "invariant #1 giữ" đúng theo nghĩa "team-step không egress", KHÔNG phải
  "output qua gateway". Nối external_write→gateway = tính năng v20.5.

## Mở / sang sau
- DeepAgentRuntime: vendor-review deepagents pin version + tắt shell/tracing rồi mới bật chạy thật.
- ToolCallingRuntime cost accounting per-loop hiện best-effort (None) — budget tháng là backstop;
  thêm token-sum nếu cần trần chính xác.
- Tiếp: v21 channel binding (account→agent) · v19.5 kioku (sau cùng).
