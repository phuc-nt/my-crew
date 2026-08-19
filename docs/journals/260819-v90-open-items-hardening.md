# v90 — Đóng 5 mục treo sau cổng release 0.12.0
2026-08-19 · ✅ Done · chưa release

## Làm gì

- **Gỡ Telegram khỏi thế độc đạo báo vận hành.** `operator_channels.send_via_channels()`
  thử telegram → smtp → webhook; seam đặt trong `operator_notify._try_send` nên **8**
  consumer thoát cùng lúc chứ không phải 2 call-site như plan. `OPERATOR_EMAIL`,
  `OPERATOR_WEBHOOK_URL` là env presence, KHÔNG vào `company.yaml` (`save_company` dựng
  lại từ dict cứng nên nuốt key viết tay).
- **Đổi mật khẩu** — `POST /api/auth/change-password` + ô trong tab Cài đặt. Đổi mật khẩu
  ghi lại luôn `WEB_SESSION_SECRET`, giết mọi cookie đã ký, kể cả của chính người đổi.
- **Bỏ bản nháp ngay trên bảng việc** — trước đây nháp bỏ dở là thẻ ma không cách nào dọn
  vì chỉ màn giao việc đang mở mới hủy được.
- **`scripts/cold-start-smoke.sh`** — dựng wheel → soi trong zip → cài venv sạch → seed
  home rỗng → `/health` → (`--browser`) Playwright thật trên backend thật.
- **Thứ tự `/api/approvals/pending`** — index toàn fleet giờ cũ-nhất-lên-đầu thay vì gom
  theo vòng duyệt registry.

## Quyết định & vì sao

| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| `send_via_channels` trả **`None`** khi agent không có kênh, tách khỏi `False` | Caller đang duyệt danh sách agent (điều phối → dự phòng → admin) phải **đi tiếp** khi gặp agent câm, chứ không dừng như gặp lỗi gửi | Hợp đồng 3 trạng thái phải nhớ, khó hơn bool |
| Đổi mật khẩu = xoay session secret | Đổi mật khẩu khi nghi bị xâm nhập mà phiên cũ vẫn sống thì đổi làm gì | Chính người đổi bị đăng xuất — phải nói rõ trên UI |
| `send_plain_email` nhét vào `email_write.py`, không tạo module mới | Guard `test_smtplib_imported_only_in_email_write` bắt `smtplib` chỉ có một nhà | File dài thêm |
| Config Playwright **thứ hai** cho cold start | Suite cũ mock mọi `/api` + tự spawn `vite dev` — mock ở đây là vô hiệu hoá chính bài test | 2 config phải cùng bảo trì |
| Hủy nháp **không** xoá lạc quan, chỉ invalidate | Nếu điều phối viên vừa kịp xác nhận nháp trong tích tắc đó, thẻ phải còn — đúng thực tế thay vì đúng theo ý FE | Chậm hơn một nhịp |

## Vấp & học được

- **Tạo `operator_notify.py` mà không grep chính cái tên file sắp tạo → đè mất module có
  sẵn.** Grep theo *nội dung* ("escalat", "telegram") kỹ đến mấy cũng không thay được một
  lệnh `ls` trên đường dẫn sắp ghi. Lộ ra vì `ImportError` ở 2 test fullflow, khôi phục
  bằng `git checkout`. Tai nạn lại cho thiết kế tốt hơn: seam trong `_try_send` phủ 8
  consumer.
- **Xác minh sống lần đầu chứng minh nhầm thứ.** Chạy với `coordinator` — agent này CÓ
  Telegram nên `channels_for` = `['telegram','webhook']` và Telegram thắng; webhook chưa
  hề được thử. Phải chạy lại với `researcher` (không Telegram) mới thấy `['webhook']` →
  `True` → receiver ghi được payload thật. **Chọn sai đối tượng test thì test xanh vẫn vô
  nghĩa.** Đếm được luôn quy mô vấn đề gốc: **7/11 agent** trong fleet thật không có kênh
  báo nào.
- **Thiếu một dấu phẩy trong `__all__` không phải lỗi cú pháp.** Hai string literal cạnh
  nhau tự nối, `verify_current_password` lặng lẽ biến mất khỏi export. `ast.parse` bắt được.
- **Test-first có giá trị đo được ở phase 5**: test thứ tự ĐỎ với diff thật
  (`'2026-08-19T12:00:00+00:00' != '2026-08-18T09:00:00+00:00'`) trước khi thêm một dòng
  `sort`, nên biết chắc dòng đó gánh việc chứ không phải trang trí.

## Mở / sang sau

- 0.12.0 **vẫn chưa tag, chưa publish** — chờ CEO bấm `git tag -a v0.12.0` + `git push`.
- Cold-start smoke mới chạy tay; chưa gắn vào workflow CI nào (cố ý: nó dựng wheel + cài
  venv, đắt cho mỗi push — hợp với gate release hơn là gate PR).
