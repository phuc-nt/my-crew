# UAT — Nghiệm thu các case quan trọng (v14, 2026-07-10)

Cách chạy app: `PORT=8765 uv run python -c "from src.server.app import main; main()"`
→ mở **http://127.0.0.1:8765**. Dừng: `lsof -ti :8765 | xargs kill`.

Điều kiện chung: đã có ít nhất 3-4 nhân sự agent (tạo qua wizard nếu chưa) — hoặc bật
nhanh bộ data chuẩn bằng **`scripts/demo-mode.sh on`** (công ty demo + 6 nhân sự + văn
phòng đang hoạt động; tắt bằng `off`, data thật được trả nguyên vẹn). LLM key cấu hình
trong `.env`. Case có 📱 cần Telegram bot đã nối; case có 📧 cần SMTP.
Đánh dấu: ✅ đạt / ❌ lỗi (ghi chú) / ⏭ bỏ qua (thiếu điều kiện).

---

## A. Nền tảng & điều hướng

- [ ] **A1 — App khởi động, đăng nhập**: Mở http://127.0.0.1:8765 → thấy trang chính
  tiếng Việt, 4 mục điều hướng (Trợ lý / Đội / Việc / Văn phòng + Cài đặt). Nếu đã đặt
  mật khẩu (`WEB_AUTH_PASSWORD_HASH`) thì bị chặn ở màn đăng nhập trước.
- [ ] **A2 — Theme**: Nút Sáng/Tối/Tự động góc phải trên — đổi theme ăn ngay, F5 vẫn nhớ.
- [ ] **A3 — Chế độ nâng cao**: Cài đặt → bật "Chế độ nâng cao" → menu hiện thêm các trang
  kỹ thuật (timeline, cost, audit…); tắt → menu gọn về 4 mục.

## B. Giao việc đội & vòng đời việc (lõi v12-v13)

- [ ] **B1 — Giao việc cho đội**: Trợ lý → gõ "giao đội: <việc có 3-5 đầu việc, nêu rõ cần
  nghiên cứu + viết nội dung + kiểm định>" → hệ thống trả **preview kế hoạch** (danh sách
  bước, ai làm, thứ tự) → bấm xác nhận → việc chuyển trạng thái chạy.
  Kỳ vọng: KHÔNG bước nào tự chạy trước khi CEO xác nhận.
- [ ] **B2 — Theo dõi tiến độ**: Văn phòng → Timeline hiện sự kiện thật theo thời gian:
  nhận việc → đang làm → tự soát → xong bước → bàn giao. Tab Việc hiện trạng thái + chi phí.
- [ ] **B3 — Tự soát + soát chéo (peer review)**: Với bước "viết nội dung" (needs_review):
  sau khi xong, hệ thống TỰ chèn bước soát chéo giao cho nhân sự khác (ưu tiên id có
  kiem/qa/review, không bao giờ là chính tác giả). Verdict "cần sửa" → tác giả gốc nhận
  bước sửa; tối đa 2 vòng; vẫn fail → việc dừng + báo CEO (không lặp vô hạn).
- [ ] **B4 — Hỏi ý kiến đồng nghiệp (consult)**: Trong timeline thấy dòng "X hỏi ý kiến Y"
  kèm tóm tắt câu hỏi/đáp ≤120 ký tự (KHÔNG lộ nguyên văn tài liệu).
- [ ] **B5 — Điều chỉnh kế hoạch giữa chừng (replan)**: Trợ lý → "điều chỉnh việc <id>:
  bỏ các bước chưa chạy, thêm bước X" → hệ thống trả **DIFF** (giữ bước đã xong/đang chạy,
  bỏ/thêm bước chờ) → xác nhận → việc TIẾP TỤC chạy (không bị dừng oan).
  Kỳ vọng: bước đã xong/đang chạy không bao giờ bị đổi.
- [ ] **B6 — Song song có kiểm soát**: Giao việc có các bước độc lập → tối đa 2 bước chạy
  cùng lúc (mặc định `team_task_concurrency=2`), bước thứ 3 chờ.

## B2. Giao việc @PIC + màn Văn phòng hợp nhất (v15 — mới)

Mở tab **Văn phòng** (màn hợp nhất: 3D + hoạt động trực tiếp + ô giao việc).

- [ ] **B2.1 — Màn hợp nhất**: 3D và cột "Hoạt động trực tiếp" cùng hiện, cùng cập nhật
  realtime (giao 1 việc → cả feed lẫn 3D thay đổi, không lệch nhau). `/office/3d` cũ tự
  chuyển về màn này; "Nhật ký văn phòng" (nâng cao) vẫn xem được dòng thời gian đầy đủ.
- [ ] **B2.2 — @ chỉ định PIC**: gõ `@` trong ô giao việc → danh sách nhân sự hiện ra;
  chọn `@noi-dung` + mô tả việc → bấm Giao việc → kế hoạch hiện **"PIC (chịu trách nhiệm
  chính): noi-dung"** và bước CUỐI (tổng hợp) thuộc noi-dung → Xác nhận → việc chạy;
  bàn noi-dung trên 3D có ⭐ + nhãn PIC.
