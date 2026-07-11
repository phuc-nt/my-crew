# UAT theo User Story — my-project-manager (v18, 2026-07-11)

Tài liệu nghiệm thu **theo góc nhìn người dùng**: mỗi mục là một *user story* (CEO / người
quản lý một-người muốn gì) + kịch bản kiểm thử để tự tay xác nhận sản phẩm làm đúng story.

## Chân dung người dùng

**CEO / Founder một-người** (không phải kỹ thuật): điều hành công ty qua web + Telegram,
"thuê" một đội **nhân sự ảo AI** làm việc PM/nội dung/nghiên cứu/phân tích/kiểm định.
Nguyên tắc cốt lõi: *nhân sự ảo tự chủ về TỐC ĐỘ, không bao giờ tự chủ về TRÁCH NHIỆM* —
mọi việc gửi ra ngoài công ty đều chờ CEO duyệt; việc nguy hiểm bị chặn cứng.

## Cách dùng tài liệu

- Mở app: `http://127.0.0.1:8765` (mặc định). Bộ điều phối phải chạy:
  `uv run python -m src.runtime.service` (hoặc dịch vụ nền đã cài).
- Muốn có sẵn công ty mẫu để thử nhanh: `scripts/demo-mode.sh on` (tắt: `off`).
- Đánh dấu mỗi tiêu chí: ✅ đạt / ❌ lỗi (ghi chú) / ⏭ bỏ qua (thiếu điều kiện).
- Ký hiệu điều kiện: 📱 cần Telegram · 📧 cần SMTP · 🌐 cần web-search key · 🔗 cần Jira/Slack thật.

---

## EPIC 1 — Dựng công ty & đội ngũ

### US-1.1 — Cài đặt & kết nối
> **Là** CEO, **tôi muốn** cài đặt một lần và kết nối các công cụ (Jira, Slack, GitHub…),
> **để** đội ảo có thể đọc dữ liệu công ty và làm việc.

- [ ] Chạy `./deploy/install.sh` → báo thiếu công cụ (nếu có) kèm lệnh cài, không tự cài bừa.
- [ ] Setup Wizard mở trong trình duyệt → điền key từng bước, mỗi bước có "Kiểm tra kết nối".
- [ ] **Cài đặt → Sức khỏe hệ thống**: mọi kết nối đã cấu hình hiện ● xanh; mục lỗi kèm lệnh sửa.
- [ ] Bí mật chỉ đi qua Wizard (ghi vào `.env`), không qua terminal/URL; Wizard tự khóa sau khi xong.

### US-1.2 — Tuyển nhân sự ảo
> **Là** CEO, **tôi muốn** tạo nhân sự ảo cho từng vai trò, **để** có đội làm việc.

- [ ] **Đội → "+ Tạo nhân sự ảo"**: tạo qua hội thoại (Trợ lý) hoặc biểu mẫu; agent xuất hiện ở bảng Đội.
- [ ] Tạo được các vai trò office: trưởng phòng (điều phối), nghiên cứu, nội dung, phân tích, kiểm định.
- [ ] Đặt một agent làm **trưởng phòng** (coordinator) — đội cần trưởng phòng mới nhận việc được.
- [ ] (v19) Nhân viên mới có workspace đủ: `profile.yaml`/`SOUL.md`/`PROJECT.md`/`MEMORY.md`
  + `vault/` (bộ nhớ, dùng ở v19.5) + `skills/` (kỹ năng riêng) — giao việc được ngay.

### US-1.3 — Đội của tôi không bị mất (v18)
> **Là** CEO, **tôi muốn** cấu hình đội của mình được giữ an toàn, **để** không bị mất khi cập nhật hệ thống.

- [ ] Chỉnh đội (thêm/tắt agent) → chạy cập nhật/`git pull`/lệnh git bất kỳ → **đội KHÔNG bị hoàn tác**.
- [ ] Nếu có hồ sơ nhân sự tồn tại trên máy mà chưa vào đội → **Đội** hiện mục *"Hồ sơ chưa
  trong đội (N)"* → bấm **"Thêm vào đội"** → agent vào bảng + **giao việc được ngay** (không
  cần khởi động lại); hồ sơ lỗi hiện ghi chú, không cho thêm.

