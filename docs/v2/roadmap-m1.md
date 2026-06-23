# v2 — Milestone M1: Multi-agent core (CLI/worker, no UI)

> Quay lại [README](README.md) · tiếp theo: [roadmap-m2](roadmap-m2.md) · nền: [profile-design](profile-design.md), [architecture](architecture.md).

## 5. Milestone M1 — Multi-agent core (CLI/worker, no UI)

> Mục tiêu M1: chạy được **N agent / N project, isolated, qua CLI/worker** — giá trị thật trước khi có UI. Mỗi phase chạy được + có giá trị, không big-bang (nguyên tắc v1 giữ nguyên).

### P1 — Config-injection refactor (kill singletons) **[BREAKING]**

- **Goal**: bỏ 2 `@lru_cache` singleton; config trở thành object truyền vào làm parameter. Đây là nền cho mọi thứ sau.
- **Key changes**:
  - Giữ `ReportingConfig` + `Settings` (đã là `@dataclass(frozen=True)` — `reporting_config.py:59`, `settings.py:47`) nhưng **bỏ `@lru_cache`** (`reporting_config.py:102`, `settings.py:78`); chuyển thành builder nhận `dict`/profile thay vì đọc `.env` toàn cục.
  - Thread config qua param tới ~21 call site (đã verify, theo category):
    - **Tool fetchers (4 file)**: `jira_read.py` (3 call: :99/:135/:160), `github_read.py` (2: :97/:114), `okr_read.py` (:73), `confluence_read.py` (:82) — đổi sang nhận `cfg` param.
    - **Graph builders / deps (factory)**: `report_graph.py:70`, `okr_weekly_section.py` (:36/:64/:81), `resource_weekly_section.py` (:37/:40/:69/:83), `audience_delivery.py:33` — `default_*_deps(...)` nhận `config`+`settings`.
    - **Action writers (3 file)**: `confluence_write.py` (:78/:100), `slack_write.py` (:29/:59), `action_gateway.py` (:106/:108 external_channels — đã có param `external_channels` ở `__init__:122`, chỉ cần bắt buộc truyền).
    - **Storage (4 file)**: `checkpoint.py:32` (đã nhận `db_path`), `approval_store.py:37` (đã nhận `db_path`), `audit_log.py:52` (đã nhận `path`), `dedup_store.py:25` (đã nhận `db_path`) — bỏ default `get_settings().data_dir`, bắt buộc truyền path.
    - **Budget / LLM (2 file)**: `budget_tracker.py:38` (đã nhận `settings`), `client.py:54` (đã nhận `settings`) — bỏ fallback `get_settings()`.
    - **Entrypoints (2 file)**: `cli.py` (:22/:35/:60), `cron.py` (:64/:72) — đọc profile, build config, truyền xuống.
- **Files touched**: ~21 (6 graph/section, 4 tool, 3 action, 4 storage, 2 budget/llm, 2 entrypoint) + 2 config.
- **Acceptance**:
  - `grep -rn "get_reporting_config\|get_settings" src/` → **0 hit** (ngoài định nghĩa builder).
  - Toàn bộ 269 test pass sau khi đổi sang truyền config (test có thể cần update fixtures — chấp nhận, breaking allowed).
  - `ruff` clean.
- **Risks**: lan rộng (21 file) nhưng **logic graph không đổi** — chỉ plumbing. Risk = bỏ sót call site → runtime `NameError`. Mitigation: grep-driven, acceptance = 0 hit.
- **BREAKING**: ✅ v1 CLI signature đổi (`build_*_graph` thêm `config=`, `settings=`). Backward-compat KHÔNG yêu cầu (user xác nhận).

### P2 — Profile system (thư mục 4 file + persona/project/memory + `default` profile)

