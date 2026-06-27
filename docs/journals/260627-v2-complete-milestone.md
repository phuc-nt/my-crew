# 🏁 v2 COMPLETE — Multi-agent platform (M1+M2+M3)

2026-06-27 · ✅ Done · 776 tests, ruff clean, final live E2E verified

> Tổng kết v2 toàn bộ (3 milestone). Chi tiết từng phase ở journals riêng. Đây là cái nhìn toàn cảnh, khoá học, và kế tiếp.

## Đạt được

v2 = từ **1 agent / 1 project** (v1) → **N agent / N project, cô lập hoàn toàn, web dashboard, multi-channel, automation** — 3 milestone, 28 commit, 776 test xanh. Verify toàn surface qua E2E live (Jira/Slack/Confluence/Postgres thật).

| Milestone | Giao | Commit | Test |
|---|---|---|---|
| **M1** Multi-agent core | Config-injection + profile system + registry/worker/service + multi-agent CLI | P1→P2→P3→P4 | 414 |
| **M2** Platform | Graph interrupt + FastAPI/SSE + web dashboard + Postgres/Store/memory opt-in | P5→P6→P7→P8 | 545 |
| **M3** Extensibility | Skill system + cross-agent memory + integrations/multi-channel + automation/observability | P10/P9/P11/P12 | 776 |

## M1: Multi-agent core (282 test → 414)

Transformer: mỗi agent = 1 thư mục `profiles/<id>/` (4 file: yaml + SOUL/PROJECT/MEMORY.md), cô lập hoàn toàn (`data_dir` đơn tiếp → cả 5 store). Cổng guardrail áp dụng per-agent (không rewrite, chỉ inject `settings`). CLI `mpm agent list/register/run/approvals/approve/reject/audit`. **Không có UI, không Postgres, không streaming** — đơn thuần backend + CLI.

Bài học M1: Smoke E2E (2 agent thật spawn cùng lúc + 2 approval store riêng) phát 1 bug singleton-cache mà unit test không bắt. Validate ở 1 biên (registry agent_id) → mọi downstream (path, argv, thread_id) tin tưởng.

## M2: Platform (414 test → 545)

**LangGraph interrupt + streaming + dashboard + Postgres** (tất cả opt-in): node `approval_gate` thật (checkpoint pause/resume, không queue); FastAPI localhost 4 route (list/status/trigger/stream) + HTMX dashboard 6 surface (list/cost, on-UI approve/reject, audit, config view/edit, trigger+SSE); Postgres checkpointer + Store + cross-thread agent memory (extractor LLM → Store, mirror MEMORY.md section, inject internal-only).

Bài học M2 (mạnh hơn): E2E thật bắt 5 CRITICAL bug mà unit + selection-test che mất — astream-vs-sync-saver, re-queue-thay-vì-post, Postgres conn-leak, MEMORY.md marker-doubling, summarize-node PII rò. Review adversarial + repeated-write = lưới thứ 2 không thể bỏ qua. Guardrail red-line (external KHÔNG memory, memory KHÔNG gateway) verify bằng test mỗi slice, không chỉ tin comment.

## M3: Extensibility (545 test → 776)

**Skill system + cross-agent memory + integrations + workflow automation**: 5 bundled skill (instruction-only, KHÔNG tool), injectable LLM selector → internal prompt; sibling discovery + cross-agent fact read (Store namespace) + injectable ranker → internal; config-driven extra MCP (Linear read + gated-write Lớp B) + Email/SMTP (new action type, ALL email = Lớp B) + channel registry; opt-in LangSmith tracing (B4, off=byte-identical) + checkpoint replay (B3, dedup + refuse-unsafe) + workflow automation (D3, READ+analyze+PROPOSE, never auto-exec).

Bài học M3: Mỗi feature (P10/P9/P11/P12) là 3–4 slice, đoàn-tóm. Slice-per-commit + code-review bắt buộc → không CRITICAL nào land. Live E2E bắt 1 bug final (`LlmResult.text`→`.content`), vá + regression test. Lằn ranh đỏ KHÔNG lay: Action Gateway, external→Lớp B, memory→internal-only, automation→PROPOSE-not-execute.

## E2E live toàn surface (2026-06-27)

1 agent throwaway `e2e-final` (Postgres thật, dry_run=false). Verify TOÀN cái hành:

