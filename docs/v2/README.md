---
title: "v2 Vision + Roadmap — Multi-agent PM platform"
description: "From a single-project PM agent to N profile-bound agents managed from a web dashboard, guardrail preserved per-agent."
status: v2 COMPLETE (M1+M2+M3 all shipped, 776 tests, final live E2E verified 2026-06-27)
created: 2026-06-23
supersedes: extends ../v1/project-roadmap.md (picks up its deferred items: service backend, multi-user, Postgres scale-up)
priority: P2
tags: [v2, vision, roadmap, multi-agent, langgraph, web-ui]
---

# v2 Vision + Roadmap — my-project-manager

> Status: **v2 COMPLETE** (2026-06-27, M1+M2+M3 = 776 tests, final live E2E verified).
> - **M1**: Multi-agent core (P1–P4, profiles + registry/worker + scheduler + CLI), 414 tests.
> - **M2**: Platform (P5–P8, interrupts + FastAPI/SSE + dashboard + Postgres opt-in), 545 tests.
> - **M3**: Extensibility (P10/P9/P11/P12, skills + cross-agent memory + integrations/multi-channel + automation/observability), 776 tests, live E2E: Jira 21 issue, real Confluence + Slack post, Postgres facts, replay+automate via gateway.
>
> Mở rộng [`../v1/project-roadmap.md`](../v1/project-roadmap.md) (v1 Phase 0–5 đã xong). v1 = single-agent, single-project.
> v2 = **nhiều agent, mỗi agent một project, XONG TOÀN BỘ (multi-agent core + interrupts + streaming + optional Postgres + web dashboard + skills + integrations + automation), guardrail giữ nguyên per-agent.**
> Bilingual: prose tiếng Việt, code/identifier tiếng Anh.

## Bộ tài liệu v2 (chia nhỏ để dễ maintain)

| File | Nội dung |
|---|---|
| **README.md** (file này) | Vision + tóm tắt thay đổi vs v1 + index |
| [profile-design.md](profile-design.md) | **Centerpiece**: thiết kế agent profile (thư mục 4 file: `profile.yaml` + `SOUL.md` + `PROJECT.md` + `MEMORY.md`) |
| [architecture.md](architecture.md) | Kiến trúc target (registry → service → worker → per-agent gateway) + cái GIỮ từ v1 + cross-cutting principles |
| [roadmap-m1.md](roadmap-m1.md) | **Milestone M1** — multi-agent core (config refactor → profile → registry/worker → CLI) |
| [roadmap-m2.md](roadmap-m2.md) | **Milestone M2** — web UI + LangGraph upgrades (interrupts / streaming / Postgres+Store) |
| [feature-proposals.md](feature-proposals.md) | **Đề xuất tính năng** từ research 3 repo (memory / observability / skill / channel) → phần lớn thành **M3** |
| [risks-open-questions.md](risks-open-questions.md) | Rủi ro + câu hỏi mở (cross-cutting, hay cập nhật) |

## 1. Vision

v1 chứng minh được một luận điểm: một LLM agent có thể **full autonomous write** vào Jira/GitHub/Slack/Confluence mà vẫn an toàn, nhờ Action Gateway (Lớp A hard-deny + Lớp B approve + audit + budget + dedup). Nhưng v1 chỉ phục vụ **một project**, cấu hình qua **một file `.env` toàn cục**, kích hoạt qua **CLI/cron**. Muốn theo dõi project thứ hai phải clone repo hoặc đổi `.env` — không scale.

v2 biến nó thành một **multi-agent PM platform**. Mỗi agent = **một thư mục `profiles/<id>/`** (4 file: `profile.yaml` config + `SOUL.md` persona + `PROJECT.md` context + `MEMORY.md` agent tự ghi) bound vào **một project** (Jira/GitHub/Slack/Confluence bindings riêng). Một **registry** liệt kê tất cả agent; một **coordinating service** spawn mỗi agent thành một **worker process** chạy graph của nó (theo lịch + on-demand), với **data isolation hoàn toàn** per-agent (`checkpoints/audit/budget/approvals/dedup` riêng từng agent). Bạn chạy 5 agent cho 5 project, mỗi cái tone + threshold + schedule + budget riêng, không cái nào đụng cái nào.

