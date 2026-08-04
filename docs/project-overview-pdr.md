# Project Overview & PDR — my-crew

> Product definition + requirements. Đọc file này TRƯỚC khi plan hay code.
> Cập nhật: 2026-08-04 (v66). Trạng thái: **production-usable, single-user, autonomy-first, live E2E verified — PyPI 0.7.0**.
> Liên quan: [system-architecture](system-architecture.md) · [action-gateway-explainer](action-gateway-explainer.md) · [uat-theo-user-story](uat-theo-user-story.md).

## 1. Vấn đề

Một founder/CEO công ty một-người phải tự làm toàn bộ việc "quản lý": theo dõi Jira,
đọc GitHub, cập nhật OKR ở Confluence, viết báo cáo, nhắc nhở, tổng hợp. Việc lặp lại,
tốn thời gian, và không scale khi chỉ có một người.

## 2. Sản phẩm

Một **đội nhân sự ảo AI** do một người điều hành. CEO giao việc bằng ngôn ngữ tự nhiên
(web hoặc Telegram); các agent — mỗi con một vai trò (điều phối / nghiên cứu / nội dung /
phân tích / kiểm định / **thư ký riêng**) — tự phân rã việc, làm, soát chéo nhau, và *tự
hành động* trên hệ thống thật (Jira/GitHub/Confluence/Slack/Gmail/Calendar). Không phải
chatbot hỏi-đáp; là đội tự làm việc theo lịch và theo lệnh.

Từ v57–v66 (arc thư ký), cửa vận hành chính là **chat Telegram với thư ký**: việc cá nhân
(briefing, email, lịch, nhắc đúng giờ) lẫn việc công ty (giao việc đội, chỉnh giữa chừng,
xem kanban + chi phí) đi qua một cửa; **autopilot** cho phép AI là người quyết cuối
(tự xác nhận kế hoạch, tự gỡ kẹt, tự duyệt Lớp B) — Lớp A + trần chi phí vẫn chỉ người
thật đổi được.

## 3. Nguyên tắc bất khả xâm phạm (v30: autonomy-first)

> **Tự chủ về TỐC ĐỘ (mặc định); duyệt là tùy chọn. Luôn duyệt về an toàn.**

- Agent chạy nhanh, song song, tự phối hợp — **không cần CEO gật đầu từng bước nội bộ**.
- Hành động ghi **RA NGOÀI công ty** (đăng Slack, gửi email, gộp PR) **chạy ngay mặc định** (autonomous mode, tự chủ) → audit ghi rationale "trust_mode=autonomous"; **hoặc chờ CEO duyệt** (guarded mode, opt-in per-agent via `safety.trust_mode: guarded`).
- MỌI hành động đi qua một cửa duy nhất (**Action Gateway**): việc nguy hiểm (mất dữ liệu / lộ bí mật) bị **chặn cứng LUÔN** (Lớp A, không toggle) — LLM không vượt được kể cả khi "muốn".

Xem [action-gateway-explainer.md](action-gateway-explainer.md) cho mô hình đầy đủ (bảng trust modes + 5 bắt-buộc-nói-thẳng).

## 4. Người dùng & phạm vi

- **Người dùng**: CEO/founder không-kỹ-thuật, một người, vận hành qua web (localhost) +
  Telegram. **KHÔNG** phải multi-tenant, không SaaS công khai — single-user, self-hosted
  trên máy cá nhân/server riêng.
- **Trong phạm vi**: giao việc đội, theo dõi realtime, duyệt hành động, báo cáo định kỳ,
  cảnh báo. Xem 22 user story ở [uat-theo-user-story.md](uat-theo-user-story.md).
- **Ngoài phạm vi (cố ý)**: đăng nhập nhiều người, phân quyền RBAC, thanh toán, chạy cloud
  đa-tenant. Bind LAN chỉ cho phép khi bật web-auth (an toàn mặc định localhost).

## 5. Yêu cầu chức năng (tóm tắt — chi tiết ở user stories)

