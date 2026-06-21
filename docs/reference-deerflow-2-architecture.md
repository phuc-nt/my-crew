# DeerFlow 2.0 Technical Architecture Report

**Date**: 2026-06-20  
**Target**: DeerFlow 2.0 (ByteDance) ground-up rewrite  
**Scope**: Read-only codebase analysis for multi-agent harness architects

---

## Executive Summary

DeerFlow 2.0 is a LangGraph-based orchestration framework for super agents that:
- Spawns and manages sub-agents via async background executor with configurable concurrency (default 3 concurrent)
- Isolates execution in per-thread sandboxes (local filesystem or Docker containers)
- Maintains long-term memory via LLM-powered extraction + persistence
- Injects extensible skills via system prompt + slash activation (`/skill-name task`)
- Routes to any LLM provider (OpenAI, Anthropic, Deepseek, vLLM, Ollama, custom)

**Key departure from OpenClaw/Hermes**: DeerFlow uses LangGraph's `StreamBridge` + built-in checkpointer instead of custom memory dreaming; uses file-based skill manifests (SKILL.md) instead of SKILL.md conventions; provides embedded `DeerFlowClient` for in-process usage alongside HTTP Gateway.

---

## 1. Top-Level Directory Layout

| Path | Purpose |
|------|---------|
| `backend/` | FastAPI Gateway API + embedded LangGraph agent runtime + harness package (packages/harness/deerflow/) |
| `frontend/` | Next.js 16 web UI with React 19 + shadcn/ui + LangGraph SDK client |
| `contracts/` | JSON contract for subagent status schema (SLA doc, not auto-generated) |
| `docker/` | Docker Compose configs (dev-compose, prod, provisioner, dood, nginx) + entrypoints |
| `skills/` | Public + custom skill directories; SKILL.md format with optional frontmatter |
| `scripts/` | Setup/bootstrap scripts (configure.py, doctor.py, serve.sh, docker.sh, deploy.sh, sandbox setup) |
| `tests/` | Integration tests (blocking-IO gate, harness boundary, client conformance) |
| `pr-build/` | PR-local build artifacts (minimal; most state in .deer-flow/) |

---

## 2. Backend Architecture

### 2.1 High-Level Structure

```
backend/
├── packages/harness/          # Publishable deerflow-harness package (import: deerflow.*)
│   └── deerflow/
│       ├── agents/            # LangGraph agent system
│       ├── sandbox/           # Sandbox providers (local + Docker)
│       ├── subagents/         # Subagent delegation executor
│       ├── tools/             # Built-in + config-defined tools
│       ├── mcp/               # MCP server integration
│       ├── models/            # Model factory with thinking/vision
│       ├── skills/            # Skill discovery + loading
│       ├── config/            # Config system (YAML + extensions_config.json)
│       ├── persistence/       # Checkpointers, run stores, channel connections (SQLite/async)
│       ├── community/         # Tavily, Jina, Firecrawl, image search, AIO sandbox
│       ├── reflection/        # Dynamic module resolution (resolve_variable, resolve_class)
│       ├── tracing/           # LangSmith + Langfuse callback wiring
│       ├── uploads/           # File upload + auto-conversion (markitdown)
│       └── client.py          # DeerFlowClient (embedded in-process agent)
├── app/                       # Unpublished application code (import: app.*)
│   ├── gateway/               # FastAPI routes + LangGraph runtime
│   └── channels/              # IM integrations (Feishu, Slack, Telegram, Discord, DingTalk)
└── tests/                     # Unit + integration tests
```

**Dependency rule** (enforced by `tests/test_harness_boundary.py`): App imports deerflow, but deerflow never imports app.

### 2.2 Agent Orchestration Model

**Entry Point**: `deerflow.agents:make_lead_agent` (registered in `langgraph.json`)

**Lead Agent** (`backend/packages/harness/deerflow/agents/lead_agent/agent.py`):
- Single LangGraph agent that serves as the orchestrator for the entire system
- Receives user input → processes through middleware chain → invokes tools → maintains state
- Supports dynamic model selection, thinking mode, vision mode (flags: `thinking_enabled`, `model_name`)
- System prompt auto-generated with skill list, memory context, and subagent instructions