Trên hết là một **web dashboard** (React SPA via Vite+TypeScript, M4): thấy danh sách agent + trạng thái (running/idle/error), cost vs budget từng agent, audit gần đây, **các Lớp B approval đang chờ (approve/reject ngay trên UI, same real-post path as CLI)**, xem/sửa config từng agent (validate-before-write, atomic replace, MEMORY.md read-only), **trigger một report on-demand với SSE live streaming**. Đồng thời v2 khai thác sâu LangGraph mà v1 MVP chưa dùng: **graph-native interrupts** cho human-in-the-loop, **streaming** để UI xem agent chạy live, **Postgres checkpointer + Store** cho state đa-process + cross-thread memory. Điều bất biến: **Action Gateway guardrail được GIỮ NGUYÊN, chỉ trở thành per-agent** — red line Lớp A vẫn hard-coded trước LLM, mọi write vẫn qua một cổng, giờ một cổng *cho mỗi agent*.

## 2. What changes vs v1

| Khía cạnh | v1 (as-built) | v2 (target) |
|---|---|---|
| Số agent / project | 1 agent, 1 project | **N agent, mỗi agent 1 project** |
| Config | 2 `@lru_cache` singleton (`get_reporting_config`, `get_settings`) đọc `.env` toàn cục | **thư mục `profiles/<id>/` per-agent (4 file), inject làm parameter** vào graph/gateway/store/tool |
| Persona / prompt | system prompt hardcode trong `src/llm/*` | **`SOUL.md` + `PROJECT.md` override/prepend** lớp prompt |
| Kích hoạt | CLI + cron | CLI + **worker** + **web dashboard** (M4 React SPA) |
| Runtime | 1 process, chạy tay/launchd | **registry → coordinating service → N worker process** |
| Data | shared `.data/` (1 checkpoints/audit/budget/approvals/dedup) | **`.data/agents/<id>/` riêng từng agent**; `thread_id` chứa `agent_id` |
| Checkpointer | `SqliteSaver` (1 file) | **Postgres checkpointer** (multi-process) + **Store** (cross-thread memory) |
| Lớp B approval | gateway-level queue (`pending_approval` + `approval_store` + `cli approve`) | **graph-native interrupt** (pause→UI hỏi→resume, checkpoint-serialized) — augment/replace queue |
| Quan sát | đọc JSONL audit + `cli audit` | **web dashboard** (React SPA): status, cost, audit, pending approvals, streaming live run |
| **Guardrail** | Action Gateway (Lớp A/B + audit + budget + dedup) | **GIỮ NGUYÊN — chỉ trở thành per-agent** (mỗi agent một gateway + một bộ store) |

> Guardrail **không** bị viết lại. Lớp A red-line, allowlist-default-deny, audit, budget cap, dedup reserve-before-execute — tất cả giữ. Thay đổi duy nhất: chúng được khởi tạo *per-agent* (path + config từ profile) thay vì từ singleton toàn cục. Chi tiết: [architecture.md §7](architecture.md).

## Timeline (v2 COMPLETE)

**M1** [P1→P2→P3→P4](roadmap-m1.md) → **M2** [P5→P6→P7→P8](roadmap-m2.md) → **M3** [P10/P9/P11/P12](feature-proposals.md) — tất cả shipped. Xem [journals/](../journals/) để chi tiết từng phase (decisions + bugs + lessons). Deferred: live-key integration E2E (Linear/SMTP/LangSmith real), advanced workflow (when conditions, schedule triggers), safe re-fetch in replay.