---

## EPIC 2 — Giao việc cho đội

### US-2.1 — Giao việc và chỉ định người phụ trách (PIC) (v15)
> **Là** CEO, **tôi muốn** giao một việc và nói rõ ai chịu trách nhiệm chính, **để** việc có chủ.

- [ ] **Văn phòng** → ô giao việc → gõ `@noi-dung Soạn bài giới thiệu sản phẩm…` (gõ `@` hiện
  danh sách chọn) → hệ thống hiện **kế hoạch + "PIC: noi-dung"** → **Xác nhận giao việc**.
- [ ] Bước chốt/tổng hợp cuối cùng thuộc về PIC; các bước chuyên môn khác chia đúng người.
- [ ] Trên 3D, bàn của PIC có dấu **⭐** + nhãn **PIC**.

### US-2.2 — Để đội tự chọn người phụ trách (v15)
> **Là** CEO, **tôi muốn** giao việc mà không cần chỉ định ai, **để** đội tự phân công hợp lý.

- [ ] Gõ `@all …` hoặc **không @ ai** → kế hoạch hiện *"X nhận làm PIC"* với X là nhân sự
  hợp lệ trong đội (không bịa tên ngoài đội).
- [ ] Bấm **Huỷ** → việc không chạy, không để lại rác.

### US-2.3 — Giao là chạy ngay (tùy chọn) (v15)
> **Là** CEO đã tin đội, **tôi muốn** bỏ bước bấm xác nhận, **để** giao việc nhanh hơn.

- [ ] **Cài đặt → "Tự xác nhận kế hoạch khi giao việc"** bật → giao `@phan-tich …` → hiện
  **"ĐÃ TỰ XÁC NHẬN"**, việc chạy ngay không cần bấm; tắt → quay lại hỏi xác nhận.
- [ ] Dù bật tự-xác-nhận, việc **gửi ra ngoài công ty** vẫn chờ duyệt riêng (xem US-4.1).

### US-2.4 — @ sai tên báo lỗi ngay
> **Là** CEO, **tôi muốn** được báo lỗi rõ khi gõ nhầm tên, **để** không tạo việc rác.

- [ ] Gõ `@khong-ton-tai …` → báo lỗi *"không có trong danh sách nhân sự"* NGAY, không gọi
  LLM, không tạo việc.

---

## EPIC 3 — Theo dõi & điều phối công việc

### US-3.1 — Xem đội làm việc theo thời gian thực (v12/v16/v17)
> **Là** CEO, **tôi muốn** thấy đội đang làm gì realtime, **để** yên tâm việc đang chạy.

- [ ] **Văn phòng** = màn chính (mở app vào thẳng đây): 3D trên + 3 cột *Phòng việc | Hoạt
  động | Kết quả* + ô chat/giao việc.
- [ ] Cột **Hoạt động** cập nhật realtime với icon/màu theo loại (📋 phân công, ⚙ tiến độ,
  ✅ bàn giao, 🔍 soát chéo, 💬 tham vấn); tên nhân sự tô màu.
- [ ] Bóng thoại 3D chỉ hiện với nhân sự **đang làm việc** (người xong/rảnh không treo thoại cũ).

### US-3.2 — Mỗi việc một "phòng việc" riêng, quay lại được (v16)
> **Là** CEO, **tôi muốn** mỗi việc có không gian riêng và xem lại được, **để** không lẫn lộn.

- [ ] Giao việc mới → tự vào **phòng việc** của việc đó; danh sách phòng bên trái (● đang
  chạy / ⚠ kẹt / ✓ xong).
- [ ] Chọn phòng khác → feed + chat + kết quả đổi theo phòng; quay lại phòng cũ **đủ lịch sử**.
- [ ] "Toàn cảnh" xem cả đội; "Nhật ký văn phòng" (nâng cao) xem dòng thời gian đầy đủ.

### US-3.3 — Hỏi tiến độ & chỉnh việc bằng chat (v16)
> **Là** CEO, **tôi muốn** hỏi/điều chỉnh việc bằng ngôn ngữ tự nhiên, **để** không cần thao tác phức tạp.