**ThreadState** (`deerflow/agents/thread_state.py`):
- Extends `AgentState` with: `sandbox`, `thread_data`, `title`, `artifacts`, `todos`, `uploaded_files`, `viewed_images`
- Custom reducers for artifact deduplication and image tracking
- Async-safe state transitions through LangGraph

### 2.3 Middleware Chain (19 layers)

Assembled in strict order at `deerflow/agents/middlewares/tool_error_handling_middleware.py` + `lead_agent/agent.py`:

1. **ThreadDataMiddleware** – Per-thread isolated dirs (workspace, uploads, outputs)
2. **UploadsMiddleware** – Inject newly uploaded files into conversation
3. **SandboxMiddleware** – Acquire sandbox, store sandbox_id in state
4. **DanglingToolCallMiddleware** – Placeholder ToolMessages for interrupted tool calls
5. **LLMErrorHandlingMiddleware** – Normalize provider failures
6. **GuardrailMiddleware** – Pre-tool-call authorization (pluggable `GuardrailProvider` protocol)
7. **SandboxAuditMiddleware** – Security logging for shell/file ops
8. **ToolErrorHandlingMiddleware** – Convert exceptions to error ToolMessages
9. **SkillActivationMiddleware** – Detect `/skill-name task` syntax, resolve enabled skills, inject SKILL.md body
10. **SummarizationMiddleware** – Context reduction near token limits
11. **TodoListMiddleware** – Task tracking for plan mode (opt-in via `is_plan_mode` config)
12. **TokenUsageMiddleware** – Record token metrics (opt-in)
13. **TitleMiddleware** – Auto-generate thread title after first exchange
14. **MemoryMiddleware** – Queue conversations for async memory update
15. **ViewImageMiddleware** – Inject base64 images (if vision-capable model)
16. **DeferredToolFilterMiddleware** – Hide MCP tools until promoted (opt-in if `tool_search.enabled`)
17. **SubagentLimitMiddleware** – Enforce max 3 concurrent subagents (truncate excess calls)
18. **LoopDetectionMiddleware** – Detect repeated tool loops, force final text answer
19. **ClarificationMiddleware** – Intercept `ask_clarification`, interrupt via `Command(goto=END)` (must be last)

**Key insight**: Each middleware wraps the agent in async hooks (`abefore_agent`, `aafter_agent`), allowing fine-grained control over I/O sequencing. Path: `deerflow/agents/middlewares/` (individual files).

### 2.4 Sub-Agent Orchestration

**Built-in agents**: `general-purpose` (full toolset) + `bash` (command specialist)

**Executor**: `deerflow/subagents/executor.py::SubagentExecutor`
- Dual thread pool: `_scheduler_pool` (3 workers) + `_execution_pool` (3 workers)
- Max 3 concurrent subagents enforced by `SubagentLimitMiddleware`
- Timeout: 30 min (configurable)
- Each subagent gets fresh ThreadState (deferred MCP promotions isolated per run)
- No checkpointer (one-shot runs, never resume)
- Deferred MCP tools assembled at start, hidden from initial schema, promoted after `tool_search` resolution

**Flow**:
1. User calls `task()` tool (args: description, prompt, subagent_type)
2. `SubagentExecutor._aexecute()` → background thread
3. Poll every 5s for completion
4. SSE events: `task_started`, `task_running`, `task_completed`/`task_failed`/`task_timed_out`
5. Result injected as ToolMessage

**Tracing**: Subagent runs carry parent `thread_id` → `langfuse_session_id` so they group under parent in observability dashboard.

### 2.5 Memory Subsystem

Path: `deerflow/agents/memory/` + `deerflow/persistence/` (SQLite)

**Components**:
- `updater.py` – LLM-powered extraction (fact deduplication, whitespace-normalized)
- `queue.py` – Debounced update queue (configurable 30s wait, per-thread dedup)
- `storage.py` – File-based JSON per-user (`.deer-flow/users/{user_id}/memory.json`)
- `prompt.py` – Memory templates + token counting (tiktoken or char estimate)

**Data Structure** (in `.deer-flow/users/{user_id}/memory.json`):
- **User Context**: workContext, personalContext, topOfMind (1-3 sentence summaries)
- **History**: recentMonths, earlierContext, longTermBackground
- **Facts**: discrete facts with id, content, category (preference/knowledge/context/behavior/goal), confidence (0-1), createdAt, source

