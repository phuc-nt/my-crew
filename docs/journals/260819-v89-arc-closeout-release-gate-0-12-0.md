# v89 — Đóng arc v88: mobile, cold start, dọn nợ, cổng release 0.12.0
2026-08-19 · ✅ Done · **chưa release** (chờ CEO bấm tag)

## Làm gì

- **Layout điện thoại** cho shell 5 hub + luồng chat: thanh tab dưới đủ 5 hub, 4 nút
  chrome gộp vào menu `⋯`, chat thành hai màn (danh sách → hội thoại) có Back, deep
  link mở thẳng hội thoại. 5 e2e mobile mới ở 390px canh không hub nào tràn ngang.
- **Vá cold start** từ audit bản cài mới: tuyển người đầu tiên có đường tới; Resume
  xoá luôn cổng `enabled` trong profile (trước chỉ lật registry → nút vô tác dụng,
  chỉ sửa được bằng tay); profile hỏng degrade thay vì 500; thông báo chặn giao việc
  nêu đúng màn cần mở (`Đội ngũ → Kênh`) thay vì từ vựng backend.
- **Dọn nợ v88**: `views/office-unified` + `views/office-shared` chuyển về đúng chủ
  (`features/office/`, `features/shared/` mới) — `src/views/` chỉ còn cửa pre-auth
  Login/Setup; xoá 3 api method chết + 1 type mồ côi; thư mục phụ thuộc ở root vào
  .gitignore; đồng bộ 6 file docs về as-built v88.
- **Cổng release 0.12.0**: 6 ca delta-UAT trên daemon thật + browser thật + wheel thật,
  bump version + changelog. Không tag, không publish.

## Quyết định & vì sao

| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| Chủ sở hữu file suy từ consumer thật (grep import), không theo tên thư mục cũ | Tên `office-unified` là di sản của màn đã chết; đi theo nó sẽ đẻ ra `features/shared/` chứa cả thứ chỉ office dùng | Phải đọc từng import trước khi move, chậm hơn `git mv` cả cụm |
| Giữ nguyên "21 redirect" trong journal v88 dù grep ra 23 | Journal là bản ghi lịch sử của arc, không phải tài liệu as-built | Số trong journal lệch số hiện tại, người đọc sau có thể gợn |
| Bump 0.12.0 nhưng **không** tag | Release là quyết định của CEO, đã chốt từ trước | Commit `01b43a9` nằm chờ; nếu để lâu, changelog sẽ lệch với việc làm thêm |
| Không rerun benchmark cho gate này | Delta thuần FE + backend additive; không đụng đường chạy LLM nào | Nếu có regression hiệu năng ẩn trong tầng dữ liệu mới thì gate này không bắt |

## Vấp & học được

- **Suite xanh vẫn giấu bug thật — lần thứ hai liên tiếp.** `test_list_survives_a_broken_profile`
  mock `raise RuntimeError(...)` nên luôn xanh, trong khi loader chỉ ném `RuntimeError`
  khi YAML *parse được nhưng sai hình dạng*. File **không parse nổi** (người mới gõ
  nhầm — ca phổ biến nhất) ném `yaml.YAMLError`, thoát cả 2 chốt, 500 cả roster lẫn
  khung chi tiết. Chỉ lộ khi cho file hỏng **thật** chạy qua loader **thật**. Học:
  mock exception là mock luôn giả định "loại lỗi nào xảy ra" — chính giả định cần kiểm.
- **Suýt kết luận sai vì công cụ đo, không phải vì code.** SSE trả 0 payload qua 3 kiểu
  đọc stream tự viết; đã đi tra path DB, proxy, auth middleware. Hoá ra `curl -D -`
  báo rõ "1118 bytes received" — server luôn đúng, reader của mình nuốt dữ liệu. Học:
  khi tầng dưới (store) chứng minh có dữ liệu mà tầng trên báo rỗng, nghi client trước.
- **Sai URL trông y hệt sai tính năng.** `/api/office/rooms` (trả list string) vs
  `/api/office/workrooms` (trả object có `last_seq`) — gọi nhầm cái đầu ra `AttributeError`,
  đọc thoáng dễ tưởng field mới chưa được ghi.
- **`cd` trong lệnh nền không sống sót**: pytest chạy nền từ cwd `web/` ra file rỗng,
  không báo lỗi. Chạy lại foreground từ root mới có kết quả.

## Mở / sang sau

- **Rail escalation vẫn ép Telegram là đường báo duy nhất** — cold start của người
  không dùng Telegram vẫn cụt. Quyết định sản phẩm, không phải bug; đã đưa vào roadmap.
- Chưa có test cold-start tự động — gate này chạy tay, lần sau vẫn phải chạy tay.
- Bảng việc hiện 1 task ở 2 cột khi còn preview draft bỏ dở.
- Đổi mật khẩu vẫn chưa làm được (nợ từ v88, `api/client.ts` chưa có endpoint).
