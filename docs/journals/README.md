# Dev Journal — my-project-manager

Dòng thời gian phát triển kiến trúc + tính năng (repo vừa-làm-vừa-học). Đọc bảng dưới để thấy cả hành trình; mở từng file cho chi tiết.

**Quy ước:** 1 file / mốc, **tiền tố ngày** `YYMMDD-<slug>.md` (vd `260622-phase-1-slice-2-confluence-report.md`) → sắp xếp theo thời gian, mỗi mốc tự ghi ngày. Súc tích theo template — chỉ ghi cái verify được, không bịa, không kể lể. Ghi ở mốc (phase/slice xong hoặc sự kiện đáng nhớ).

## Dòng thời gian

| Ngày | Mốc | Trạng thái | Tóm tắt |
|---|---|---|---|
| 2026-06-21 | [Phase 0 — Scaffold](260621-phase-0-scaffold.md) | ✅ Done | Hello-agent (LangGraph) + guardrail core. Chốt: tool qua MCP+CLI; allowlist + Lớp A hard-deny (2 vòng review). E2E OpenRouter OK. |
| 2026-06-21 | [Phase 1 Slice 1 — Reporting](260621-phase-1-slice-1-reporting.md) | ✅ Done | Jira+GitHub→Slack qua gateway. Agent SPAWN MCP subprocess (stdio-only). E2E post Slack thật. |
| 2026-06-22 | [Phase 1 Slice 2 — Confluence](260622-phase-1-slice-2-confluence-report.md) | ✅ Done | Report detail→Confluence + short+link→Slack. E2E thật cả 2. State chỉ primitive (fix checkpoint). |
| 2026-06-22 | [Phase 1 Slice 3 — Daily/Weekly + Cron](260622-phase-1-slice-3-daily-weekly-cron.md) | ✅ Done | `report --daily\|--weekly` (weekly + sprint data) + cron launchd. Phase 1 HOÀN TẤT. |
| 2026-06-22 | [Phase 2 — Guardrail Hardening](260622-phase-2-guardrail-hardening.md) | ✅ Done | Dedup bền + audit query + Lớp B interrupt (queue/approve). Reviewed, red-line verified. |
| 2026-06-22 | [Phase 3 — OKR Tracking](260622-phase-3-okr-tracking.md) | ✅ Done | OKR (Confluence table) → map epic → rollup có trọng số → report --okr + nhúng weekly. E2E + write thật. Fix bug duedate ở Jira MCP (overdue im lặng). |
| 2026-06-22 | [Phase 4 — Resource + Cost](260622-phase-4-resource-cost.md) | ✅ Done | Workload theo assignee (overload tương đối mean) + cost (LLM budget thật + labor ước lượng) → report --resource + nhúng weekly + cron. Review fix C1 (tên assignee inject Slack mrkdwn). |
| 2026-06-22 | [Phase 5 — Audience-split](260622-phase-5-audience-split.md) | ✅ Done | `--audience internal\|external` cả 4 report; external → giọng business + Lớp B duyệt. Review fix C1 (link Confluence rò PII). E2E lộ+vá gap Phase 2: approve giờ post thật. Service/bot/multi-user hoãn. |
| 2026-06-23 | [v2 M1-P1 — Config-injection](260623-v2-m1-p1-config-injection.md) | ✅ Done | Giết 2 config singleton (grep src/ = 0 hit). `from_dict` thuần + `from_env` wrapper; config inject làm tham số qua cả call graph. Mở đường P2 per-agent (`profile.yaml→dict→from_dict`). 282 test xanh. |
| 2026-06-24 | [v2 M1-P2 — Profile system](260624-v2-m1-p2-profile-system.md) | ✅ Done | Agent = thư mục `profiles/<id>/` (4 file: profile.yaml + SOUL/PROJECT/MEMORY.md). Loader env-fallback 3 tầng → `default` == v1. Inject persona/project/memory vào prompt; external KHÔNG lấy gì từ profile (guardrail PII). `--profile` ở cli/cron. 317 test xanh + E2E thật. |
| 2026-06-24 | [v2 M1-P3 — Registry + worker](260624-v2-m1-p3-registry-worker.md) | ✅ Done | N agent cô lập: `registry.yaml` + worker subprocess (1 process/agent, `.data/agents/<id>/`) + service daemon (cron `schedule:` qua croniter, cap 4, timeout 600s). Cô lập rơi ra từ 1 `data_dir`; auto-migrate `.data/` v1. thread_id `<id>:<kind>:<audience>`. 383 test + E2E spawn thật. |
| 2026-06-24 | [v2 M1-P4 — Multi-agent CLI](260624-v2-m1-p4-multi-agent-cli.md) 🏁 | ✅ Done | `mpm agent list/register/run/approvals/approve/reject/audit`. Surface multi-agent trên primitive P3 (additive, cli/cron giữ legacy). `run` spawn worker (lock-step argv với service); approvals/audit per-agent = GAP-CLOSER (đọc `.data/agents/<id>/` mà cli global không thấy sau migrate). 414 test + E2E thật. **🏁 ĐÓNG MILESTONE 1** (P1→P2→P3→P4). |
| 2026-06-24 | [🏁 v2 Milestone 1 COMPLETE](260624-v2-m1-milestone-complete.md) | ✅ Done | **Tổng kết milestone**: 1 agent (v1) → N agent cô lập hoàn toàn qua CLI/worker + scheduler, guardrail per-agent. 17 commit, 414 test, E2E thật. Retrospective + bài học xuyên P1–P4. Sang M2 (web dashboard + Postgres + streaming). |
| 2026-06-24 | [v2 M2-P5 — Graph interrupt](260624-v2-m2-p5-graph-interrupts.md) | ✅ Done | Mốc đầu M2. Lớp B → LangGraph `interrupt()` thật: node `approval_gate` (3 graph) pause external trước deliver, checkpoint-serialize, resume `Command(resume=...)`. `execute_approved()` post LIVE (fix C1: trước đó re-queue lần 2). `worker --resume` + `mpm agent resume`, exit 3 + run-event `interrupted`. AUGMENT (queue giữ, replace ở P8). 443 test + E2E thật (post Slack + reject sạch). |
| 2026-06-25 | [v2 M2-P6 — FastAPI + SSE](260625-v2-m2-p6-fastapi-sse.md) | ✅ Done | Web surface M2: FastAPI localhost (list/status/trigger/stream). Trigger chạy graph in-process (sync `stream` trong thread vì sync SqliteSaver), SSE phát node-progress LIVE + terminal `interrupted`. `summarize_node` = PII firewall allowlist. Cap 4, single-drain (409). E2E bắt 2 bug fake che mất (astream-vs-sync-saver + empty-box-on-resume) → vá + test thật. P5↔P6: `mpm agent resume` đọc checkpoint server tạo → post thật. 490 test. |

## Template entry (`YYMMDD-<slug>.md`)

```markdown
# <Tiêu đề mốc>
<ngày> · <trạng thái>

## Làm gì
3-5 gạch: tính năng/kiến trúc đã build (cái verify được).

## Quyết định & vì sao
Bảng: Quyết định | Vì sao | Đánh đổi. Chỉ mốc đáng nhớ.

## Vấp & học được
2-4 gạch: sai gì → rút ra gì. Ngắn.

## Mở / sang sau
1-3 gạch.
```

Sau khi viết entry, thêm 1 dòng vào bảng dòng thời gian trên.
