# Phase 0 — Scaffold + guardrail core

2026-06-21 · ✅ Done (E2E verified với key thật)

## Làm gì
- uv/Python 3.12, deps pinned (langgraph 1.2.6, openai 2.43.0, pydantic 2.13.4).
- Hello-agent: LangGraph `perceive→respond` + SQLite checkpointer + CLI. E2E thật: gọi OpenRouter (minimax-m2.7) OK, cost $0.000429.
- LLM layer: OpenRouter qua raw `openai` SDK, bounded retry, budget-gated.
- Guardrail core: Action Gateway (1 chốt mutation), audit JSONL append-only + redaction, budget tracker $50/tháng (`src/llm/budget_tracker.py`), DRY_RUN + kill-switch.
- 74 unit test, ruff clean.

## Quyết định & vì sao
| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| Tool qua **MCP + CLI**, không SDK Python | MCP server sẵn có; ranh giới ngoài dễ audit; agent không cầm token | Cần Node + cầu transport stdio (Phase 1) |
| LLM qua **raw openai SDK**, không ChatOpenAI | ChatOpenAI bỏ mất `cost`/usage extras của OpenRouter | Mất tiện ích LangChain ở tầng gọi |
| Guardrail **allowlist + Lớp A hard-deny**, bỏ denylist | Denylist cho qua mọi thứ chưa liệt kê → không an toàn cho red line "full autonomous write" | Mỗi tool mới phải thêm allowlist thủ công |
| 1 detector secret dùng chung (`secret_patterns.py`) | Gateway-chặn = audit-redact, không lệch | — |

## Vấp & học được
- Build denylist trước → 2 vòng review tìm ra bypass thật (secret lọt vào audit log bất biến; `gh api` implicit-POST; version `"0"`/`-1` lọt). CI xanh vẫn sót → **red line cần review đối kháng, không chỉ test**.
- Vòng 1 vá *từng case*, vòng 2 mới thấy *kiến trúc* sai (vẫn là denylist). Bài học: red line = dùng allowlist, liệt kê cái ĐƯỢC phép.
- Secret không prefix (Atlassian token) không bắt được trong free-text → chấp nhận residual risk, ghi `deployment-guide.md §3`.

## Mở / sang Phase 1
- MCP transport: 3 server stdio-default, cần cầu HTTP/SSE hoặc session-manager.
- Tool READ thật (Jira/GitHub) + adapter MCP/CLI + write handler đầu tiên qua gateway.
- Token Atlassian/Slack đặt ở env MCP server; `gh auth login` cho GitHub.