**Workflow**:
1. `MemoryMiddleware` filters user inputs + final AI responses, queues conversation with captured `user_id`
2. Queue debounces (30s default), deduplicates per-thread
3. Background thread invokes LLM to extract + store facts atomically (temp file + rename)
4. Next interaction injects top 15 facts + context into `<memory>` tags in system prompt

**Per-User Isolation**:
- Memory stored at `{base_dir}/users/{user_id}/memory.json`
- Per-agent at `{base_dir}/users/{user_id}/agents/{agent_name}/memory.json`
- `user_id` resolved via `get_effective_user_id()` from `deerflow.runtime.user_context`
- In no-auth mode, defaults to `"default"` constant

**Config** (in `config.yaml` → `memory` section):
- `enabled` / `injection_enabled` – Master switches
- `storage_path` – Absolute path opts out of per-user isolation
- `debounce_seconds` – Wait before processing (default 30)
- `model_name` – LLM for updates (null = use default model)
- `max_facts`, `fact_confidence_threshold` – Storage limits (100 / 0.7)
- `max_injection_tokens` – Token budget for prompt injection (2000)
- `token_counting` – Strategy: `tiktoken` (accurate, may block on BPE download) or `char` (network-free CJK-aware estimate)

### 2.6 Sandbox Subsystem

Path: `deerflow/sandbox/` + `deerflow/community/aio_sandbox/`

**Abstract Interface** (`Sandbox`):
- `execute_command(cmd)` – Run shell command
- `read_file(path, start_line, end_line)` – Read file with optional line range
- `write_file(path, content, append)` – Write or append to file
- `list_dir(path)` – Directory listing (tree format, max 2 levels)

**Provider Pattern** (`SandboxProvider`):
- Lifecycle: `acquire(thread_id)` → `get(id)` → `release(id)`
- Async hooks: `acquire_async()`, release stays sync but safe for event loop (no blocking I/O)

**Implementations**:

1. **LocalSandboxProvider** (`sandbox/local/provider.py`):
   - Filesystem-based execution
   - Per-thread isolation: `backend/.deer-flow/users/{user_id}/threads/{thread_id}/user-data/{workspace,uploads,outputs}`
   - Virtual path mappings: `/mnt/user-data/{workspace,uploads,outputs}` → physical dirs
   - LRU cache (256 entries) with threading.Lock
   - Legacy singleton sandbox (`local`) for no-thread contexts
   - No bash tool by default (security; enable via Docker sandbox)

2. **AioSandboxProvider** (`community/aio_sandbox/provider.py`):
   - Docker-based isolation
   - Active-cache + warm-pool for container reuse
   - Health-check validation during acquire/reuse; dead containers dropped
   - Container backend discovery (Docker or Kubernetes provisioner)
   - Same virtual paths mounted at `/mnt/user-data/` inside container
   - Bash tool enabled

**Virtual Path System**:
- Agent sees: `/mnt/user-data/{workspace,uploads,outputs}`, `/mnt/skills`
- Physical: `backend/.deer-flow/users/{user_id}/threads/{thread_id}/user-data/...`, `deer-flow/skills/`
- Translation: Built at acquire time via `PathMapping`; `tools.py` has defense-in-depth `replace_virtual_path()`
- Detection: `is_local_sandbox()` checks `sandbox_id == "local"` (legacy) or `sandbox_id.startswith("local:")` (per-thread)

**Sandbox Tools** (in `sandbox/tools.py`):
- `bash` – Execute commands (path-translated, error handling; disabled in local mode by default)
- `ls` – Directory listing
- `read_file` – Read with optional line range
- `write_file` – Write/append (creates directories, overwrites by default)
- `str_replace` – Substring replacement (single or all); same-path serialization scoped to `(sandbox.id, path)`

### 2.7 Skills Subsystem

Path: `deerflow/skills/` + `skills/{public,custom}/`

**Format**: Directory with `SKILL.md` (YAML frontmatter + markdown body)

**Example Frontmatter** (from `skills/public/bootstrap/SKILL.md`):
```yaml
---
name: bootstrap
description: >-
  Generate a personalized SOUL.md through a warm, adaptive onboarding conversation.
---
```

