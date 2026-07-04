---
title: "UAT Checklist — Nghiệm thu đội nhân sự ảo (dành cho CEO)"
description: "Danh sách kiểm thử từng bước để CEO tự xác nhận hệ thống chạy đúng, không cần dev."
status: stable
created: 2026-07-04
---

# UAT Checklist — Nghiệm thu đội nhân sự ảo

> Dành cho **CEO / người vận hành**, không cần biết code. Làm theo thứ tự, mỗi mục có **việc làm** và **kết quả mong đợi**. Đánh dấu ✅ khi đúng như mô tả. Nếu sai, ghi lại mục nào rồi báo người kỹ thuật.

Trước khi bắt đầu: đã chạy `./deploy/install.sh` (xem [deployment-production.md](deployment-production.md)) và điền đủ `.env`.

**Bản đồ menu (v7):** dashboard gom về **4 mục** — **Trợ lý** (chat điều hành, trang mặc định) · **Đội** (danh sách agent → trang agent, nút Tạo, Kho tài liệu) · **Việc** (gộp: cần duyệt + việc đã giao, có badge đỏ số chờ) · **Cài đặt** (kết nối + **Nâng cao**: Tổng quan/Timeline/Chi phí/Bộ nhớ/Guardrail/Cấu hình/Chạy thủ công). Không chức năng nào mất; các trang kỹ thuật nằm trong Cài đặt → Nâng cao.

---

## 1. Đăng nhập

| Việc làm | Kết quả mong đợi |
|---|---|
| Mở trình duyệt vào địa chỉ dashboard (mặc định http://127.0.0.1:8765) | Hiện màn hình **Đăng nhập** (không vào thẳng dashboard) |
| Nhập sai mật khẩu, bấm Đăng nhập | Báo lỗi "Sai tên đăng nhập hoặc mật khẩu" |
| Nhập đúng tên + mật khẩu | Vào được dashboard, thấy 4 mục menu: **Trợ lý / Đội / Việc / Cài đặt** (mặc định mở Trợ lý) |
| Thử mở lại một trang bất kỳ ở tab ẩn danh (chưa đăng nhập) | Bị chặn về màn hình đăng nhập |

☐ Mục 1 đạt

## 2. Tạo nhân sự ảo bằng hội thoại (không cần form)

| Việc làm | Kết quả mong đợi |
|---|---|
| Vào menu **Trợ lý**, gõ tiếng Việt: "tạo agent mã sales-pm, vai trò quản lý dự án" | Trợ lý hỏi lại loại báo cáo |
| Trả lời: "daily" | Trợ lý hiện **bản xem trước** cấu hình + hỏi "Xác nhận?" |
| Gõ "xác nhận" | Báo "Đã tạo agent 'sales-pm'…" |
| Vào menu **Đội** | Thấy agent sales-pm trong danh sách (bấm vào tên = mở trang agent) |

☐ Mục 2 đạt

## 3. Hỏi đáp bằng dữ liệu thật

| Việc làm | Kết quả mong đợi |
|---|---|
| Trong **Trợ lý**, gõ: "đội mình đang có mấy agent, tốn bao nhiêu tiền?" | Trả lời số agent + chi phí LLM tháng này (số thật, không bịa) |

☐ Mục 3 đạt

## 4. Nhận báo cáo tự động (Telegram)

*(Chỉ khi đã cấu hình bot Telegram cho agent — xem getting-started.)*

| Việc làm | Kết quả mong đợi |
|---|---|
| Nhắn cho bot Telegram của agent PM: "tiến độ dự án sao rồi?" | Trong ~1 phút, bot trả lời bằng dữ liệu Jira thật (bảng issue/rủi ro) |

☐ Mục 4 đạt (hoặc bỏ qua nếu chưa dùng Telegram)

## 5. Giao lệnh có kiểm soát (Lớp B — cần duyệt)

| Việc làm | Kết quả mong đợi |
|---|---|
| Nhắn bot PM: "tạo ticket: lỗi đăng nhập trang admin" | Bot trả "⏳ Đã xếp hàng chờ duyệt #N" — **chưa** tạo gì trên Jira |
| Vào menu **Việc** trên dashboard (badge đỏ hiện số việc chờ) | Khối "Cần bạn duyệt" hiện yêu cầu #N của agent tương ứng |
| Bấm **Xem & duyệt** → **Approve & post** | Jira issue thật được tạo, approval biến mất khỏi hàng chờ, badge giảm |
| Thử lệnh nguy hiểm: "xóa hết ticket" | Bot **từ chối** — không có lệnh đó |

☐ Mục 5 đạt

## 6. Giao việc theo dõi nhiều ngày

| Việc làm | Kết quả mong đợi |
|---|---|
| Trong **Trợ lý**: "theo dõi PR số 1 của agent default tới khi merge" | Xác nhận → "Đã giao việc #N" |
| Vào menu **Việc**, cuộn xuống khối "Việc đã giao" | Thấy việc theo dõi PR #1, trạng thái "đang mở" |
| Bấm **Huỷ** trên việc đó | Trạng thái chuyển "đã huỷ" |

☐ Mục 6 đạt

## 7. Đăng xuất

| Việc làm | Kết quả mong đợi |
|---|---|
| Bấm **Đăng xuất** góc trên phải | Về màn hình đăng nhập |
| Bấm nút Back của trình duyệt | Không vào lại được dashboard (vẫn ở màn đăng nhập) |

☐ Mục 7 đạt

## 8. An toàn dữ liệu (người kỹ thuật làm giúp 1 lần)

| Việc làm | Kết quả mong đợi |
|---|---|
| Chạy `./deploy/backup.sh` | Tạo file `backups/mpm-backup-*.tar.gz`; in "(.env excluded)" |
| Mở archive kiểm tra | KHÔNG chứa file `.env` / token |

☐ Mục 8 đạt

---

## Kết luận

- Tất cả 8 mục ✅ → hệ thống sẵn sàng giao cho công ty vận hành.
- Bất kỳ mục nào ✗ → ghi lại số mục + mô tả hiện tượng, gửi người kỹ thuật.

## Câu hỏi thường gặp

- **Bot Telegram trả lời chậm ~1 phút?** Đúng — hệ thống kiểm tra tin mới theo nhịp (không phải tức thời). Đây là thiết kế.
- **Quên mật khẩu?** Người kỹ thuật chạy `mpm web hash-password` tạo hash mới, dán vào `.env`, khởi động lại dịch vụ web.
- **Muốn truy cập từ máy khác trong công ty?** Cần đặt `BIND_HOST=0.0.0.0` trong `.env` — hệ thống chỉ cho phép khi đã bật mật khẩu (bảo vệ nút Duyệt).
