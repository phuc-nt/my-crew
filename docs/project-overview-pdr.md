# Project Overview & PDR — my-crew

> Product definition + requirements. Đọc file này TRƯỚC khi plan hay code.
> Cập nhật: 2026-07-13 (v34). Trạng thái: **production-usable, single-user, autonomy-first, live E2E verified**.
> Liên quan: [system-architecture](system-architecture.md) · [action-gateway-explainer](action-gateway-explainer.md) · [uat-theo-user-story](uat-theo-user-story.md).

## 1. Vấn đề

Một founder/CEO công ty một-người phải tự làm toàn bộ việc "quản lý": theo dõi Jira,
đọc GitHub, cập nhật OKR ở Confluence, viết báo cáo, nhắc nhở, tổng hợp. Việc lặp lại,
tốn thời gian, và không scale khi chỉ có một người.

## 2. Sản phẩm

Một **đội nhân sự ảo AI** do một người điều hành. CEO giao việc bằng ngôn ngữ tự nhiên
(web hoặc Telegram); các agent — mỗi con một vai trò (điều phối / nghiên cứu / nội dung /
phân tích / kiểm định) — tự phân rã việc, làm, soát chéo nhau, và *tự hành động* trên hệ
thống thật (Jira/GitHub/Confluence/Slack). Không phải chatbot hỏi-đáp; là đội tự làm việc
theo lịch và theo lệnh.

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
| Giao việc | @PIC / @all / tự-xác-nhận; phân rã ≤7 bước; hash-bind chống tamper |
| Theo dõi | Màn Văn phòng realtime (3D + feed + kết quả) theo từng phòng việc |
| Tự vận hành | Soát chéo tự chèn ≤2 vòng; hỏi ý kiến đồng nghiệp; tự cứu lỗi 1 lần; song song cap 2 |
| An toàn (v30) | Action Gateway (Lớp A chặn cứng luôn / Lớp B: autonomous chạy ngay vs guarded duyệt per-agent); PII firewall; chat flatten (autonomous mode). |
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

Đã ship tới **v34** (checkpointer + interrupt + follow-up sweep + fan-out parallelization, 2105 BE + 200 FE tests, live E2E verified).
Lộ trình + việc tiếp: [project-roadmap.md](project-roadmap.md).

## Câu hỏi mở

- Định nghĩa "đội office" đã chốt = mọi agent enabled (không lọc domain) — cân nhắc lại
  nếu sau này có agent không nên nhận việc đội.
- Multi-user/hosted chưa trong phạm vi — cần thiết kế lại auth + isolation nếu mở rộng.