| Khía cạnh | Kết quả live |
|---|---|
| M1 read | Jira SCRUM 21 issue |
| M2 compose+deliver | Confluence page thật (id 2064385, V2 API 200) |
| M2 approve→post | Slack Lớp B queue → mpm agent approve → post Slack thật (ts 1782532805) |
| M2 Postgres | 8 checkpoint + 5 fact Store trong PG thật |
| M3 skills | Skill bundled thấy trong prompt, external 0 skill |
| M3 cross-agent memory | Sibling share 20 fact, internal có memory, external không |
| M3 integrations | Linear MCP thấy, Email SMTP STARTTLS thật (nội bộ Lớp B) |
| M3 B4 tracing | OFF byte-identical, ON → callbacks len 1 |
| M3 B3 replay | List 8 checkpoint, replay approve_gate → dedup chặn, unsafe refuse |
| M3 D3 automate | dry-run (0 enqueue), propose external → Lớp B, propose non-external → skipped |

Dọn sạch (profile + container + registry entry KHÔNG track).

## Quyết định xuyên v2 (bảo vệ red-line)

| Quyết định | Thực hành | Vì sao |
|---|---|---|
| Guardrail per-agent, KHÔNG rewrite | Mỗi agent = riêng action_gateway instance + settings | Cô lập hoàn toàn, giới hạn blast-radius |
| External KHÔNG lấy persona/project/memory | 3 test riêng mỗi slice; LLM selector + inject = internal-only | PII = red-line non-negotiable (v1 Phase 5 tiếp tục) |
| Memory KHÔNG qua gateway | Store + MEMORY.md = checkpoint-level state, như checkpointer | Memory = hành vi graph internal; exterior không thấy |
| Automation KHÔNG tự thực thi | PROPOSE enqueue Lớp B, không execute handler | Autonomy ≠ responsibility; mutation luôn queue approval |
| Replay = frozen-state, không re-fetch | safe-replay guard: chỉ deliver/approval_gate/terminal | Avoid re-read-mà-data-đã-thay, non-idempotent |

## Bài học xuyên v2 (từ M1→M3)

1. **E2E live > unit + mock**: 6 CRITICAL bug (astream/conn-leak/marker/PII/LlmResult) bị mock che. Offline test = giả an toàn. → Luôn smoke thật trước close, verify real data path + real saver + real dependency.

2. **Review adversarial là lưới thứ 2**: Mỗi slice bắt buộc code-review bằng independent smoke (không dùng mock graph của implementer). Reviewer repeat bug để chứng minh trước assert. → Không slice nào CRITICAL land nếu review đủ tiêu chuẩn.

3. **Validate ở 1 biên, tin downstream**: agent_id validate ở registry → mọi code dùng id assume clean; channel validate ở channel-registry → downstream trust. Không spread validation → security boundary mờ.

4. **Slice-per-commit, mỗi commit runnable**: P1 BREAKING (singleton kill), P3 BREAKING (thread_id hình dạng), nhưng `default` profile + auto-migrate = lưới. Mỗi slice tự chạy → git-bisect không gây sân khấu chết.

5. **Lằn ranh đỏ ≠ comment, = test + observe**: "external không gì" = nhân thực bằng 3 test riêng (builder-not-inject, inject-internal-only, external-saver-noops). Mock không đủ; observe thật giá trị inject hay không.

6. **Guardrail KHÔNG rewrite khi add feature**: M3 thêm 4 feature, mỗi cái có write surface (skill không có, cross-agent có read, integrations có write, automation có propose). **TOÀN BỘ qua Action Gateway**, không bypass. → Guardrail = seam cô định, new write = add allowlist rule, không add new bypass.

## Mở / sang sau

- **Live-key integration E2E**: Linear (real createComment) + SMTP (real inbound) + LangSmith (real flush) — defer vì cần live credential, audit/approval lý luận không đủ chứng minh (vs dry-run). Scheduled sau shipping.
- **Boolean `when` + schedule-triggered automation**: D3 v1 = READ+analyze+propose; v2 defer = READ+analyze+when? propose. Giới hạn M3: automation = on-demand CLI, chưa schedule. Sang sau nếu cần.
- **Replay re-fetch safety**: B3 v1 = frozen-state (replay không fetch live). Sang sau nếu cần selective re-fetch (với lịch sử + audit).
- **File modularize**: cli 318 LOC, action_gateway 351, report_graph ~250 — tồn từ v1, M1-M3 không đẻ. Cân nhắc nếu maintenance khó.

## Kết thúc

**v2 XONG.** M1 (core) + M2 (platform) + M3 (extensibility) = 776 test, 28 commit, 1 final live E2E, 1 bug vá, **lằn ranh đỏ giữ xuyên 3 milestone** (Action Gateway, allowlist, Lớp A/B, audit, memory internal). Guardrail + multi-agent + web dashboard + integrations = production-ready pattern để xây dựng autonomous agent an toàn. Tiếp theo = expand domain (thêm tool/channel) hoặc user-facing (multi-user, role-based).

Xem [journals/README.md](README.md) để timeline toàn hành trình (Phase 0–5 v1 + M1–M3 v2).
