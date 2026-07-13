# v37 — UI design-system sync (office layout + app-wide tokens)
2026-07-13 · ✅ Done (200 FE)

CEO thấy màn Văn phòng "font lệch + không thẳng hàng". Audit đo computed-style trực tiếp trên web sống → sửa CSS thuần (+ 2 đổi tag), không đụng logic.

## Làm gì
- **Audit** (ui-ux-designer, browser + CSS 13 route): "font lệch" KHÔNG phải tiêu-đề-cột (đã đồng nhất) mà là (a) cột Kết quả lệch xuống 9px vì có box-padding còn 2 cột kia không, (b) input desktop + button không-class toàn app dùng 13.3px UA-default vì rule input chỉ nằm trong `@media max-width:640px`, (c) cột Kết quả không phân cấp size.
- **P1 Office**: `.office-artifacts` bỏ box ngoài → box chuyển vào `.office-artifacts-body`, zone-title flush mép trên như 2 cột kia (3 title cùng top 588, trước 588/588/597). Task `<h4>` → `--fs-h4` (15.2px, trên item 14.4px). `<h2>Văn phòng 3D</h2>` → `<h3>` (bỏ 2 h2 chồng ở fallback 2D).
- **P2 App-wide**: `input,textarea,select{--fs-body}` thành BASE rule (16px mọi trang, kiêm anti-zoom iOS); `button{font-size:--fs-sm}` (14.4px, khớp .chip/.btn). Dọn `--fs-md` undefined → `--fs-h3`; `0.85em`×2 → `--fs-xs`; `0.62rem` → `--fs-2xs`.

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Giữ 3 cột, chỉ chuẩn hoá (CEO chốt) | Layout quen thuộc; vấn đề là canh lề + token, không phải cấu trúc | Cột giữa vẫn rộng ~464px (feed cần chỗ cho text — hợp lý) |
| Box chuyển vào `.office-artifacts-body` | Cho zone-title flush mép trên như 2 cột kia → 3 title cùng baseline | Thêm 1 div wrapper |
| Input/button sửa BASE rule toàn app | Đúng GỐC (13.3px UA-default là app-wide, không riêng Office) | Blast rộng → phải UAT nhiều trang |
| Không thêm token mới cho micro-label | `--fs-2xs` đủ; bớt 1 token (YAGNI) | PIC tag to hơn chút (0.62→0.75rem) |

## Vấp & học được
- "font lệch" CEO thấy dễ tưởng là tiêu-đề-cột, nhưng đo computed-style cho thấy gốc là input/button UA-default + 1 cột lệch box — audit ĐO thật (không chỉ grep CSS) mới thấy đúng.
- `1.4fr` cho cột giữa vô tác dụng: trong app-shell 1100px, cột giữa là track flexible DUY NHẤT nên luôn lấy phần còn lại bất kể tỉ lệ fr → revert về `1fr`, để min-width side lo cân.
- Cascade: base `button{--fs-sm}` không phá `.theme-toggle-btn{--fs-xs}` (class đặc-hiệu hơn thắng) — verify bằng đo browser, không đoán.

## Mở / sang sau
- Đã cook hết plan; không còn mục treo.
- Nếu sau muốn siết `button` global delegate hẳn về `.btn` sizing (đóng vĩnh viễn gap raw-vs-classed) thì làm đợt riêng.