- [ ] **B2.3 — @all / không @**: gõ việc không @ ai → kế hoạch hiện "X nhận làm PIC" với
  X là nhân sự có vai trò khớp (không bịa tên ngoài đội). Bấm Huỷ → việc không chạy.
- [ ] **B2.4 — @ sai tên**: gõ `@khong-ton-tai làm gì đó` → báo lỗi rõ ràng ngay, không
  tốn gọi LLM, không tạo việc rác.
- [ ] **B2.5 — Tự xác nhận**: Cài đặt → bật "Tự xác nhận kế hoạch khi giao việc" → giao
  `@phan-tich <việc>` → card **"ĐÃ TỰ XÁC NHẬN"** hiện, việc chạy ngay không cần bấm;
  tắt setting → quay lại hỏi xác nhận như cũ. Việc gửi RA NGOÀI vẫn chờ duyệt riêng (E1).
- [ ] **B2.6 — Chỉnh kế hoạch giữ PIC**: với việc có PIC đang chạy, "chỉnh kế hoạch <id>"
  → kế hoạch mới vẫn có đúng MỘT bước chốt cuối thuộc PIC (không mất người chịu trách nhiệm).

## B3. Phòng việc + bộ điều phối (v16 — mới)

- [ ] **B3.1 — Banner bộ điều phối**: tắt service → màn Văn phòng hiện banner đỏ trong
  ≤3 phút; bật `uv run python -m src.runtime.service` → banner tự ẩn, việc pending chạy.
- [ ] **B3.2 — Phòng việc**: giao việc mới → tự vào phòng của việc; danh sách phòng trái
  hiện ●/⚠/✓; quay lại phòng cũ đủ lịch sử; "Toàn cảnh" xem cả đội.
- [ ] **B3.3 — Chat trong phòng**: hỏi "tiến độ thế nào?" → trả lời tại chỗ (không tạo
  việc); "giao @x …" → việc con cùng phòng; "chỉnh [mã việc]: …" → DIFF → xác nhận sửa.
- [ ] **B3.4 — Desk sạch**: nhân sự không còn trong registry không hiện bàn 3D (sự kiện
  cũ vẫn còn trong nhật ký chữ).

## B4. Command center 3 cột + Kết quả (v17 — mới)

- [ ] **B4.1 — Trang chủ**: mở app (`/`) → vào thẳng Văn phòng; nav: Văn phòng · Đội ·
  Duyệt · Trợ lý · Cài đặt.
- [ ] **B4.2 — Cột Kết quả**: chọn phòng có bước đã bàn giao → cột phải list bước ✅ →
  bấm → xem FULL nội dung render markdown (tiêu đề/bảng/danh sách đẹp, không thô) →
  Copy + Tải .md chạy; Esc đóng; vào lại phòng cũ vẫn xem được.
- [ ] **B4.3 — Bóng thoại sạch**: nhân sự đã xong/rảnh KHÔNG còn treo thoại việc cũ;
  chỉ người đang làm (hoặc đang tham vấn 💬) có thoại.
- [ ] **B4.4 — Duyệt**: tab Duyệt đủ 2 phần: "Cần bạn duyệt" (badge số) + "Việc đã giao
  cho từng nhân sự" (board cũ nguyên vẹn).

## B5. Đội & registry (v18 — mới)

- [ ] **B5.1 — Hồ sơ mồ côi**: có thư mục profiles/<id> hợp lệ chưa trong đội → trang
  Đội hiện "Hồ sơ chưa trong đội" → bấm Thêm → agent vào bảng đội + giao việc thấy ngay
  (không cần khởi động lại); lịch báo cáo của agent mới tự kích hoạt ở tick kế.
- [ ] **B5.2 — Registry là dữ liệu của bạn**: chỉnh đội (thêm/tắt agent) → chạy các lệnh
  git bất kỳ → đội KHÔNG bị hoàn tác (registry.yaml không còn trong git).
- [ ] **B5.3 — Cảnh báo web_search**: agent bật web_search mà máy thiếu TAVILY/BRAVE key
  → Sức khỏe hệ thống hiện cảnh báo kèm tên agent; thêm key hoặc tắt flag → hết cảnh báo.
- [ ] **B5.4 — 3D theo giao diện**: bật chế độ Tối → nền không gian 3D tối theo, nhãn
  vẫn đọc rõ; đổi lại Sáng không cần tải lại trang.

## C. Văn phòng 3D "sống" (v14)

Không gian 3D nằm ngay trong tab **Văn phòng** (v15 — không còn menu riêng).

- [ ] **C1 — Toàn cảnh sống**: Thấy bàn trưởng phòng giữa, mỗi nhân sự một bàn; nội thất:
  2 chậu cây, bảng viết có nét chữ, ghế sofa, đèn cây. Avatar có tay chân, đội nón/đeo
  kính/cà vạt theo người, nhấp nhô thở nhẹ.
- [ ] **C2 — Camera tự xoay**: Không đụng chuột ~10 giây → góc nhìn tự xoay chậm liên tục.
  Kéo chuột → camera theo tay, thả ra vài giây → tự xoay tiếp. Cuộn = zoom.