| Nhóm | Yêu cầu |
|------|---------|
| Đội ngũ | Tạo/tắt/xoá agent; đội = mọi agent enabled; registry là user-data (không mất) |
| Giao việc | @PIC / @all / tự-xác-nhận; phân rã ≤7 bước; hash-bind chống tamper; giao/chỉnh/huỷ qua chat thư ký (catalog scope theo domain) |
| Theo dõi | Màn Văn phòng realtime (3D + feed + kết quả) theo từng phòng việc; kanban + chi phí qua chat |
| Tự vận hành | Soát chéo THEO RỦI RO (chỉ bước cuối + ghi-ra-ngoài, task nhỏ waiver); tự cứu lỗi 1 lần; autopilot: tự xác nhận / tự gỡ kẹt thang 2 nấc / tự duyệt Lớp B, opt-out per-task; scheduler round-robin công bằng |
| Trợ lý cá nhân | Chat DM tức thì; briefing sáng/tuần; đọc Gmail/Calendar; gửi email; tạo/sửa/xoá lịch; nhắc đúng-giờ về Telegram; đa-lệnh một tin |
| Trí nhớ | Store SQLite bền dùng chung; đội đọc chéo; thư ký chỉ-đọc (`memory_share: read_only`); retention 90 ngày |
| An toàn (v30) | Action Gateway (Lớp A chặn cứng luôn / Lớp B: autonomous chạy ngay vs guarded duyệt per-agent); PII firewall; chat flatten (autonomous mode); shell chỉ trong Docker sandbox (không mount host, network off, fail-closed) |
| Báo cáo | daily/weekly/okr/resource + headcount (hr); xuất .xlsx qua email; đa-audience |
| Cảnh báo | agent chết ngầm, bộ điều phối chưa chạy, thiếu web-search key → Telegram/banner |

## 6. Yêu cầu phi chức năng

- **An toàn > tiện lợi**: không có đường tắt nào bỏ qua gateway; secrets chỉ trong `.env`
  (không qua terminal/URL/log); audit log không sửa được.
- **Bền vững khi lỗi**: mọi ghi realtime (office events, heartbeat) fail-degrade, không
  chặn pipeline. Retry = attempt mới (không resume mid-graph).
- **Chi phí có trần**: mỗi việc đội có cap ($2 mặc định); ngân sách LLM per-agent hàng tháng.
- **Kiểm chứng thật**: mọi tính năng lớn E2E trên browser + LLM + ticker thật, không chỉ
  suite xanh (bài học "suite xanh ≠ chạy được").

## 7. Bối cảnh kỹ thuật (1 dòng mỗi cái)

- Backend Python 3.12 (uv) · LangGraph agent graphs · FastAPI + SSE · SQLite WAL.
- Frontend React 19 + Vite + react-three-fiber (màn 3D).
- Tích hợp: MCP (Jira/Confluence/Slack) · `gh` CLI · `gws` CLI · OpenRouter (LLM).
- Kiến trúc chi tiết: [system-architecture.md](system-architecture.md).

## 8. Trạng thái & lộ trình

Đã ship tới **v66** (…**v51 productize** (PyPI) · v52–v55 office cockpit · **v56
Playwright e2e** · **v57–v60 thư ký cá nhân** (pack `personal`, briefing, Gmail/Calendar,
email, sửa lịch) · **v61 chat = cổng điều phối đội** · **v62 English identifiers** ·
**v63 autopilot + review theo rủi ro + gỡ kẹt 1 chạm** · **v64 UAT hardening (chống bịa
sau bước bị bỏ)** · **v65 nhắc đúng-giờ + scheduler công bằng** · **v66 cross-agent
memory SQLite**), **2530 BE + 279 FE + 8 e2e tests**, live E2E verified, PyPI 0.7.0.
Kiến trúc runtime-tier + moat: xem [system-architecture](system-architecture.md) §3.9.
Lộ trình + việc tiếp: [project-roadmap.md](project-roadmap.md).

## Câu hỏi mở

- Định nghĩa "đội office" đã chốt = mọi agent enabled (không lọc domain) — cân nhắc lại
  nếu sau này có agent không nên nhận việc đội.
- Multi-user/hosted chưa trong phạm vi — cần thiết kế lại auth + isolation nếu mở rộng.
