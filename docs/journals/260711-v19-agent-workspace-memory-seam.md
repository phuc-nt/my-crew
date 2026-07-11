# v19 — Agent-harness vòng 1: memory seam + workspace protocol
2026-07-11 · HOÀN TẤT (1730 BE + 177 FE xanh, ruff/tsc sạch, 6 kịch bản E2E code-path pass)

## Làm gì
- Brainstorm khảo sát 3 harness (hermes-agent, OpenClaw, my-kioku) để nâng repo thành agent
  harness tái-dùng-được (self-host + template). Chương trình 3 vòng: v19 seam+protocol → v20
  channel binding → v21 2-mode UI.
- **Memory provider seam** (`src/memory/`): `resolve_memory_text(loaded)` = 1 cửa thay 6 site
  đọc `loaded.memory` (worker/team_step_runner/review_graph/cron/cli + **qa_answer**). Provider
  `static` (MEMORY.md byte-identical) qua `MemoryConfig` từ `memory:` block; `kioku` HOÃN v19.5
  (chọn nay raise rõ, không im lặng fallback).
- **Workspace protocol v2**: `scaffold_profile_dir` tạo `vault/` (reserved kioku) + `skills/`
  (per-agent) cho mỗi nhân viên mới.
- **Per-agent skills có guard** (`load_agent_skills`): body wrap `format_internal_content`
  (L1/L2/L4), name scrub charset; `load_skill_pool` merge pack∪agent, collision không shadow
  pack (rename `agent:<name>`).
- **Capability block** (`capability_block.py`): auto-gen ≤600 chars, INTERNAL-only qua
  `build_context_block(project, memory, capability)` (param default "" → caller cũ byte-identical).

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| HOÃN kioku adapter sang v19.5 | Red-team đối chiếu my-kioku THẬT: 7/16 claim sai (chưa publish npm, `--digest` recency-top-5 không-query, `bun x`=RCE, race vault) | v19 chưa có memory sống; seam sẵn sàng, static vẫn default |
| Capability block INTERNAL-only (không system msg) | System msg phục vụ CẢ external → skill.name free-text = injection vector từ file gitignored (H6) | External deliverable không thấy năng lực agent (không cần) |
| Agent skill = trust tier thấp hơn pack | Skill từ user-data/template chưa được review; pack repo-vetted | Thêm wrap + scrub cho agent skill |
| Collision không shadow pack (rename) | Vetted pack skill không bao giờ bị file gitignored thay ngầm (M4) | Có thể 2 skill gần tên nhau |
| Schema lỗi `memory:` → RuntimeError | Entrypoint chỉ catch `(FileNotFoundError, RuntimeError)`; ValueError escape thành traceback | Khớp convention `_parse_inbox` |

## Vấp & học được
- **Red-team-plan-trước-cook cứu cả nửa plan**: plan viết phần kioku theo CLI TƯỞNG TƯỢNG.
  Nếu cook thẳng sẽ code xong adapter rồi mới đụng dist (npm E404) / injection / race — tốn
  công lớn. Đối chiếu repo dependency THẬT ở tầng plan là rẻ nhất.
- **Site thứ 6 bị bỏ sót**: plan ban đầu liệt 5 site đọc `loaded.memory`; grep ra 6 —
  `qa_answer.py` (Q&A path Telegram/inbox). Đếm bằng grep, đừng tin liệt kê tay.
- **LoadedProfile stub cũ trong test thiếu `memory_config`** → `resolve_memory_text` dùng
  `getattr(loaded, "memory_config", None) or MemoryConfig()` để backward-compat với stub.

## Mở / sang sau
- **v19.5 (kioku)**: nháp đã tạo (`plans/260711-1543-v195-kioku-memory-adapter/`) với 7 điều
  kiện tiên quyết từ red-team (dist/env-scrub/network-pin/recall-query/wrap/flock/health-probe).
- **Known-limitation**: memory_node (Store P8, report runs) tách khỏi seam — facts học ở report
  run không vào vault (khi kioku về); ghi để v19.5 không phát hiện lại.
- Tiếp: v20 channel binding account→agent (mỗi agent 1 bot Telegram, OpenClaw-style).
