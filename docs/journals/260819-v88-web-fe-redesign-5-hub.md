# v88 — Redesign toàn bộ web FE: 5 hub, chat làm nhà
2026-08-19 · ✅ Done · chưa release

## Làm gì

- **Quy hoạch lại IA thành 5 hub**: `/chat` (HOME), `/office` (3D), `/work`, `/team`, `/system`. Trước đó là ~20 route top-level phẳng; giờ mỗi màn cũ thành một tab có URL riêng bên trong hub đã hấp thụ nó.
- **Chat là màn nhà**, dựng theo lối app chat (danh sách hội thoại + composer) nhưng khai thác BE: giao việc, duyệt approval, xem artifact ngay trong luồng — thứ Telegram không làm được.
- **Đổi tầng dữ liệu sang TanStack Query** (`web/src/api/queries/`), `query-keys.ts` là factory key duy nhất để cầu SSE→invalidate gọi đúng slice. Bỏ hẳn 2 global context cũ (`AgentProvider`, `PendingApprovalsProvider`) — agent nằm ở route, approvals là 1 query cache.
- **Tổ chức lại code theo `web/src/features/<hub>/`** thay cho `web/src/views/` phẳng.
- **21 redirect** giữ mọi URL trước redesign còn resolve; `/agents/:id` giữ id trong path.
- Entry bundle **540.05 → 475.37 kB**; dọn 300 entry dictionary + 66 rule CSS + 10 file chết.

## Quyết định & vì sao

| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| Đập đi thiết kế lại từ BE hiện có, không bám FE cũ | FE cũ là 20 route phẳng ánh xạ 1-1 với endpoint — cấu trúc của BE, không phải của người dùng | Phải viết lại gần hết view; đổi lại IA không còn rò rỉ hình dạng API ra mặt user |
| Tab state ở URL (`?tab=`) chứ không ở component state | Deep link + bookmark phải mount đúng tab khi cold load | Mỗi tab phải parse param; bù lại test được bằng browser thật |
| Giữ mọi URL cũ dưới dạng redirect thay vì để 404 | Link đã in trong report cũ và bookmark của user không được chết | 21 dòng route thừa; rẻ hơn nhiều so với mất link |
| Giữ `lib/api-cache.ts` dù plan liệt vào danh sách xóa | Grep còn 4 caller sống ngoài query layer — xóa = tái phát burst fetch trùng mà nó sinh ra để chặn | Tồn tại 2 lớp cache song song cho tới khi caller cuối chuyển sang query |
| Scanner key i18n chỉ **báo cáo**, không tự xóa | Key xóa nhầm không fail build — nó render chuỗi key thô ra mặt user | Phải soi tay từng candidate |

## Vấp & học được

- **Suite xanh hoàn toàn vẫn ship được lỗi nhìn thấy bằng mắt.** 344 vitest + 28 e2e + tsc + build đều sạch, nhưng browser thật lộ 2 lỗi: `systemInsights.total` mất param `{spent}/{cap}/{pct}` (tổng fleet render ra mỗi chữ "Tổng") và `.company-identity` không có rule CSS (form dồn 1 hàng, label dính input). Học: chuỗi có tham số và sự tồn tại của rule CSS là hai thứ không assertion nào trong repo này đang canh — chỉ screenshot thấy.
- **`git checkout` để revert một lần sweep hỏng đã nuốt luôn 25 key mới của cùng file.** Phát hiện vì tsc fail sau revert; nếu không, UI ship ra chuỗi key thô. Học: revert theo file là revert **cả** phần chưa commit của file đó — sweep và feature không được ở chung file chưa commit.
- **Sweep dictionary thất bại 2 lần vì heuristic đọc sai biên entry**: xóa theo dòng làm vỡ 8 entry đa dòng; "span kết ở dòng đầu tiên có dấu phẩy" tràn sang entry sau. Lần 3 dùng "span dừng ở dòng entry kế / comment / đóng block" mới sạch.
- **Grep chuỗi không thấy được tên dựng bằng nối chuỗi.** Sweep CSS nuốt 5 họ class dạng `${base}-${value}` (`.workroom-*`, `.office-3d-state-*`, `.verdict-*`…) vì tên literal không tồn tại trong source. Khôi phục 13 dòng và ghi comment tại chỗ; scanner i18n cũng phải whitelist theo prefix cùng lý do.
- **Optional chaining nửa vời là bug chờ payload.** `data?.skipped.length` chain `data` nhưng không chain `skipped` — e2e bắt được crash trắng màn ở `CompanyActivity`. Ô hiển thị lỗi mà lại là thứ làm hỏng màn hình thì phòng thủ phải mạnh hơn phần còn lại.

## Mở / sang sau

- "Đổi mật khẩu khi auth bật" chưa build được: `api/client.ts` không có endpoint — cần BE trước.
- `node_modules/` ở root chưa gitignore (chỉ `web/node_modules/` có).
- Insights hiện chỉ có con số tổng chi tiêu fleet; chưa quyết có cần chart theo thời gian không.