**Loading** (`skills/storage.py::LocalSkillStorage`):
- Recursively scans `skills/{public,custom}` for `SKILL.md`
- Parses YAML frontmatter: `name`, `description`, `license`, `allowed-tools`
- Enabled state read from `extensions_config.json`
- Offloaded to asyncio thread pool to avoid blocking event loop

**Injection**:
- Enabled skills listed in agent system prompt with container paths
- Full SKILL.md body accessible within skill namespace

**Slash Activation** (`SkillActivationMiddleware`):
- Detect strict `/skill-name task` syntax on latest user message
- Resolve only enabled + runtime-allowed skills
- Read `SKILL.md` from trusted storage
- Inject skill body as hidden current-turn model context
- Record audit event: skill name, category, path, content hash

**Installation** (`POST /api/skills/install`):
- Accept `.skill` ZIP archive
- Extract to `custom/` directory
- Optional frontmatter support

**Vs OpenClaw convention** (`SKILL.md`): DeerFlow's SKILL.md is a manifest + body combined (not a convention). Instructions live inside the skill directory, not in hardcoded code. Skills are discoverable via file scan, not hard-registered.

---

## 3. Model & Provider Configuration

Path: `config.yaml` (project root, after `cp config.example.yaml config.yaml`)

**Model Config Schema** (from `config.example.yaml` lines 40–150+):

```yaml
models:
  - name: model-id                    # Unique identifier
    display_name: Display Name
    use: langchain_provider:ClassName # Class path for reflection
    model: model-name-string          # Provider's model identifier
    api_key: $OPENAI_API_KEY          # Env var resolution
    supports_thinking: true/false
    supports_vision: true/false
    supports_reasoning_effort: true/false (Doubao)
    when_thinking_enabled:
      extra_body:
        thinking:
          type: enabled
    when_thinking_disabled:
      extra_body:
        thinking:
          type: disabled
```

**Recommended Models** (per README.md):
- **Doubao-Seed-2.0-Code** (VolcEngine) – thinking + vision
- **DeepSeek v3.2** – reasoning
- **Kimi 2.5** – reasoning + vision

**Supported Providers** (via LangChain):
- OpenAI (`langchain_openai:ChatOpenAI`)
- Anthropic Claude (`langchain_anthropic:ChatAnthropic`) – extended thinking
- Google Gemini (`langchain_google_genai:ChatGoogleGenerativeAI`)
- Deepseek (`langchain_deepseek:ChatDeepSeek`)
- Ollama native (`langchain_ollama:ChatOllama`) – preserves reasoning content
- vLLM (`deerflow.models.vllm_provider:VllmChatModel`) – Qwen reasoning via `chat_template_kwargs.enable_thinking`
- Custom via reflection: `module.path:ClassName`

**Config Versioning**:
- `config_version: 14` in `config.example.yaml` – Bump when schema changes
- `AppConfig.from_file()` compares versions, warns if outdated
- `make config-upgrade` auto-merges missing fields

**Config Caching**:
- `get_app_config()` caches parsed config
- Auto-reloads on file content signature change (includes mtime + digest)
- **Hot-reload boundary** (per-request reload): `models[*].max_tokens`, `summarization.*`, `title.*`, `memory.*`, `subagents.*`, `tools[*]`, system prompt
- **Startup-only fields** (restart required): database, checkpointer, run_events, stream_bridge, sandbox, log_level, channels, channel_connections (listed in `reload_boundary.py::STARTUP_ONLY_FIELDS`, mirrored with `"startup-only:"` prefix in field descriptions)

**Extensions Configuration** (`extensions_config.json`, project root):

```json
{
  "mcpServers": {
    "github": {
      "enabled": true,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {"GITHUB_TOKEN": "$GITHUB_TOKEN"}
    },
    "secure-http": {
      "enabled": true,
      "type": "http",
      "url": "https://api.example.com/mcp",
      "oauth": {
        "enabled": true,
        "token_url": "https://auth.example.com/oauth/token",
        "grant_type": "client_credentials",
        "client_id": "$MCP_OAUTH_CLIENT_ID",
        "client_secret": "$MCP_OAUTH_CLIENT_SECRET"
      }
    }
  },
  "skills": {
    "pdf-processing": {"enabled": true}
  }
}
```

---

## 4. Frontend

Path: `frontend/` (standalone Next.js 16 app)

