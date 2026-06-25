# 🏁 v2 Milestone 2 CORE COMPLETE — interrupts + streaming + persistence

2026-06-25 · ✅ Done (P5/P6/P8, 12 commit, 518 test xanh; P7 dashboard hoãn)

> Tổng kết milestone. Chi tiết từng phase ở 3 journal P5/P6/P8. Đây là cái nhìn toàn cảnh + retrospective + kết quả E2E thật toàn M2.

## Đạt được

Backend v2 hoàn chỉnh trên nền M1 (N agent cô lập): **Lớp B graph-native interrupt** (pause→resume bền), **FastAPI + SSE streaming** (xem agent chạy live), **Postgres checkpointer + Store + cross-thread memory** (state bền multi-process + agent tự nhớ xuyên run). Verify cả unit (518 test) lẫn **E2E thật toàn bộ pattern** — Jira/Slack/Confluence thật + 1 Postgres throwaway thật. Nửa còn lại của M2 — **P7 web dashboard (UI)** — hoãn; backend đã đủ.

| Phase | Giao | Commit |
|---|---|---|
| **P5** Graph interrupt | Node `approval_gate` (3 graph) pause external trước deliver, checkpoint-serialize, resume `Command(resume=...)`. `execute_approved()` post LIVE. `worker --resume` + `mpm agent resume`, exit 3 + run-event `interrupted`. AUGMENT queue (replace ở P8). | `a82dad5`…`92110b1` |
| **P6** FastAPI + SSE | 4 route localhost (list/status/trigger/stream). Trigger chạy graph in-process (sync `stream` trong thread), SSE node-progress LIVE + terminal `interrupted`. `summarize_node` PII firewall. Cap 4, single-drain (409). | `1aeb3f5`…`d12214d` |
| **P8** Postgres + Store + memory | `get_checkpointer/get_store(settings)` chọn sqlite\|postgres / memory\|postgres (opt-in, SQLite default). Cross-thread memory: extractor LLM → Store content-hash + mirror MEMORY.md (internal-only, KHÔNG qua gateway). | `e68a811`…`8ed63d2` |

## Đặc tính cốt lõi M2

- **Lớp B = graph-native interrupt** (P5): graph pause thật tại node, state checkpoint, resume deterministic. AUGMENT — queue gateway (P2) vẫn còn; cả 2 đường tồn tại. `execute_approved` cho phép approve→post LIVE mà KHÔNG re-queue.
- **1 seam, mọi path thừa hưởng:** `build_graph_for` (worker) là chỗ duy nhất build graph + chọn checkpointer/store + gắn remember node → P5-resume + P6-server + P8-memory đều tự động dùng chung. Đổi 1 chỗ, lan khắp.
- **Sync saver xuyên suốt:** graph dùng sync SqliteSaver/PostgresSaver (chung với worker/resume → checkpoint tương thích). P6 server chạy sync `graph.stream` TRONG thread (không `astream`) để khỏi đụng sync-saver + giữ event loop free.
- **Memory = state NỘI BỘ:** Store + MEMORY.md như checkpointer — KHÔNG qua Action Gateway (gateway = external mutation). MEMORY.md inject internal-only → agent memory KHÔNG BAO GIỜ tới external. Guardrail PII giữ nguyên.
- **Opt-in, default tự chứa:** SQLite + InMemoryStore là default (không cần infra). Postgres chỉ bật khi `runtime: postgres_dsn`.

## E2E thật toàn M2 (real data, mọi pattern)

2 agent: `default` (SQLite+InMemory) + `pg-agent` (Postgres throwaway). Mọi pattern xanh:

| Pattern | Kết quả |
|---|---|
| P5 pause / approve / reject | pause exit 3 · resume approve → post Slack thật (`ts 1782392110`) + Confluence thật · reject → KHÔNG post |
| P6 list/status · trigger→stream · external-interrupt · 409 | read route đúng data 2 backend · SSE live `perceive→analyze→compose→approval_gate→deliver→remember→terminal` · external → `terminal:interrupted` · same-thread 2nd → 409 |
| P8 cross-thread memory | run 1 ghi 5 fact → MEMORY.md → run 2 đọc lại · internal prompt có memory, external KHÔNG |
| P8 **Postgres thật** | `checkpoints` = 8 row + `store` = 5 fact trong PG thật — đóng gap "selection-only" |
| Lớp B queue approve (PG agent) | `mpm agent approve` → post Slack thật (`ts 1782392057`) |

**1 lần stream chứng minh cả 3 feature M2 cùng lúc** (approval_gate + SSE + remember). MEMORY.md đúng **1 cặp marker** trên cả 2 agent sau nhiều lần ghi (fix C1/C2 verify trên data thật). Dọn sạch: profile default restore, pg-agent xóa (có DSN thật), container PG hủy → tree sạch.

## Bài học xuyên milestone

- **E2E thật bắt bug mà mock + selection-test che mất (lặp lại từ M1, mạnh hơn ở M2):** P6 astream-vs-sync-saver + empty-box-on-resume; P5 C1 re-queue-thay-vì-post; P8 C1 Postgres conn-leak (`__enter__` để GC đóng connection) + C2 MEMORY.md marker-doubling. Tất cả unit test happy-path xanh giả; chỉ E2E / review adversarial bắt. → **test write-once/mock-graph không đủ; cần repeated-write + real-saver + chạy thật.**
- **Review adversarial = lưới thứ 2:** mỗi slice code-review bắt buộc bắt được CRITICAL (C1 P5, C1 P8-saver, C1/C2 P8-memory). Reviewer reproduce bug bằng smoke độc lập trước khi assert. Không slice nào land với CRITICAL hở.
- **Plan R-risk dự đoán đúng nhưng code làm ngược:** P8 R3 đã dặn "mở raw connection, đừng dùng `with`" — code làm `__enter__()` (ngược). Review bắt lại đúng R3. → đọc lại plan's risk khi code đúng chỗ rủi ro.
- **Guardrail red-line không lay chuyển:** P5 PII (external lấy không gì), P8 memory internal-only + không qua gateway — verify bằng test riêng MỖI slice, không chỉ tin comment.
- **Slice plumbing-trước, behavior-sau:** P8 S1+S2 (checkpointer+store selection) là plumbing thuần (default không đổi hành vi, 490 test giữ xanh); S3 mới đổi behavior. Mỗi slice giữ default → baseline luôn xanh.

## Mở / sang sau

- **P7 web dashboard (UI)** — nửa còn lại M2, HOÃN: HTMX/Streamlit trên 4 route P6 + approve/config/trigger. Backend đã đủ; chỉ thiếu frontend.
- **Postgres production:** runtime đã verify trên PG throwaway, nhưng cần (a) connection-pool cho concurrency thật, (b) quyết lifecycle saver dài hạn, trước khi nói "Postgres production-ready".
- **Cosmetic:** extractor để sót markdown (`SCRUM-15**`) — `_parse_facts` strip bullet đầu nhưng không strip `**`/`*` cuối. 1 dòng regex.
- File >200 LOC tồn từ trước (cli 318, action_gateway 351, 3 report graph ~230-300) — M2 không đẻ ra, modularize hoãn.
- **M3:** xem [feature-proposals](../v2/feature-proposals.md) — cross-agent memory, skill library, MCP gateway, workflow automation. P7 dashboard có thể vào đầu M3.