- **Goal**: parse thư mục `profiles/<id>/` (4 file) → config object (P1's `ReportingConfig`+`Settings`) + persona + project-context + memory; inject vào prompt/analysis; ship một `default` profile migrate y hệt hành vi v1.
- **Key changes**:
  - `src/profile/loader.py`: đọc `profile.yaml` → build `ReportingConfig`+`Settings`+budget/schedule. `token_env` → resolve từ `os.environ[name]` lúc spawn server (map vào `McpServerSpec.env`, dùng lại `required_env_keys` validation — `reporting_config.py:41`). Đọc `SOUL.md`/`PROJECT.md`/`MEMORY.md` thành string (file thiếu ⇒ rỗng, no-op).
  - `src/profile/context.py`: inject 3 file Markdown vào lớp prompt:
    - `SOUL.md` → prepend system prompt (`src/llm/report_prompt.py` + `okr_/resource_` + `audience_external_prompts.py`); rỗng ⇒ prompt v1 nguyên vẹn.
    - `PROJECT.md` → đưa vào user-message context của analyze/compose (nền nghiệp vụ).
    - `MEMORY.md` → đọc vào context (đọc-only ở M1; ghi qua Store ở M2-P8).
  - `profiles/default/{profile.yaml,SOUL.md,PROJECT.md,MEMORY.md}`: tái tạo `.env` v1 (`profile.yaml` từ `config.example.env`; 3 file md rỗng ⇒ hành vi v1).
- **Files touched**: new `src/profile/{loader,context}.py`, `profiles/default/` (4 file); edit prompt modules để nhận persona/project param (5 prompt file).
- **Acceptance**:
  - Load `profiles/default/` (3 md rỗng) → config bằng-byte với `.env` v1; `cli report --daily` ra report **giống hệt** v1.
  - `SOUL.md` có nội dung → system prompt thực sự đổi (test: prompt chứa custom rule). `PROJECT.md` có quy ước → vào context analyze.
  - `token_env` resolve đúng từ `.env`; thiếu env → lỗi rõ ràng lúc spawn (không lúc load).
- **Risks**: persona/project có thể đè business-tone external (rò PII). Mitigation: 3 file Markdown **prepend** context, KHÔNG thay external-prompt sanitization (privacy giữ — bài học Phase 5). Test: external report với persona+project vẫn zero key/PII. Memory tự-ghi tới M2-P8 mới bật (M1 chỉ đọc).

### P3 — Registry + worker + per-agent isolation + per-agent gateway/budget/audit

- **Goal**: `registry.yaml` liệt kê agent; worker entrypoint load 1 profile, build graph + gateway + stores per-agent với data dir riêng; coordinating service spawn worker theo registry.
- **Key changes**:
  - `registry.yaml`: `agents: [{id, enabled}]` (đường dẫn = `profiles/<id>/` — thư mục 4 file). Model = OpenClaw `openclaw.json` agents.list[].
  - `src/runtime/worker.py`: nhận `--agent-id`, load thư mục profile (P2 loader), build mọi store với path `.data/agents/<id>/{checkpoints.db,audit/,budget/,approvals.db,dedup.db}`, build per-agent `ActionGateway(settings, stores, external_channels)` từ profile.
  - `thread_id` = `"<agent_id>:<kind>:<date>"` (v1 hiện flat: `cli.py:35`="cli", `cron.py:72`="cron-{kind}-{audience}" — thêm prefix `agent_id`).
  - `src/runtime/service.py`: đọc registry, scheduler (đọc `schedule` trong `profile.yaml`), spawn/giám sát worker. Pattern: OpenClaw registry + DeerFlow subagent executor (thread pool, per-thread state, timeout).
- **Files touched**: new `src/runtime/{worker,service}.py`, `registry.yaml`; reuse mọi store (đã nhận path từ P1).
- **Acceptance**:
  - 2 agent (acme-web + beta-app) chạy đồng thời, ghi vào 2 data dir riêng, audit/budget/dedup không lẫn.
  - Budget của agent A hit 100% **không** chặn agent B (budget per-agent).
  - Lớp B approval của A không xuất hiện trong queue của B (approval_store per-agent).
  - `thread_id` chứa agent_id → checkpoint của A và B không đụng.
- **Risks**:
  - **Resource cost**: 1 process/agent — N agent = N node subprocess spawn + N Python process (xem [risks](risks-open-questions.md)). Mitigation M1: worker on-demand/scheduled, không giữ N process thường trực.
  - Token isolation: 2 agent cùng project type cần 2 token khác nhau → `token_env` khác nhau per-profile (P2 đã lo).

### P4 — Multi-agent CLI (register / list / run)

- **Goal**: CLI quản lý nhiều agent thay cho CLI single-project v1.
- **Key changes**:
  - `mpm agent list` — đọc registry, in id/name/enabled/last-run.
  - `mpm agent register <id>` — scaffold `profiles/<id>/` (4 file từ template; 3 md có placeholder).
  - `mpm agent run <id> --report daily|weekly|okr|resource [--audience internal|external]` — chạy 1 report cho 1 agent qua worker.
  - `mpm agent approvals <id>` / `approve <id> <approval-id>` / `reject` — Lớp B per-agent (route tới approval_store của agent đó).
  - Giữ `audit` query nhưng thêm `--agent <id>`.
- **Files touched**: `src/entrypoints/cli.py` (rewrite dispatch quanh agent_id — **BREAKING** so với v1 CLI), reuse worker (P3).
- **Acceptance**: register 2 agent → list thấy cả 2 → run report từng cái → approvals/approve per-agent hoạt động end-to-end (DRY_RUN trước, rồi real write 1 agent).
- **Risks**: BREAKING CLI surface. Mitigation: `default` profile + `mpm agent run default ...` = đường tương đương v1 cho ai quen lệnh cũ.

**Exit M1**: nhiều agent / nhiều project, isolated hoàn toàn, chạy qua CLI/worker + scheduler. Guardrail per-agent. **Chưa có UI, chưa Postgres** — đó là M2.


---

## Features chèn vào M1 (từ [feature-proposals](feature-proposals.md))

- **A1 Memory injection** → P2 (loader đọc `MEMORY.md` rồi inject top-K vào context compose).
- **B1 Run-event log** → P3 (ghi `runs.jsonl` cạnh audit per-agent).
- **D1 Per-agent scheduler** → P3 (service đọc `schedule` trong `profile.yaml`, thay launchd toàn cục).
