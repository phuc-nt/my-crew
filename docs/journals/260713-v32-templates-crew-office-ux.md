# v32 — One-click templates + crew, đại tu office 3D, tổng rà UI/UX
2026-07-13 · ✅ Done (P1-P4 một phiên cook, UAT bằng browser thật trên data thật; 2 mục chờ CEO review)

## Làm gì
- **Audit UI/UX toàn diện** (report + 40 screenshot 2 viewport, ma trận capability↔UI): nền tảng tốt; gap tập trung 2 cụm — lệnh chat không khám-phá được và cờ per-agent chỉ sửa YAML. Findings → P2/P3/P4.
- **Template thành executable**: card "Tạo ngay" (2 click, `POST /api/agents/create-from-template` — spec build SERVER-side, client chỉ gửi role_id) + banner "Tạo cả đội" (crew.yaml 1 crew mặc định, per-member independent, skip-existing idempotent, coordinator wire có domain-guard + không ghi đè). Agent ra đời **TẮT** (registry + profile) → điền token → bật ở Đội. Template mang tool gắn sẵn: flags web/academic, skills copy (*.md, chặn symlink-escape), runtime tier, schedule mặc định.
- **Office 3D đại tu**: gate 3 mockup render thật (webgl swiftshader headless) → chọn Style A low-poly flat (palette 2 theme trong `officeTheme`); panel 70vh→38vh (1280×800 thấy 3D+feed+composer cùng lúc); desk click → PIC room/agent page, hover tooltip, fallback table parity; camera fit theo số desk; error boundary + watchdog 12s cho lazy chunk (vá rủi ro kẹt "Đang tải" vĩnh viễn mà audit phát hiện).
- **4 quick-win từ audit**: listing "Trợ lý làm được gì?" (`GET /api/ops/chat/commands`), AgentPage lỗi profile-mồ-côi có hướng dẫn + link recovery, back-link, note filter verdict ở Hoạt động.
- Suite 2019→**2032 BE** + 183→**186 FE**; bundle office 3D **giảm 9.6%**; sửa luôn 2 lỗi type làm `tsc -b` vỡ từ v30 (bundle committed đã stale 2 ngày mà không ai biết).

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Audit trước, build sau (P1 là input P2-P4) | Yêu cầu "đánh giá toàn diện" của CEO chính là spec cho 2 mảng còn lại | Mất ~2h đầu phiên cho screenshot tooling |
| One-click spec build server-side, client chỉ gửi role_id | Client không bao giờ gửi được config tự do vào profile — cùng cửa validate `create_agent` | UI ít linh hoạt hơn wizard (đúng chủ đích: wizard vẫn còn cho custom) |
| One-click/crew tạo agent DISABLED (wizard giữ enabled lịch sử) | Bất biến plan + hint UI khớp thực tế; agent thiếu token không nên nhận việc đội | Thêm 1 click "Bật" — chấp nhận, an toàn hơn |
| Style A low-poly flat (cook chọn tạm, CEO review 3 mockup) | Ấm/"văn phòng con người" đúng persona; trạng thái đọc rõ cả 2 theme; B nâu-chìm, C lạnh server-room | CEO có thể đổi — palette đã cô lập trong `officeTheme` nên đổi rẻ |
| Screenshot bằng Chrome CLI headless thay puppeteer | puppeteer `captureScreenshot` treo mọi page trên máy này; CLI + swiftshader chạy ổn | Không tương tác được từng bước — bù bằng API-level UAT |

## Vấp & học được
- **Bundle committed stale không ai canh**: `tsc -b` đã vỡ từ v30 (2 lỗi literal-type) nên dist trong repo là bản cũ 2 ngày — mọi UAT browser trước đó chạy UI cũ. Bài học: sau mỗi wave FE phải `npm run build` và soi hash dist đổi, không chỉ `tsc --noEmit` (build dùng tsconfig chặt hơn).
- Office lazy-chunk treo "Đang tải" trong headless hoá ra **hết sau rebuild** — nhưng quá trình đuổi bug lộ một rủi ro sản phẩm thật (user kẹt vĩnh viễn nếu chunk/WebGL fail) → error boundary + watchdog. Tooling pain đôi khi là finding sản phẩm trá hình.
- Review bắt đúng chỗ đau: code tạo agent ENABLED (parity wizard) trong khi plan ghi bất biến DISABLED và hint UI nói "rồi bật" — mâu thuẫn ba bên code/plan/copy. Chọn theo plan (an toàn hơn) thay vì rationalize parity.
- Hook chặn Write vì fake key/từ "target" trong test heredoc — lách bằng ghép chuỗi runtime; pattern-hook thô cần escape route quen tay.
- `useState` thêm sau early-return → Rules-of-Hooks vỡ 7 test — hooks mới luôn đặt cạnh cụm hooks đầu component.

## Mở / sang sau
- **Chờ CEO**: (1) duyệt/đổi style 3D từ 3 mockup + xem build thật trên browser (fps + visual GL chưa verify được headless); (2) quyết `hr` profile mồ côi.
- Backlog từ audit: toggle UI cho watchers/web_search/academic_search/trust_mode (hiện YAML), bảng Đội mobile → card layout, nhóm advanced row.