- [ ] Trong phòng, hỏi *"tiến độ thế nào?"* → trả lời từ trạng thái thật, **không tạo việc mới**.
- [ ] Gõ *"chỉnh: bỏ bước cuối, thêm bước X"* (hoặc `chỉnh <mã việc>: …` khi phòng nhiều
  việc) → hiện **DIFF** → **Xác nhận sửa** → việc tiếp tục theo kế hoạch mới; bước đã
  xong/đang chạy không bị đổi.
- [ ] Gõ *"giao @thiet-ke …"* → tạo **việc con cùng phòng** (phòng hiện nhiều việc).

### US-3.4 — Xem kết quả bàn giao đầy đủ (v17)
> **Là** CEO, **tôi muốn** đọc kết quả nhân sự làm ra, **để** kiểm tra và sử dụng.

- [ ] Việc xong → cột **Kết quả** hiện các bước đã bàn giao → bấm 1 bước → xem **toàn văn,
  render markdown đẹp** (tiêu đề/bảng/danh sách).
- [ ] Có nút **Copy** (vào clipboard) và **Tải .md**; **Esc** đóng.
- [ ] Vào lại phòng cũ (kể cả sau khi khởi động lại) vẫn xem lại được kết quả.

---

## EPIC 4 — Kiểm soát & an toàn (BẤT BIẾN — quan trọng nhất)

### US-4.1 — Duyệt việc gửi ra ngoài (Lớp B)
> **Là** CEO, **tôi muốn** phê duyệt trước mọi việc gửi ra ngoài công ty, **để** giữ kiểm soát.

- [ ] 🔗 Việc có bước "đăng Slack / tạo Jira / gửi email" → bước **DỪNG chờ duyệt**; hiện ở tab **Duyệt**.
- [ ] Bấm **"Xem & duyệt"** → hộp thoại tóm tắt tiếng Việt việc sắp làm; việc **gửi RA NGOÀI**
  tô **đỏ đậm** cảnh báo. **Duyệt & thực hiện** để chạy / **Từ chối** để bỏ.
- [ ] Không có việc gửi-ngoài nào tự chạy khi chưa duyệt (trừ khi đã bật auto-approve Lớp B).

### US-4.2 — Việc nguy hiểm bị chặn cứng
> **Là** CEO, **tôi muốn** hệ thống chặn tuyệt đối việc phá hoại, **để** an tâm cả khi lỡ tay.

- [ ] Việc **xoá vĩnh viễn dữ liệu / lộ bí mật** không bao giờ thực hiện được, kể cả khi CEO duyệt.
- [ ] Nội dung nội bộ (tài liệu, hồ sơ nhân sự, câu trả lời đầy đủ) **không rò** ra dòng thời
  gian/3D — chỉ hiện tóm tắt.

### US-4.3 — Nâng mức tin cậy cho nhân sự (Trust ladder) (v8)
> **Là** CEO, **tôi muốn** cho một nhân sự tự-duyệt việc Lớp B khi đã tin, **để** giảm thao tác.

- [ ] Nâng mức tin cậy 1 agent → hành động Lớp B của agent đó tự duyệt (**vẫn ghi audit**);
  hạ mức → quay lại chờ duyệt.

---

## EPIC 5 — Đội tự vận hành (nâng cao)

### US-5.1 — Tự kiểm và soát chéo (v13)
> **Là** CEO, **tôi muốn** đội tự đảm bảo chất lượng, **để** tôi không phải soi từng bước.

- [ ] Bước tạo nội dung xong → hệ thống **tự chèn bước soát chéo** giao cho nhân sự khác
  (không phải tác giả); nếu "cần sửa" → tác giả sửa (≤2 vòng); vẫn fail → dừng + báo CEO.
- [ ] Toàn bộ tự động, không cần CEO duyệt từng lần tự kiểm.

### US-5.2 — Nhân sự hỏi ý kiến nhau (v13/v14)
> **Là** CEO, **tôi muốn** đội phối hợp như người thật, **để** kết quả tốt hơn.