- [ ] **C3 — Đi lại gần nhau khi tham vấn**: Khi có sự kiện consult (chạy việc thật có bước
  cần hỏi ý kiến, hoặc chờ B4 xảy ra) → HAI avatar rời bàn, đi lại gần nhau giữa 2 bàn,
  quay mặt vào nhau, bubble 💬 hiện tên người đối thoại ở cả 2 phía.
- [ ] **C4 — Tự về bàn**: Sau consult, khi MỘT trong hai người có việc tiếp (sự kiện mới)
  → CẢ HAI avatar tự đi về bàn mình (không ai đứng kẹt giữa phòng).
- [ ] **C5 — Giai đoạn trên bubble**: Bubble hiện đúng giai đoạn thật: *đang làm* →
  *tự soát* → *đang sửa*; màu viền bàn đổi theo trạng thái (xám/xanh dương/cam/xanh lá).
- [ ] **C6 — Fallback 2D**: Bật "Giảm chuyển động" (macOS: System Settings → Accessibility
  → Display → Reduce motion) rồi F5 → thấy BẢNG 2D thay canvas 3D, đủ thông tin trạng thái.

## D. Bước kẹt tự cứu (v14 — mới)

- [ ] **D1 — Nhờ trợ giúp rồi tự phục hồi**: Khi một bước gặp lỗi lúc chạy (ví dụ LLM lỗi
  tạm thời), bubble 3D + timeline hiện giai đoạn **"nhờ trợ giúp"**, hệ thống tự hỏi 1
  đồng nghiệp về chỗ kẹt rồi thử lại MỘT lần. Thành công → việc đi tiếp bình thường.
  (Khó ép lỗi thật theo ý muốn — chấp nhận quan sát khi xảy ra tự nhiên, hoặc tin cậy
  9 test tự động đã cover; case này ⏭ được nếu không gặp.)
- [ ] **D2 — Fail thật vẫn báo đúng**: Nếu thử lại vẫn lỗi → bước đánh dấu thất bại +
  escalate CEO (timeline/Telegram), KHÔNG lặp vô hạn, KHÔNG nuốt lỗi.

## E. An toàn & phê duyệt (bất biến — phải giữ)

- [ ] **E1 — Ghi ra ngoài phải qua duyệt (Lớp B)**: Việc có bước "đăng lên Slack/
  Confluence" → bước DỪNG chờ duyệt; mục duyệt hiện trong tab Việc/Approvals; CEO duyệt
  → bước chạy tiếp; từ chối → bước fail + báo lại. Không có ghi ngoài nào tự chạy không
  qua duyệt (trừ khi đã bật auto-approve Lớp B ở trust ladder).
- [ ] **E2 — Trust ladder**: Cài đặt → nâng mức tin cậy cho 1 agent → hành động Lớp B của
  agent đó tự duyệt (có ghi audit); hạ mức → quay lại chờ duyệt.
- [ ] **E3 — Nội dung nội bộ không rò ra timeline**: Timeline/3D chỉ hiện tóm tắt template
  (tiêu đề bước, đếm lỗi, tóm tắt ≤120c) — KHÔNG bao giờ hiện nguyên văn tài liệu, SOUL.md,
  hay câu trả lời đầy đủ của consult.

## F. Báo cáo & kênh ngoài

- [ ] **F1 — Báo cáo định kỳ**: Chờ lịch (hoặc chạy tay `run-now`) báo cáo tuần/OKR →
  đăng đúng kênh Slack/Confluence đã cấu hình, nội dung tiếng Việt, có số liệu thật.
- [ ] **F2 📧 — Xuất Excel qua email**: Báo cáo nguồn lực/OKR kèm file `.xlsx` đính email
  (Lớp B — qua duyệt nếu chưa auto-approve); mở file được bằng Excel/Numbers.
- [ ] **F3 📱 — Telegram CEO**: Nhắn bot: hỏi trạng thái đội, giao việc nhanh, duyệt/từ chối
  approval từ Telegram → phản hồi đúng và khớp với web.
- [ ] **F4 📱 — Cảnh báo agent chết ngầm**: Tắt 1 agent đang có lịch chạy (hoặc để quá hạn)
  → nhận cảnh báo Telegram trong chu kỳ giám sát.

## G. Hồi quy nhanh (sanity)

- [ ] **G1**: `uv run pytest -q` → 1657 passed.
- [ ] **G2**: `cd web && npx vitest run` → 162 passed; `npx tsc --noEmit` sạch.
- [ ] **G3**: Tab Đội hiện đủ nhân sự + chi phí; Health panel (Cài đặt) các tích hợp xanh.

---

## Ghi chú kết quả

| Ngày | Người test | Case fail | Ghi chú |
|------|-----------|-----------|---------|
|      |           |           |         |

Câu hỏi mở: D1 khó tái hiện chủ động trên UAT (không ép được provider lỗi có kiểm soát) —
đã cover bằng test tự động mức graph; nếu cần demo trực quan, có thể yêu cầu bổ sung
"công tắc giả lập lỗi" chỉ bật ở môi trường dev.
