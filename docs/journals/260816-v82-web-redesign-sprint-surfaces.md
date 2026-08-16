# v82 — Web redesign: perf data layer + sprint surfaces lên UI
2026-08-16 · ✅ Done

## Làm gì
- **Perf data layer** (điểm đau "vào màn hình chờ lâu"): `fetchCached` TTL 5s + in-flight dedupe cho các endpoint gọi trùng; SSE resume theo seq; paginate board; three.js rời main bundle — `index-*.js` 1628KB → 764KB (-53%), three.js nằm trong chunk lazy `agent-desk` 880KB chỉ tải khi mở góc 3D.
- **3 bug fix**: ArtifactPanel lọc mất step sprint (dùng chung `DELIVERED_STEP_TYPES` với backend); `step_activity` vắng trong ActivityFeed; `external_action` render dòng rỗng.
- **4 surface sprint (v81 lên web)**: badge SPRINT/TEAM trong preview giao việc (`route_mode` từ gateway); `GET /api/team-tasks/{id}/route` → 1 dòng "Đường đi: SPRINT — vì sao" trong expand thẻ kanban; tab "Quá trình" trong ArtifactViewer (`GET /api/office/tasks/{id}/steps/{seq}/transcript` đọc JSONL v80 theo data-dir của agent làm bước đó, attempt mới nhất theo mtime, chỉ high ui-mode); `GET /api/team-tasks/{id}/metrics` bọc `bench.task_metrics.load_task_metric` store-only → dòng "⏱ 3m19s · N bước" cùng chỗ.
- Hoàn thiện: i18n vi/en đủ cặp, CSS chỉ dùng token có sẵn (dark theme tự đúng), 2 Playwright smoke mới (badge sprint + tab transcript). Suite cuối: **3357 BE + 297 FE + 10 e2e**, ruff/tsc/build sạch.
- **Retire block "Việc đã giao"** (CEO chốt): xoá Tasks.tsx + toàn bộ i18n/CSS/types/api client của nó khỏi trang Việc — trùng chức năng với kanban team-task. Backend `/api/tasks` giữ nguyên cho API/CLI (task legacy watch/report/qa vẫn huỷ được qua API).

## Quyết định & vì sao
| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| Route/metrics fetch lazy trong expand thẻ, không fan-out per-card | Đúng lời phàn nàn gốc: màn hình load quá nhiều data cùng lúc | Số liệu chỉ hiện khi mở thẻ |
| `/route` trả field rỗng, `/metrics` trả 404 khi task lạ | Route: vắng là trạng thái bình thường (task trước route_json); metrics: không có shape "rỗng có nghĩa" | Hai discipline khác nhau trên 2 route cạnh nhau — ghi rõ trong docstring |
| Transcript route đặt ở `/api/office/tasks/...` thay vì `/api/team-tasks/...` như design | Nằm cạnh route artifact mà ArtifactViewer đang dùng — FE surface nhất quán thắng sơ đồ trên giấy | Lệch design doc, ghi chú lại |
| `_parse_events` → public `parse_transcript_events` | Route mới cần parser; import hàm `_private` xuyên module là smell | — |
| Allowlist `_ROUTE_FIELDS` không có `signals` | Keyword match thô trên brief là noise nội bộ, không phải thứ CEO cần đọc | — |

## Vấp & học được
- Test cũ assert `==` nguyên body preview → thêm `route_mode` làm gãy; sửa test và nhân tiện thêm test badge chưa từng có (item 1 đã ship không kèm test).
- jsdom của suite này không có `localStorage` hoạt động — test high ui-mode phải `vi.stubGlobal` như `ui-mode-context.test.tsx`, không set thẳng.
- ArtifactViewer thêm `useUiMode()` làm 5 test cũ render thiếu provider nổ ngay — hook context mới trong component cũ là breaking change với mọi test render trực tiếp nó.

## Mở / sang sau
- Cache tay chưa có stale-while-revalidate; nếu cần mutation queue thì cân nhắc react-query.
- Backend `/api/tasks` giờ không còn FE nào gọi — nếu task legacy (watch/report/qa) cũng retire thì gỡ nốt route + store.
