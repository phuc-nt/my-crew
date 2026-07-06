# v9 P4 — responsive đầy đủ (bảng → card trên phone)

**Ngày:** 2026-07-07 · **Scope:** frontend CSS + markup nhẹ (backend py 0 đổi) · **ĐÓNG v9**

## Mục tiêu

Đạt cam kết "đọc + duyệt được trên phone" (plan v7 M20). Trước: 0 media query → bảng 7 cột tràn ngang, nút <44px, input gây iOS zoom, nav không wrap.

## Đã làm

- **Card-list mobile cho 3 bảng CEO** (Đội/Việc-tasks/Approvals): `@media (max-width: 640px)` → `.agents-table`/`.tasks-table`/`.proposals-table` chuyển `display:block`, `tr`=card, `td`=flex-row với `td::before { content: attr(data-label) }`. `data-label` đã thêm ở P1 (Team/Approvals) + P4 (Tasks). Ô hành động (không label) → suppress `::before`. **CSS-only, không rewrite data.**
- **Touch 44px**: `button, .btn, .btn-link { min-height: 44px }` ở mobile.
- **Chống iOS zoom**: `input, textarea, select { font-size: 1rem }` (≥16px → Safari không auto-zoom).
- **Wrap**: nav/quick-chips/team-actions/approval-list ở mobile.
- **Bảng Nâng cao** (AuditTable/RunList/PendingProposals/Overview): `<div className="table-scroll">` overflow-x wrapper (persona kỹ thuật, không card).
- **`.app-shell` padding nhỏ hơn** ở mobile.

## Sự kiện chính — code-review bắt coupling

Review bắt **finding thật**: `Overview.tsx` dùng chung class `.agents-table` → card-list media query nuốt luôn Overview, NHƯNG Overview `<td>` không có `data-label` → mobile hiện giá trị xếp chồng KHÔNG nhãn cột (thead ẩn). Vi phạm ý định "chỉ 3 bảng CEO card-list". **Vá**: tách Overview sang class riêng `.agents-table-advanced` + bọc `.table-scroll` (persona kỹ thuật chỉ cần scroll ngang, không card).

## Kết quả

- **86 vitest xanh** (markup thêm data-label/wrapper-div không phá query text/role) + tsc + build sạch. Backend py 0 đổi.
- **Preview visual** (desktop 640px vs phone 360px, dùng đúng token + rule card-list từ App.css) xác nhận card-list render đúng — jsdom không test được breakpoint nên verify bằng preview HTML.

## Bài học

- **Class dùng chung = coupling ẩn**: media query target class → mọi view reuse class thừa hưởng, kể cả view không muốn. Tách class cho behavior khác nhau (Overview advanced ≠ Team CEO) thay vì target chung.
- **Card-list CSS-only qua `data-label` + `attr()`** đủ đẹp cho bảng CEO, không cần render component riêng — ít đổi markup, giữ test.
- **jsdom không test breakpoint** → preview HTML dùng đúng token production là cách verify visual rẻ nhất khi không có browser.

## v9 tổng kết (P1→P4)

CEO low-tech: duyệt việc hiểu được (P1 trust-surface tiếng Việt) → tạo agent qua chat không dead-end (P2) → giao diện đồng bộ WCAG-pass (P3 design-token) → dùng trên phone (P4 card-list). **Backend py 0 đổi toàn v9** (frontend-only, 0 dependency mới). 4 phase mỗi phase gate đủ (test+review+build+journal+commit); P1 adversarial trust-surface.
