# v2 M2-P6 — Streaming + FastAPI service

2026-06-25 · ✅ Done (4 slice, `1aeb3f5`→`ac074ed`, 490 test, E2E thật)

> Web surface đầu của M2. FastAPI localhost-only: list/status/trigger agent + **stream live** node-progress qua SSE. Trigger chạy graph **in-process** (không subprocess) để stream trực tiếp. Scheduled run vẫn qua worker (P3) — đây là surface on-demand + quan sát.

## Làm gì

- **4 route** (`src/server/`): `GET /api/agents` (list), `GET /api/agents/{id}/status` (budget vs cap + pending-approval count), `POST /api/agents/{id}/trigger` (chạy graph in-process trong asyncio task → `{run_id, thread_id}`), `GET /api/runs/{run_id}/stream` (SSE — 1 event/node + 1 terminal).
- **In-process streaming:** trigger build `build_graph_for` rồi chạy **sync `graph.stream` trong thread** (graph dùng sync SqliteSaver), bridge từng chunk sang `asyncio.Queue`. SSE phát `perceive→analyze→compose_report→deliver` LIVE. External → terminal `interrupted` (kèm thread_id + summary non-PII); resume vẫn qua P5 `mpm agent resume` (stream KHÔNG block).
- **`summarize_node` = PII firewall (allowlist):** mỗi node project về field non-PII (risk_count / cost_usd / delivered) — persona/project/memory/per-assignee KHÔNG bao giờ tới client, kể cả node tương lai rò vào delta.
- **Concurrency:** 1 `RunManager`/process; same (agent,thread) đang chạy → 409, cap 4 toàn cục → 503, agent khác chạy song song. Single-drain: attach thứ 2 vào run đang chạy → 409; late-attach sau khi xong → replay terminal cache. Enqueue non-blocking (drop-oldest) nên reader chậm/vắng không wedge slot.
- **Security:** localhost-only (bind 127.0.0.1), KHÔNG auth (M2 1-operator sandbox; expose ra ngoài cần auth — hoãn). DRY_RUN + guardrail per-agent (Lớp A/B + audit + budget + dedup) vẫn áp cho mọi trigger.
- **E2E thật** (uvicorn thật, graph thật, profile default): trigger external → SSE node events live + terminal interrupted → `mpm agent resume` đọc checkpoint **SERVER tạo** (P5↔P6) → resume external resource → **post Slack thật + Confluence page thật**, `delivered=True`.

## Quyết định & vì sao

| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| In-process trigger (không subprocess) | Để stream node-event trực tiếp từ graph đang chạy; subprocess không giữ được live graph để stream | Scheduled run vẫn qua worker (2 path) |
| Sync `graph.stream` trong `asyncio.to_thread` | Graph dùng sync SqliteSaver (chung với worker/mpm-resume → checkpoint tương thích); `astream` từ chối sync saver. Thread giữ loop free | Bridge chunk qua `call_soon_threadsafe` |
| localhost + no-auth | M2 1 operator; service trigger được write thật → KHÔNG expose ngoài 127.0.0.1 khi chưa có auth | Auth hoãn (ghi rõ docstring) |
| Single-drain + 409 (không full fan-out) | M2 1 operator; fan-out per-subscriber là over-eng. 409 đóng được hang | Multi-watcher hoãn P7 |
| Checkpoint URL-free short ở compose (Slice 4) | Resume rebuild graph → box rỗng → deliver cần data từ STATE, không phải closure | Thêm 1 state key + inject link ở deliver |

## Vấp & học được

- **E2E bắt 2 bug mà fake-graph unit test che mất** (lại bài học P5):
  1. **astream vs sync saver:** `_drive` gọi `graph.astream()` nhưng graph dùng sync SqliteSaver → "does not support async methods". Fake graph có `async astream` nên xanh giả. → chạy sync `graph.stream` trong thread + **test bằng SqliteSaver thật**.
  2. **empty-box on resume (bug P5 cũ):** 3 graph giữ model nặng trong closure `box`, không checkpoint. Resume rebuild graph → box rỗng → okr/resource KeyError, daily post short degrade ("không phát hiện rủi ro"). Test cũ reuse CÙNG graph object nên box sống sót → che mất. → checkpoint short ở compose; **test rebuild graph giữa pause↔resume**.
- **TestClient loop-per-request** không share background task giữa request → 409/503 + stream-live test phải drive trực tiếp (asyncio.run), không qua TestClient trigger→stream.
- **Review bắt + vá trước khi land:** broken-profile 500 (degrade như CLI), gateway connection leak per /status (đọc count qua ApprovalStore đóng), watcher-less queue hang (drop-oldest), audience silent-coerce (422), concurrent-attach hang (409).

## Mở / sang sau

- File >200 LOC: report_graph 299 / okr 230 / resource 237 (pre-existing over, Slice 4 +~10 mỗi cái) — modularize hoãn.
- Multi-watcher fan-out (xem nhiều client 1 run) hoãn P7 nếu dashboard cần.
- Resume vẫn operator-triggered (`mpm agent resume`); service-driven auto-resume (UI duyệt → service spawn resume) là **P7**.
- **Sang P7:** web dashboard (HTMX/Streamlit) trên 4 route này — list/status/cost/approve/trigger/config. Rồi **P8** Postgres checkpointer + Store (resume bền multi-process + cross-thread memory).
