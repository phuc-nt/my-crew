# E2E full-flow cho các journey v91
2026-08-21 · ✅ Done

## Làm gì

- Bịt lỗ e2e browser-level của milestone v91: trước đó chỉ board-card stalled flow có e2e,
  phần còn lại mới ở mức unit/component. Thêm 7 case, suite 37 → **44** (39 chromium + 5 mobile).
- **Unstick từ TRANG CHI TIẾT** (#22/#23 work-hub) — đường của finding HIGH cũ. Trang chi tiết
  render từ `queryKeys.artifacts.room(roomId)`, cache entry KHÁC board (`tasks.board()`), nên
  repaint phụ thuộc invalidate riêng — chính chỗ review từng thấy thiếu.
- **Form cấu hình agent** (#25/#26 team-hub) — model + lịch chạy + band + dry-run round-trip
  qua cache thật: PATCH xong query re-fetch, hàng repaint giá trị MỚI chứ không phải giá trị
  lúc mount.
- **Badge dry-run + sửa yêu cầu** (#27/#28 office-hub), **autopilot + concurrency** (#24/#25
  system-hub) — load-modify-save phải mang theo field khác nguyên vẹn.
- Fixture: bịt gap `/api/agents/{id}/band` → **0 dòng UNMOCKED** toàn suite, và thêm
  `expectNoUnmockedRoutes()` biến cảnh báo đó thành assertion.

## Quyết định & vì sao

| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| State flip trong mock khóa theo "đã POST write", không theo bộ đếm GET | Trang fetch cùng route nhiều lần mỗi lượt vào; đếm hit làm assertion phụ thuộc thứ tự | Mock giữ state, không còn thuần hàm |
| Đếm request artifacts thay vì sentinel `window.__noReload` | Sentinel sống sót qua remount client-side → chỉ chứng minh "không nạp lại trang", KHÔNG chứng minh re-fetch | Cần listener riêng mỗi test |
| `page.on('request')` thay `page.route()` khi chỉ muốn quan sát | Playwright route sau đè route trước → spec-level route che handler của mock, chặn nó sang pha post-action | Không chặn/đổi được response |
| `.click()` thay `.check()` cho checkbox dry-run | Input controlled theo server state, chỉ lật sau khi PATCH resolve + query re-fetch; `.check()` assert lật đồng bộ nên fail vì latency | Không assert được trạng thái tức thì |
| `page.reload()` thay `goBack()` khi dò seed one-shot | Chromium tự khôi phục input đã gõ khi đi lại trong history → goBack đo hành vi browser, không phải contract app | Không dò được đúng nhánh in-app |
| Mock trả đủ 5 key profile-settings kể cả absent-shape | `read_profile_settings_raw` luôn trả `null`/`[]`/`{}`, type FE khai required — spread thiếu key đưa `undefined` sai contract | Fixture dài hơn |

## Vấp & học được

- **Agent revert xóa mất work chưa commit.** Tester được giao "phá file tạm rồi revert ngay
  (`git checkout`)"; lệnh đó restore file về HEAD, cuốn luôn 463 dòng test chưa commit. Reflog
  trống, stash trống, không backup → rebuild lại từ đầu. Học: **commit trước khi spawn agent
  chạm git**, và cấm agent dùng lệnh git mutate tree (revert bằng cách Edit ngược lại text gốc).
- **Test xanh không đủ, phải mutation-test.** Sau khi đổi #22 sang đếm request, tự gỡ dòng
  invalidate `artifacts.room` để xác nhận case ĐỎ thật — nếu không kiểm, chỉ đổi một sentinel
  yếu này lấy một sentinel yếu khác.
- **Cảnh báo chỉ log ra console = không tồn tại.** Gap `/api/agents/{id}/band` sống sót nhiều
  vòng vì `[mock-api] UNMOCKED` chỉ in console: route abort, app render như chưa từng gọi, test
  vẫn xanh. Nay assert được.
- **Không tin số liệu agent báo.** docs-manager ghi "3691 BE"; chạy `uv run pytest` thật ra
  **3690 passed, 1 skipped**, và split chromium/mobile là 39/5 chứ không phải 38/6. Sửa lại.

## Mở / sang sau

- **Live-UAT (P6) của plan v91 vẫn cần người:** bind `ops_operator_id` qua Telegram DM rồi tick.
- `expectNoUnmockedRoutes` là snapshot chứ không phải wait (poll trên list rỗng resolve ngay
  tick đầu) — assert nội dung trang trước, helper này mới phủ hết cái đã tới.