**Stack**:
- **Framework**: Next.js 16 (App Router)
- **UI**: React 19 + Tailwind CSS 4 + shadcn/ui + MagicUI + React Bits
- **AI Integration**: LangGraph SDK + Vercel AI Elements

**Client Model**:
- Uses `@langchain/langgraph-sdk` HTTP client to Gateway API
- Connects via `/api/langgraph/*` (through Nginx) or direct `localhost:8001`
- Supports streaming responses (SSE) via LangGraph SDK's `stream()` method

**Routes**:
- `/` – Landing page
- `/chats` – Chat list
- `/chats/new` – New chat
- `/chats/[thread_id]` – Specific chat (LangGraph thread_id)

**Environment Variables** (from `frontend/.env.example`):
- `NEXT_PUBLIC_LANGGRAPH_BASE_URL` – Default `/api/langgraph` (through Nginx)
- `NEXT_PUBLIC_BACKEND_BASE_URL` – Default empty (through Nginx)

**Gateway Contract**:
- Uses LangGraph SDK client to call `/api/langgraph/*` routes
- Response format: LangGraph-compatible threads + runs (see `contracts/subagent_status_contract.json` for subagent SLA)

---

## 5. Notable Dependencies

### Backend (`backend/pyproject.toml` + `packages/harness/pyproject.toml`)

| Lib | Version | Purpose |
|-----|---------|---------|
| LangGraph | 1.1.9+ | Agent orchestration, checkpointing, streaming |
| LangChain | 1.2.15+ | LLM abstractions, tool system |
| FastAPI | 0.115.0+ | Gateway REST API |
| langchain-mcp-adapters | 0.2.2+ | MCP server multi-server client |
| agent-sandbox | 0.0.19+ | Sandbox execution |
| markitdown | 0.0.1a2+ | Multi-format doc conversion (PDF, PPT, Word, Excel → Markdown) |
| tavily-python | 0.7.17+ | Web search (5 results) |
| firecrawl-py | 1.15.0+ | Web scraping |
| Pydantic | 2.12.5+ | Config schema + validation |
| SQLAlchemy[asyncio] | 2.0–3.0 | Async ORM for persistence |
| langgraph-checkpoint-sqlite | 3.0.3+ | Default checkpointer |
| langgraph-checkpoint-postgres | 3.0.5+ | Optional: Postgres checkpointer (opt-in) |
| tiktoken | 0.8.0+ | Token counting (lazy-loaded, blocks on BPE download; fallback to char estimate) |
| Langfuse | 3.4.1+ | Observability (optional) |

**Optional**: `langchain-ollama` (Ollama native API), `langchain-google-genai` (Gemini), `langchain-anthropic` (Claude), `langchain-deepseek` (DeepSeek)

### Frontend (`frontend/package.json`)

| Lib | Purpose |
|-----|---------|
| Next.js 16 | React framework with App Router |
| React 19 | UI components |
| Tailwind CSS 4 | Utility CSS |
| shadcn/ui | Headless UI components |
| @langchain/langgraph-sdk | LangGraph SDK (HTTP client) |
| ai / @vercel/ai | AI SDK for streaming, tool use |

---

## 6. How to Run It

### Minimal Local Path (from `Install.md` + Makefile)

```bash
cd /path/to/deer-flow

# 1. Copy config template
cp config.example.yaml config.yaml

# 2. Add at least one LLM model to config.yaml under `models:[]`
# 3. Set env vars (e.g., export OPENAI_API_KEY=...)

# 4. Check prerequisites (Node.js 22+, Python 3.12+, uv, pnpm, nginx)
make check

# 5. Install all dependencies
make install

# 6. Start all services (Gateway + Frontend + Nginx)
make dev
# App available at http://localhost:2026
```

**Separate services** (backend only, skipping Nginx + frontend):
```bash
cd backend
make install
make dev  # Gateway at http://localhost:8001
```

### Docker Path

```bash
make docker-init    # Pull sandbox image
make docker-start   # Start all services in Docker
# App available at http://localhost:2026
```

### Commands

