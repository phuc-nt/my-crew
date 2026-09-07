# UI/UX catch-up — dashboard hero, chuông Cần chú ý, phím tắt (mượn mẫu openhuman)
2026-09-07 · ✅ Done

## Làm gì
- Backend phơi số liệu đã đo mà SPA chưa dùng: `GET /api/insights/route-stats`,
  `/tool-stats?days=`, `/engine-costs?days=` (read-only, sau auth, store trống → 200 số 0);
  `/team-tasks/{id}/route` thêm `shape`/`effort`/`failure_mode`/`dead_end`. 9 test mới.
- Tab Số liệu dựng lại theo mẫu cost dashboard: hero StatTile ×3 + Badge + ProgressBar,
  "Cập nhật Ns trước" + Làm mới, `?days=` trong URL. Hai primitive mới `ProgressBar`, `StatTile`.
- Chuông Cần chú ý trên header: gom 7 nguồn (coordinator, việc kẹt, ngân sách, team alerts,
  duyệt, hỏi, bản mẫu mới) xếp error>warning>info, deep link, bỏ qua theo fingerprint.
- Bảng phím tắt `?`, chord `g`+`c/o/w/t/s`, nút ⌨; chi tiết việc + desk inspector đọc tuyến
  điều phối bằng nhãn người.
- Cổng: BE 4830 pass / 1 skip · ruff · FE vitest 438 · Playwright 47 · tsc · oxlint · bundle dựng lại.

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Badge chuông chỉ đếm error+warning, `/work` giữ badge duyệt riêng | Hai câu hỏi khác nhau: "cái gì cần tôi" vs "bao nhiêu việc chờ duyệt"; info không được nag | Hai con số trên header, phải giải thích trong hướng dẫn |
| Bỏ qua theo fingerprint (nội dung), không theo id | Cùng cảnh báo đổi nội dung (ngân sách qua nấc mới) phải quay lại; id không phân biệt được | Mục "chờ duyệt" dùng `created_at` làm fingerprint nên không bao giờ tự quay lại — đúng ý |
| Chuông đặt ngoài `.app-header-actions` | Mobile gập chip vào overflow, chuông phải còn thấy | Thêm rule CSS riêng cho ≤640 px |
| `days` clamp 90, `0` = tất cả, store trống trả 200 | Fresh install không được thấy 5xx hay spinner mãi | Số liệu >90 ngày chỉ xem được bằng `0` |
| Tham khảo openhuman ở mức mẫu, không chép | GPL-3.0 vs repo này | Tự viết CSS/logic, không dùng được component sẵn |

## Vấp & học được
- jsdom của vitest ở đây không có `localStorage` → test dismiss đỏ `reading 'clear'`;
  stub Map-backed như `theme-context.test.tsx` thay vì đổi code sản phẩm.
- Dispatch sự kiện mở bảng phím tắt ngoài `act()` không flush state → bọc `act()`.
- Script dựng bundle đặt ngoài `web/` không resolve được vite (`ERR_MODULE_NOT_FOUND`):
  Node tìm module theo vị trí file, không theo cwd → import bằng đường dẫn tuyệt đối từ cwd.
- zsh: glob `--include=*.test.tsx` không khớp là hủy cả lệnh; dùng `grep -rl | grep test`.

## Mở / sang sau
- StatusLine `aria-live` cho trạng thái stream (mẫu openhuman) chưa làm.
- Chuông chưa có "xem lại mục đã bỏ qua"; mới chỉ hiện đếm `{n} mục đã bỏ qua`.