- [ ] Khi cần, nhân sự **hỏi ý kiến đồng nghiệp** (thấy trên feed + 2 avatar 3D đi lại gần nhau).
- [ ] Bước gặp lỗi tạm thời → hiện *"nhờ trợ giúp"*, tự hỏi đồng nghiệp và **thử lại một lần**
  trước khi báo thất bại.

### US-5.3 — Song song có kiểm soát (v13)
> **Là** CEO, **tôi muốn** việc chạy nhanh mà không quá tải, **để** hiệu quả và an toàn chi phí.

- [ ] Việc có bước độc lập → tối đa 2 bước chạy cùng lúc; mỗi việc có trần chi phí (mặc định $2).

---

## EPIC 6 — Báo cáo & cảnh báo

### US-6.1 — Báo cáo định kỳ tự động
> **Là** CEO, **tôi muốn** nhận báo cáo tuần/OKR/nguồn lực tự động, **để** nắm tình hình.

- [ ] 🔗 Báo cáo chạy theo lịch (hoặc chạy tay ở **Chạy tay**) → đăng đúng kênh
  Slack/Confluence; nội dung tiếng Việt, số liệu thật.
- [ ] 📧 Báo cáo nguồn lực/OKR đính kèm **file .xlsx** qua email (Lớp B) — mở được bằng Excel/Numbers.

### US-6.2 — Nhận cảnh báo khi có vấn đề (v8/v16/v18)
> **Là** CEO, **tôi muốn** được cảnh báo sớm, **để** xử lý kịp thời.

- [ ] 📱 Agent **chết ngầm** (quá hạn không chạy) → nhận cảnh báo Telegram.
- [ ] **Bộ điều phối chưa chạy** → màn Văn phòng hiện **banner đỏ** "việc đã giao sẽ không
  tiến triển" + hướng dẫn bật; bật lên → banner tự ẩn, việc chờ chạy tiếp.
- [ ] 🌐 Agent bật web_search mà máy thiếu key → **Sức khỏe hệ thống** cảnh báo kèm tên agent.

### US-6.3 — Điều hành qua Telegram (v6)
> **Là** CEO, **tôi muốn** ra lệnh và duyệt từ điện thoại, **để** không phải mở máy tính.

- [ ] 📱 Nhắn bot: hỏi trạng thái đội, giao việc nhanh, duyệt/từ chối approval → phản hồi
  đúng và khớp với web.

---

## EPIC 7 — Trải nghiệm & trình diễn

### US-7.1 — Giao diện dễ nhìn (v10/v18)
> **Là** CEO, **tôi muốn** giao diện gọn, sáng/tối tuỳ ý, **để** dùng thoải mái.

- [ ] Nút **Sáng/Tối/Tự động** đổi ngay, nhớ lần sau; **chế độ Tối** làm nền 3D tối theo
  (nhãn vẫn đọc rõ), không cần tải lại.
- [ ] Màn hình hẹp (điện thoại): 3 cột xếp dọc, danh sách phòng cuộn ngang gọn.
- [ ] **Chế độ nâng cao** (Cài đặt) hiện thêm trang kỹ thuật; tắt → giao diện gọn.

### US-7.2 — Trình diễn cho khách (demo mode)
> **Là** CEO, **tôi muốn** show sản phẩm cho khách mà không lộ dữ liệu thật, **để** an toàn.

- [ ] `scripts/demo-mode.sh on` → công ty mẫu + đội đủ + văn phòng đang hoạt động + bộ
  điều phối demo chạy; `off` → **trả data thật nguyên vẹn** (đã kiểm byte-identical).
- [ ] `scripts/demo-mode.sh status` cho biết đang ở chế độ nào.

---

## Bảng ghi kết quả

| Ngày | Người test | Story fail | Ghi chú |
|------|-----------|-----------|---------|
|      |           |           |         |

## Câu hỏi mở

- US-5.2 (nhờ trợ giúp khi lỗi thật): khó ép tái hiện lỗi có kiểm soát — chấp nhận quan
  sát khi xảy ra tự nhiên, hoặc tin bộ test tự động đã cover.
- US-6.1 web-search: nếu chưa có Tavily/Brave key, bước nghiên cứu sẽ "xin phép tra cứu
  web" thay vì dữ liệu thật (đúng thiết kế fail-degrade) — không tính là fail chức năng.