| Cmd | Purpose |
|-----|---------|
| `make check` | Verify prerequisites (node, python, uv, pnpm, nginx) |
| `make install` | Install backend + frontend + pre-commit hooks |
| `make dev` | Start all services with hot-reload |
| `make start` | Start production mode (no reload) |
| `make dev-daemon` | Background daemon mode |
| `make stop` | Stop all services |
| `make docker-init` | Pull sandbox Docker image |
| `make docker-start` | Start in Docker |
| `make docker-stop` | Stop Docker services |
| `make detect-blocking-io` | Scan for blocking I/O on event loop |
| `make test` | Run backend tests (in `backend/`) |

### Nginx Routing

- `/api/langgraph/*` → Gateway embedded runtime (8001), rewritten to `/api/*`
- `/api/*` (other) → Gateway REST API (8001)
- `/` (non-API) → Frontend (3000)

---

## 7. Gateway API Routes

Path: `app/gateway/routers/`

| Route | Endpoints |
|-------|-----------|
| **Models** | `GET /api/models`, `GET /api/models/{name}` |
| **Runs** (LangGraph-compat) | `POST /api/langgraph/threads`, `POST /api/langgraph/threads/{id}/runs`, `GET /api/langgraph/threads/{id}/runs/{rid}`, etc. |
| **Runs** (REST) | `POST /api/threads/{id}/runs`, `GET /api/threads/{id}/runs` (thread-scoped); `POST /api/runs/stream`, `GET /api/runs/{rid}/messages` (stateless) |
| **MCP** | `GET /api/mcp/config`, `PUT /api/mcp/config` |
| **Skills** | `GET /api/skills`, `GET /api/skills/{name}`, `PUT /api/skills/{name}`, `POST /api/skills/install` |
| **Memory** | `GET /api/memory`, `POST /api/memory/reload`, `GET /api/memory/config`, `GET /api/memory/status` |
| **Uploads** | `POST /api/threads/{id}/uploads`, `GET /api/threads/{id}/uploads/list`, `DELETE /api/threads/{id}/uploads/{filename}` |
| **Threads** | `DELETE /api/threads/{id}` (local DeerFlow data cleanup after LangGraph deletion) |
| **Artifacts** | `GET /api/threads/{id}/artifacts/{path}` (forced download for `text/html`, `application/xhtml+xml`, `image/svg+xml` to reduce XSS) |
| **Suggestions** | `GET /api/suggestions/config`, `POST /api/threads/{id}/suggestions` (follow-up questions, reasoning stripped) |

**Uploads**: Auto-converts PDF/PPT/Excel/Word to Markdown via `markitdown`. Rejects directories. Renames duplicates in single request with `_N` suffix.

**Artifacts**: Active content types forced as download attachments (XSS mitigation).

---

## 8. IM Channels System

Path: `app/channels/` + `app/gateway/routers/channel_connections.py`

**Supported Platforms**: Feishu, Slack, Telegram, Discord, DingTalk

**Architecture**:
- Channels communicate via `langgraph-sdk` HTTP client (same as frontend)
- Threads created/managed server-side
- Internal auth via process-local token + matching CSRF cookie/header

**Message Flow**:
1. External platform → Channel impl → `MessageBus.publish_inbound()`
2. `ChannelManager._dispatch_loop()` consumes queue
3. Look up/create thread via Gateway's LangGraph API
4. For Feishu/Telegram: `runs.stream()` → accumulate text → publish multiple outbound updates
5. For Slack/Discord: `runs.wait()` → extract final response → publish outbound
6. Feishu patches same card in place; Telegram edits placeholder message; DingTalk uses AI Card streaming

**User-Owned Connections** (optional):
- SQL-backed `channel_connections` table mapping `(provider, external_account_id, workspace_id)` → DeerFlow `user_id`
- Deep-link `/start <code>` (Telegram) or `/connect <code>` (others)
- Single-active-owner semantics: latest bind wins (ownership transfer)

**Owner-Scoped File Storage**:
- Inbound files + uploads staged under DeerFlow owner's bucket: `users/{user_id}/threads/{thread_id}/user-data/{uploads,outputs}`
- Output artifacts resolved from owner's bucket

**Config** (`config.yaml` → `channels`):
- `langgraph_url` – LangGraph API base (default `http://localhost:8001/api`)
- `gateway_url` – Gateway auxiliary (default `http://localhost:8001`)
- Per-channel: Feishu (app_id, app_secret), Slack (bot_token, app_token), Telegram (bot_token), DingTalk (client_id, client_secret, optional card_template_id)

