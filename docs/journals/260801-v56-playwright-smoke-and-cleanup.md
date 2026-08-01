# v56 — Playwright smoke cockpit + vòng dọn dẹp
2026-08-01 · ✅ DONE · **Plan:** `plans/260801-1948-v56-playwright-smoke-and-cleanup/` · **Suite:** 2392 BE + 280 FE + 8 e2e · **Release: 0.6.0 lên PyPI** (tag v0.6.0, OIDC pipeline + CI xanh)

## Làm gì

- **Playwright harness** (`web/e2e/`): toàn bộ `/api` mock TRONG browser qua 1 predicate
  route (endpoint quên mock → abort kêu to), fixtures TS typed thẳng với `src/types.ts`,
  SSE mock bằng `route.fulfill` + `retry: 100` (EventSource reconnect ~100ms replay
  stream — `pushRoomEvents()` nối event → lần reconnect kế giao "live"). CI job
  `frontend-e2e` secret-free, không cần backend Python.
- **8 smoke test đo DOM** cho layout v55: page-no-scroll, feed scroll trong khung,
  composer luôn thấy, overlay @mention không đẩy grid, gộp watch-run ×17, filter+search,
  chấm ● tab Kết quả khi handoff tới live (bug sửa 3 lần ở v55 — giờ có chốt chặn),
  mobile stack. `retries: 0`, 5+ lần chạy không flaky.
- **Quick wins**: dòng nhắc trong preview giao việc khi PIC bật `web_search` mà máy thiếu
  key (không auto-tắt flag — flag là ý định người dùng) · focus-trap dùng chung
  (`src/hooks/use-focus-trap.ts`) + lỗi `HTTP <status> — <detail>` cho artifact viewer
  (GET `request()` nay parse `detail` như write, hợp nhất `apiErrorFrom`) · GC artifact
  dir mồ côi trong retention sweep (guard kép: không task row + mtime >7 ngày).

## Quyết định & vì sao

| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Fixtures TS thay JSON | Node ESM đòi import attribute; TS được `tsc` check shape với types.ts — payload drift = lỗi compile | Fixture không dùng lại được ngoài TS |
| Mock API predicate, không glob | `**/api/**` nuốt cả module URL `/src/api/client.ts` của vite dev → app không boot | — |
| Bỏ badge web-search trang Đội | `IntegrationHealthPanel` (v18) đã liệt kê agent bật flag ngay trang đó — badge là trùng lặp | Cảnh báo không nằm trên từng card |
| GC orphan cần tuổi >7 ngày | Orphan mới = tín hiệu bug cho audit read-only, không phải rác | Rác nằm thêm 1 tuần |

## UAT đường thật (browser + data + connection thật, sau commit đợt 1)

- CEO yêu cầu UAT đầy đủ → restart 2 service launchd chạy code mới, agent-browser đo DOM
  trên data thật (39 room): page-no-scroll ✓, feed 2635px/237px khung ✓, composer y=180 ✓,
  gộp ×N ✓, artifact viewer trap wrap 2 chiều + Esc phím thật + focus trả về ✓, giao việc
  LLM thật `@nghien-cuu` → preview overlay đứng yên + **hint web_search hiện đúng** (máy
  thiếu key thật, nghien-cuu bật flag thật) → Huỷ, dọn row · sweep thật `{artifact_orphans: 0}` ✓.
- **Bắt bug thứ 4 của chấm ●** (suite + e2e đều xanh mà lọt): reload toàn cảnh → dot sáng
  từ history. Hai lỗi chồng: sentinel `{room: null}` trùng `activeRoom=null` nên toàn cảnh
  không bao giờ chụp baseline; và SÂU HƠN — SSE **replay history bất đồng bộ sau render**,
  baseline "chụp lúc render" luôn chụp lúc messages rỗng → handoff cũ nào cũng vượt baseline.
  jsdom set messages đồng bộ nên 3 lần sửa trước đều xanh giả. **Fix lần 4 (nghiệm thật):**
  "live" = **ts của sự kiện** > lúc mở phòng (cùng máy, skew ~0); toàn cảnh tắt hẳn dot
  (ArtifactPanel ở đó chỉ là hint chọn phòng). Unit test chuyển sang mô phỏng replay
  bất-đồng-bộ + e2e nhét handoff cũ vào history replay làm regression.

## Vấp & học được

- **Review bắt H1:** sweep orphan quét `.data/team-tasks/` — đường dẫn KHÔNG writer nào
  ghi (copy từ `_scan_orphans` v36, vốn cũng bug y hệt → audit artifact-orphan im lặng
  "clean" từ v36). Tests xanh vì monkeypatch theo đúng path bịa — *phantom coverage*.
  Fix: helper chung `team_task_artifacts_root()` dùng ở cả writer/sweep/audit; test theo
  layout writer thật. Bài học: đường dẫn hạ tầng phải lấy từ helper của writer, không gõ tay.
- Vitest nhặt nhầm `e2e/*.spec.ts` (default include) — **test count vẫn 279 passed nhưng
  "Test Files 2 failed"**, dễ đọc sót ở tail output → thêm `exclude: e2e/**` vào vite.config.
- Extra `deep` biến mất khỏi venv (một lần `uv sync` trần trước đó) → 68 test deep bị
  skip thành collection error khi có bytecode cũ. `uv sync --extra deep` khôi phục.

## Mở / sang sau

- Roadmap nợ mới (review M1): `/api/office/assign/staff` gọi `load_profile` đầy đủ
  per-staff per-request — đọc yaml-only hoặc cache khi chạm lại.
- Còn lại của hướng "Nền vững": opaque `attempt_id` cho review tray (làm khi đụng tray).
