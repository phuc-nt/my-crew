# v55 — Văn phòng cockpit shell: 1 viewport, composer-lên-đỉnh, dọn phòng việc

**Ngày:** 2026-07-22 · **Commits:** 2 (feat cockpit shell + layout B · fix live results dot) · **Suite:** 273 FE · **Plan:** `plans/260722-2059-v55-office-cockpit-viewport-shell/` · **Scope:** frontend-only, zero backend.

## Bối cảnh & quyết định

UAT screenshot: màn Văn phòng phải **scroll xuống ~5000px mới giao việc được** — grid không
giới hạn chiều cao, cột Phòng việc render 39 room không cap (17 watch-run trùng tiêu đề),
Kết quả chôn dưới đáy. CEO chốt (AskUserQuestion): **cockpit khung cố định** (cả màn = 1
viewport, cột scroll riêng) + lọc trạng thái + gộp watch-run + ô tìm kiếm + cột phải thành
tab [Phòng việc | Kết quả].

**Sửa giữa UAT:** CEO thấy composer-ghim-đáy chưa đủ, chốt **composer LÊN ĐỈNH** (layout B) —
"hài hoà và nổi bật". Grid rows đổi `header · composer · content`; composer thành command bar
(nhãn GIAO VIỆC MỚI, nút primary); dropdown @mention + preview kế hoạch chuyển absolute overlay
để mở KHÔNG đẩy 3 cột.

## Đã làm

- **P1 shell:** `.app-shell:has(.office-unified)` → `100dvh` flex column, `overflow:hidden`,
  max-width 1100→1600px. Scoped bằng `:has()` (view khác không đổi; browser cũ = fallback
  document-flow). Mỗi cột `overflow-y:auto; min-height:0`. Composer command bar + overlay.
- **P2 phòng việc** (helper thuần `workroom-grouping.ts`): `groupWorkrooms` gộp theo tiêu đề
  exact (status rollup ket>dang-chay>xong), `filterWorkroomGroups` — search bỏ qua status
  filter, active room LUÔN force-include. Chip đếm [●⚠✓] (✓ tắt mặc định), xổ nhóm ×N.
- **P3 tab phải:** `sideTab` state; tab Kết quả = ArtifactPanel trọn cột; chấm ● khi bàn
  giao live về lúc chưa mở tab. ReviewTray mở → chiếm cột.

## UAT — 2 vòng trên đường thật (agent-browser, fleet + LLM thật)

Đo DOM sau MỖI hành động (bài học repo: đừng tin CLI "Done"). Data thật: 39 room, 17
watch-run trùng, 28 xong + 11 kẹt.

- **Vòng 1 (layout, 14 mục):** page không scroll, composer luôn thấy, feed/rail scroll trong
  khung, 3D 340px co được, **17 watch-run → 1 dòng ×17** (list 39→23), lọc/search/deep-link
  đúng, tab Kết quả, dropdown overlay canvas đứng yên, mobile stack đúng.
- **Vòng 2 (chạy thật, 12 mục):** bật coordinator (`DRY_RUN=true`), giao 4 việc → LLM phân
  rã → preview overlay (canvas không nhúc nhích) → xác nhận → persist DB → feed SSE → **đội
  tự chèn soát chéo** (kiem-dinh) → done. Tổng LLM $0.0070.

## Vấp & học được

- **3 bug layout vòng 1** (browser bắt, suite không): (1) feed không scroll vì
  `.office-unified-log` nằm trong wrapper `<aside>` display-block → `flex:1` vô nghĩa →
  wrapper phải là flex column + `min-height:0`; (2) 3D co còn 150px vì wrapper lấy height từ
  r3f intrinsic size → đặt basis 34vh lên WRAPPER; (3) feed 2px ở vh=577 → canvas `flex:0 1`
  nhường chỗ + nén banner/header cockpit.
- **Chấm ● tab Kết quả — sửa SAI 2 lần, suite xanh cả hai, chỉ live UAT bắt.** (1) guard
  `prev.seq>0` nuốt handoff đầu của phòng mới (baseline 0 chính đáng); (2) cờ `settled` ghi
  trong effect — nhưng effect chỉ chạy khi seq handoff đổi, phòng mở ở 0 + event step_status
  không đổi seq → effect không chạy → cờ mãi false → vẫn nuốt. **Đúng (3):** chụp baseline
  LÚC RENDER, key theo room id — tồn tại trước khi handoff tới. Verify: việc thứ 4 `dot:true`
  đúng lúc bàn giao. Bài học lặp lại: *suite xanh ≠ chạy được*.
- `:has()` cần browser 2023+ — fallback document-flow, chấp nhận. Grouping tiêu đề exact: 2
  task trùng tên sẽ gộp — xổ ra vẫn chọn được từng room, chấp nhận.

## Còn treo

- Chưa test tự động cho layout B (jsdom không tính layout) — chỉ browser đo được, đã đo.
- ~~Server chạy từ checkout cũ `my-project-manager/`~~ **Giải 2026-08-01 (finalize 0.5.0):**
  gốc rễ là 2 plist launchd `com.mpm.*` + 3 dòng `*_MCP_DIST` trong `.env` đều trỏ đường
  dẫn tuyệt đối vào checkout cũ. Chạy lại `deploy/install.sh` (re-render plist từ template
  `__REPO_DIR__`), sửa `.env`, xoá thư mục cũ (chỉ log + DB rỗng). Doctor 13/15 ✓ (2 fail
  còn lại = key web-search + SMTP, tuỳ chọn người dùng). Release **0.5.0 lên PyPI** qua
  OIDC pipeline (CI + release đều xanh).