---

## 9. Configuration System

### Config Loading Priority

1. Explicit `config_path` argument
2. `DEER_FLOW_CONFIG_PATH` env var
3. `config.yaml` in current directory (backend/)
4. `config.yaml` in parent directory (project root — **recommended**)

### Config Schema (`AppConfig`)

**Key sections**:
- `config_version` – Version number for schema migrations
- `log_level` – debug/info/warning/error
- `token_usage.enabled` – Token metrics (opt-in)
- `models[]` – LLM configs with class paths, API keys, thinking/vision flags
- `tools[]` – Tool definitions with module paths + groups
- `tool_groups[]` – Logical tool groupings
- `sandbox.use` – Sandbox provider class path (default: local)
- `skills.path` / `skills.container_path` – Host + container skill directories
- `title` – Auto-title generation (enabled, max_words, max_chars, prompt_template)
- `summarization` – Context reduction (enabled, trigger conditions, keep policy)
- `subagents.enabled` – Master switch for task delegation
- `memory` – Memory system (enabled, storage_path, debounce_seconds, model_name, max_facts, injection_enabled, max_injection_tokens, token_counting)
- `channels` / `channel_connections` – IM integrations

### Environment Variable Resolution

All config values starting with `$` resolved as environment variables at parse time (e.g., `api_key: $OPENAI_API_KEY`).

### Config Watch

`get_app_config()` detects file signature changes (mtime + content digest) and auto-reloads on next request. Startup-only fields listed in `reload_boundary.py::STARTUP_ONLY_FIELDS` require full restart.

---

## 10. Embedded Client

Path: `deerflow/client.py::DeerFlowClient`

**Purpose**: In-process agent access without HTTP (useful for scripts, notebooks, background jobs)

**Shared State**: Same config files + `.deer-flow/` data directories as Gateway

**Key Methods**:
- `chat(message, thread_id)` – Sync, returns final AI text
- `stream(message, thread_id)` – Async generator, yields `StreamEvent` (values, messages-tuple, custom, end)
- `list_models()`, `get_model(name)` – Model listing
- `get_mcp_config()`, `update_mcp_config(servers)` – MCP management
- `list_skills()`, `get_skill(name)`, `update_skill(name, enabled)`, `install_skill(path)` – Skills
- `get_memory()`, `reload_memory()`, `get_memory_config()`, `get_memory_status()` – Memory
- `upload_files(thread_id, files)`, `list_uploads(thread_id)`, `delete_upload(thread_id, filename)` – Uploads
- `get_artifact(thread_id, path)` – Returns `(bytes, mime_type)`

**Response Formats**: Match Gateway API Pydantic models exactly (validated by `TestGatewayConformance` unit tests).

**Gateway Conformance**: Every client dict return is parsed through the corresponding Gateway model to catch schema drift (tests: `test_client.py`, `test_client_live.py`).

---

## 11. Testing & Quality

### Test Structure

| Path | Purpose |
|------|---------|
| `backend/tests/blocking_io/` | Strict Blockbuster runtime gate (async event loop safety) |
| `backend/tests/test_harness_boundary.py` | Enforce harness → app one-way dependency |
| `backend/tests/test_client.py` | Client unit tests (77 tests, conformance) |
| `backend/tests/test_client_live.py` | Integration tests (require config.yaml) |
| `backend/tests/test_memory_updater.py` | Memory subsystem regression |
| `backend/tests/test_*.py` | Feature-specific unit tests |
| `frontend/tests/` | E2E tests (Playwright) |

### Blocking-IO Gate

```bash
make test-blocking-io    # Strict gate on app.* + deerflow.* in async contexts
make detect-blocking-io  # Static AST scan (informational, not CI-blocking)
```

Enforces: No sync blocking I/O (file ops, subprocess, network) on event loop. Offloads via `asyncio.to_thread` or moves to background.

### Code Style

- Linter/Formatter: `ruff`
- Line length: 240 characters
- Python: 3.12+ with type hints
- Quotes: Double
- Indentation: 4 spaces

---

## 12. Deployment Modes

### Local Development

```bash
make dev  # Hot-reload, file watching
# Ports: 2026 (Nginx), 3000 (Frontend), 8001 (Gateway)
```

### Production Local

```bash
make start  # Optimized, no reload
```

