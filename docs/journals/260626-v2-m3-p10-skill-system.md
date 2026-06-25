# v2 M3-P10 — Skill system (bundled PM guidance, LLM auto-select)

**Ngày:** 2026-06-26 · **Trạng thái:** ✅ Done · **Commits:** S1 `8e6de3d` · S2 `3413261` · S3 `ab5c9b7`

## Mục tiêu

Agent có "kỹ năng" PM dạng hướng dẫn: 5 file `skills/*.md` bundled (frontmatter
name/description/applies_to + body tiếng Việt). Một LLM selector tự chọn skill liên quan
trước khi compose, body chèn vào prompt — đi đúng đường persona/project/memory. C1 only:
chỉ markdown instruction, KHÔNG `.skill` ZIP, KHÔNG slash, KHÔNG cấp `allowed-tools`.

## Đã làm (3 slice)

- **S1** — `skill_loader.load_skills()` parse frontmatter (`---` split + `yaml.safe_load`),
  skip file hỏng (không raise). `Skill` frozen dataclass (KHÔNG có field authority — bất
  biến C1). 5 skill: flag-risk, prioritize-blockers, estimate-effort, fetch-jira-epics,
  parse-github-labels. `profile.yaml` thêm block `skills:` → `LoadedProfile.skills` (tuple
  tên, theo y hệt `reports`). `default` không có block → `()`.
- **S2** — `SkillSelector = Callable` (inject được, fake offline — mirror P8
  `MemoryExtractor`); `make_llm_selector` chịu lỗi LLM → `[]`. `select_skill_text` chỉ chạy
  selector khi audience=internal, lọc tên đã chọn về đúng pool (chống LLM bịa tên), render
  `<pm_skills>`. `ProfileContext` thêm `skills`/`skill_selector`. Chèn `skills=` vào nhánh
  INTERNAL của cả 3 builder (report/okr/resource).
- **S3** — `skill_pool.build_skill_context(loaded, settings)`: load pool + dựng selector,
  nhưng pool rỗng → `((), None)` KHÔNG dựng `LlmClient` (default profile khỏi cần key, cấp
  phát allocation-free). Wire qua 3 entry point worker/cron/cli; server (M2-P6) thừa hưởng
  qua worker. Tên skill lạ → warn + bỏ, không crash. 14 e2e offline.

## Lằn ranh đỏ (giữ vững)

Skill body chỉ chèn INTERNAL — báo cáo external (stakeholder) KHÔNG lấy gì từ skill (đúng
lằn ranh PII Phase 5). Phòng thủ 2 lớp: `select_skill_text` trả `""` cho external VÀ nhánh
external của mỗi builder return TRƯỚC khi đụng `skills`. Review S3 mutation-proven: gỡ 1 lớp
vẫn xanh vì lớp builder mới là cổng external authoritative. Skill là instruction-only —
không đi qua Action Gateway, không có tool authority.

## Kết quả

592 test xanh (545 baseline + 47 mới), ruff sạch. Code-reviewer chạy mỗi slice — đều DONE,
không CRITICAL/HIGH. No-skills byte-identical với pre-P10 (backward-compat thuần additive).

## Deviation chấp nhận

`report_prompt.py` (209) + `resource_report_prompt.py` (244) vẫn >200 LOC — file prompt có
sẵn, S2 thêm ~6 dòng mỗi file, tách prose sẽ hại readability (nhất quán deviation >200-LOC
từ P1).

## Còn lại / mở

- Production e2e với key thật + profile có `skills:` để xác nhận lằn ranh đỏ live (chưa
  chạy — toàn bộ proof là offline với fake selector + recording LLM).
- C2 (`.skill` ZIP upload), `allowed-tools` enforcement, slash activation: ngoài scope, hoãn.
