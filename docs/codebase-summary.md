# Codebase Summary — my-project-manager

> Bản đồ codebase, cập nhật khi code hình thành. Đọc để biết "cái gì ở đâu" nhanh.
> Status: **2026-06-21 — Phase 0 scaffold xong.** Hello-agent + guardrail core chạy (74 UT pass, ruff clean). E2E (gọi OpenRouter thật) hoãn tới khi có key.

## Trạng thái hiện tại

- Code: **có** — `src/` đã scaffold theo `system-architecture.md §8`. Python venv 3.12 (uv).
- Hello-agent: `python -m src.entrypoints.cli "hello"` chạy graph (perceive→respond) + checkpointer SQLite. Cần `OPENROUTER_API_KEY` để gọi LLM thật.
- Guardrail core: Action Gateway (allowlist + Lớp A hard-deny), audit JSONL append-only + redaction secret, budget tracker $50/tháng, DRY_RUN + kill-switch.
- Test: `uv run pytest` (74 UT, không cần network). `uv run ruff check src tests`.
- Chưa có: tool READ thật (jira/github/...), MCP/CLI adapter, write handler thật — Phase 1.

## Cây thư mục dự kiến (sẽ điền khi build)

```
src/
├── agent/        # LangGraph graph + nodes + state — LÕI
├── tools/        # *_read.py: jira/github/slack/confluence (READ)
├── actions/      # action_gateway.py + *_write.py (WRITE, qua guardrail)
├── llm/          # provider config + prompts
├── config/       # env loading, settings
├── audit/        # audit log (append-only)
└── entrypoints/  # cli.py, cron.py (sau: slack.py, server.py)
```

## Bản đồ "tìm gì ở đâu" (điền dần)

| Cần tìm | Ở |
|---|---|
| Flow agent (graph) | `src/agent/graph.py` (perceive→respond), `state.py`, `checkpoint.py` |
| Cách đọc Jira/GitHub | `src/tools/<tool>_read.py` (Phase 1 — chưa có); adapter ở `src/adapters/` |
| Cách agent ghi/post | `src/actions/action_gateway.py` (mọi mutation qua đây) |
| Guardrail allow/deny | `src/actions/hard_block.py` (allowlist + Lớp A hard-deny) |
| Phát hiện/redact secret | `src/actions/secret_patterns.py` (shared: gateway + audit dùng chung) |
| Budget cap LLM | `src/llm/budget_tracker.py` ($50/tháng, hard-stop) |
| Gọi LLM (OpenRouter) | `src/llm/client.py` + `cost.py` |
| Config/env | `src/config/settings.py` |
| Audit log | `src/audit/audit_log.py` (JSONL append-only) |
| Chạy thế nào | `src/entrypoints/cli.py` + `deployment-guide.md` |

## Mô hình guardrail (CHỐT 2026-06-21, sau 2 vòng review)

**Allowlist + Lớp A hard-deny (defense-in-depth)**. `hard_block.classify(action)`:
1. **Lớp A hard-deny TRƯỚC** — data-loss / credential / security bị chặn cứng dù có nằm trong allowlist. Action shape: MCP `{type,server,tool,args}` hoặc gh `{type,argv}`.
2. **Default-DENY allowlist** — chỉ (server,tool) / gh-subcommand được liệt kê mới qua. Còn lại deny.

Lý do đổi từ denylist: denylist cho qua mọi thứ chưa liệt kê → không an toàn cho red line. Secret detection dùng chung `secret_patterns.py` để gateway-chặn = audit-redact (không lệch).

## Quy ước đọc

- Bắt đầu mỗi session: `project-overview-pdr.md` → file này → file phase đang làm.
- Mọi mutation phải truy ngược về `action_gateway.py`. Nếu thấy write trực tiếp ngoài đó → bug.

## Cập nhật file này khi nào

- Sau mỗi phase / module mới: thêm vào bản đồ + mô tả 1 dòng.
- Đây là tài liệu sống — agent build CÓ TRÁCH NHIỆM cập nhật.

## Reference & Docs (đọc trước khi viết code — KHÔNG copy thẳng)

### Source tham khảo trên máy: DeerFlow 2.0

`~/workspace/deer-flow` — harness production **xây trên LangGraph**, đọc để học pattern, KHÔNG copy code (kiến trúc nặng hơn nhiều so với MVP này).

- **Phân tích kiến trúc đã có sẵn**: `docs/reference-deerflow-2-architecture.md` (trong repo này) — đọc cái này TRƯỚC khi mò repo gốc, đỡ tốn token.
- Path subsystem cụ thể trong `deer-flow/backend/packages/harness/deerflow/` (đã verify tồn tại 2026-06-21):

| Cần học pattern | Path trong deer-flow |
|---|---|
| Agent loop / graph lõi | `deerflow/agents/lead_agent/` |
| Sub-agent spawn (fan-out/gather) | `deerflow/subagents/` |
| Memory (LLM extract + persist) | `deerflow/agents/memory/` |
| Middleware chain (hooks before/after) | `deerflow/agents/middlewares/` |
| Sandbox (local + Docker) | `deerflow/sandbox/` |
| Skill loader (SKILL.md) | `deerflow/skills/` |
| Model factory (provider-agnostic) | `deerflow/models/` |
| Config (YAML + env) | `deerflow/config/` |
| Checkpointer / persistence | `deerflow/persistence/` |

> Lưu ý đối chiếu: DeerFlow dùng middleware-heavy + checkpointer Postgres + sandbox Docker. MVP này LOCAL-first, SQLite, KHÔNG cần sandbox/middleware phức tạp. Học *cách họ tách lớp*, không bê nguyên độ phức tạp.

### Docs chính thức (training data CÓ THỂ cũ — đọc docs thật trước khi code)

| Lib | Docs |
|---|---|
| LangGraph (Python) | https://langchain-ai.github.io/langgraph/ |
| LangGraph concepts (graph/state/checkpointer) | https://langchain-ai.github.io/langgraph/concepts/ |
| OpenRouter API (OpenAI-compatible) | https://openrouter.ai/docs |
| atlassian-python-api (Jira + Confluence) | https://atlassian-python-api.readthedocs.io/ |
| PyGithub | https://pygithub.readthedocs.io/ |
| slack-sdk (Python) | https://slack.dev/python-slack-sdk/ |
| LangSmith / Langfuse (observability, tùy chọn) | https://docs.smith.langchain.com/ · https://langfuse.com/docs |

> ⚠️ API LangGraph + SDK đổi thường xuyên. ĐỌC docs thật trước khi viết, đừng dựa trí nhớ.