### Docker Development

```bash
make docker-start  # Docker Compose dev mode
```

### Docker Production

```bash
make up  # Docker Compose production
```

**Docker Compose Files** (`docker/`):
- `docker-compose-dev.yaml` – Development (reload, mounts)
- `docker-compose.yaml` – Production
- `docker-compose.dood.yaml` – Docker-out-of-Docker (for sandbox provisioning)
- `docker-compose.cli-auth.yaml` – CLI auth overlay
- `provisioner/` – Kubernetes provisioner (optional for advanced sandbox modes)

---

## 13. DeerFlow vs OpenClaw/Hermes: Conceptual Differences

| Aspect | DeerFlow 2.0 | OpenClaw/Hermes |
|--------|------------|--------|
| **Orchestration** | LangGraph with middleware chain | Custom agent harness (Pi.dev) |
| **Sub-agent Model** | Async executor, 3 max concurrent, background threads | Task delegation model (similar) |
| **Memory** | File-based JSON + LLM extraction (automatic) | Inline memory dreaming (Hermes pattern) |
| **Skills** | SKILL.md manifest (slash activation `/skill-name task`) | SKILL.md convention (hardcoded registry) |
| **Embedded Client** | `DeerFlowClient` (in-process, no HTTP) | N/A (HTTP-centric) |
| **Sandbox** | LocalSandboxProvider (local) + AioSandboxProvider (Docker) | Varies by project |
| **Config Hotload** | Per-request, with startup-only marker | Project-specific |
| **Middleware** | 19 middleware layers, strict order, async hooks | Project-specific |
| **Checkpointing** | LangGraph native (SQLite or Postgres) | Depends on harness |
| **Tracing** | LangSmith + Langfuse callbacks at graph root | Framework-specific |
| **API** | FastAPI Gateway + LangGraph-compat routes | Varies |
| **Frontend** | Next.js 16 + LangGraph SDK client | Varies |
| **IM Channels** | 5 platforms (Feishu, Slack, Telegram, Discord, DingTalk) with user-owned connections | Project-specific |

---

## Unresolved Questions

1. **vLLM reasoning content**: Does `VllmChatModel::deerflow/models/vllm_provider.py` fully preserve Qwen reasoning deltas on streaming, or are edge cases still being discovered? (Code indicates preservation, but Ollama had issues initially.)

2. **Blocking-IO static vs runtime gap**: Does the AST scanner (`detect-blocking-io`) catch all event-loop-unsafe paths, or do some sneak through to runtime tests? (Currently informational, not CI-enforced.)

3. **Subagent deferred tool promotion**: When a subagent calls `tool_search`, does the promotion persist across subsequent tool calls within the same subagent run, or reset per call? (Code suggests per-run freshness, need confirmation.)

4. **Memory tiktoken retry cooldown**: If tiktoken BPE download fails, does the 600s cooldown persist across Gateway restarts, or only in-memory? (Code uses module-level cache, so restarts reset.)

5. **Sandbox Docker health-check semantics**: If a Docker health-check fails, is the container dropped permanently or retried on next acquire? (Code treats failures as "unknown", not dead; retried on next acquire with discovery step.)

6. **IM channel ownership transfer race**: If two users bind the same Telegram account concurrently, is there a guaranteed single winner, or can both succeed transiently? (Code uses DB unique index `uq_channel_connection_active_identity`, should prevent this, but edge case unclear.)

7. **Guild-bound Slack credentials**: Does the stored `connection_credentials` column support guild/workspace separation, or is it flat per (Slack workspace, external user)? (Code suggests flat, per connection row.)

8. **Artifact XSS content types**: Are `text/html`, `application/xhtml+xml`, `image/svg+xml` the only ones forced to download, or are there others? (Code lists these three, but SVG can still exec JS in some browsers.)

---

## References

- `backend/README.md` – Architecture overview + quick start
- `backend/CLAUDE.md` – Development guidelines, middleware chain, configuration
- `backend/docs/ARCHITECTURE.md` – System diagram + component details
- `config.example.yaml` – Full config schema with examples
- `Install.md` – Setup instructions for agents
- `frontend/README.md` – Frontend stack + routes
- `Makefile` – All available commands
- `langgraph.json` – LangGraph graph registry
- `.claude/rules/` – Project development rules
