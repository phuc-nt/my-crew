# Cắt bản 0.19.0 — recut hai baseline, và probe advisor đo nhầm thứ

2026-09-19 · ✅ Done (đã publish PyPI)

## Làm gì

- Bump `0.19.0`, đóng mục `[Unreleased]` trong CHANGELOG, chạy `uv sync --extra deep`
  **trước** mọi việc cắt baseline (tránh bẫy nhãn version của `conftest._version()`).
- Đẩy 14 commit chưa từng qua CI lên `main` rồi chờ xanh — tag kích hoạt publish PyPI
  nên không được tag trên cây chưa có lưới an toàn.
- Recut `bench/role_baseline_0.19.0.json` (k=3, cả 7 vai `good` 1.00) và
  `bench/journey_baseline_0.19.0.json` (9/9 live, 821s).
- Viết `docs/release-evidence-0.19.0.md`; sửa `docs/releasing.md` chỗ ghi bộ live đầy đủ
  "~12 phút" trong khi thực đo **3h03**.
- Tag `v0.19.0` → `release.yml` → PyPI (verify bằng API PyPI, không tin mỗi exit code).

## Quyết định & vì sao

| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| Đuổi theo `advisor` 0.67 thay vì ghi "variance" | Nó là trục **duy nhất** đỏ trong vòng; gọi tên là nhiễu thì phải có bằng chứng, mà lúc đó chưa có | Tốn thêm một vòng bench 40 phút |
| Sửa **probe**, không sửa `advisor_sweep` | Rào chắn đang làm đúng việc: note trôi ngôn ngữ / quá dài bị nuốt để agent không đọc phải lệnh hỏng | Điểm vai giờ phụ thuộc vào bộ giải mã dùng chung — probe và sweep buộc phải đọc reply y hệt nhau |
| Tách `_coerce_json` khỏi `_parse_verdict` | Để bench không chép lại logic bóc ```-fence; hai bên lệch nhau là sai kiểu khó thấy | Thêm một hàm nhỏ |
| Baseline vai dựa mốc `0.17.0`, bỏ qua `0.18.0` | `0.18.0` cố ý **không** recut vì cú tụt review vòng đó là chuyện định tuyến, không phải code | So với mốc cũ 2 bản, nhưng đúng mốc sạch |
| Giữ nguyên j1/j5 đổi `parked:open`→`done` trong baseline | Test pin bất biến (status đơn điệu, cost>0, chuỗi audit) chứ **không** pin terminal state — đó là lựa chọn của model | Baseline có 2 số "đẹp lên" mà không được phép kể công |

## Vấp & học được

- **Probe đo nhầm đối tượng thì điểm số vẫn trông rất thuyết phục.** `advisor` 0.67 `weak`,
  hai lỗi `wrong` dồn vào đúng một upstream — đọc kiểu nào cũng ra "model provider kém".
  Chỉ khi replay 8 lần **kèm raw reply cạnh verdict** mới thấy: 3/3 ca trống đều là rào
  chắn bắn đúng trên một note đã nêu đúng vòng lặp 403 (2 ca model trôi sang tiếng
  Croatia/Romania, 1 ca xả 16.434 ký tự một chữ lặp). Tức probe đang chấm **lỗi ngôn ngữ
  của model thành lỗi của vai advisor**. Bài học: khi một hàm trả `None` vì nhiều lý do
  khác hẳn nhau, chỗ đo phải phân biệt được chúng — nếu không, cái rào chắn mình vừa dựng
  sẽ tự kéo tụt điểm chính nó.
- **Hai bench live chạy song song suốt 19 phút mà tôi tưởng chỉ có một.** Lần relaunch
  trước, tôi đọc kết quả của task **gốc** rồi kết luận tiến trình relaunch (pid 6579) đã
  xong; thực ra nó vẫn chạy. Khi khởi động lượt mới thành ra hai tiến trình tranh cùng
  model, latency của cả hai đều bẩn. `ps -o lstart,etime` mới lộ ra. Đã bỏ cả hai, chạy
  lại sạch. Bài học: "task báo completed" chứng minh **task đó** xong, không chứng minh
  **tiến trình mình đẻ ra sau đó** xong — muốn biết tiến trình còn sống thì phải hỏi
  tiến trình.
- **`zsh script.sh` với script bash làm hỏng `BASH_SOURCE`.** `cold-start-smoke.sh` báo
  "uv build hỏng" — nghe như lỗi dựng wheel thật, hoá ra là `BASH_SOURCE[0]: parameter not
  set` ở dòng 16 vì chạy sai shell. Chạy `bash` như CI vẫn chạy thì 6/6. Một thông báo lỗi
  ở bước 1 không có nghĩa bước 1 là chỗ hỏng.
- **Log đứng im 36 phút không đồng nghĩa treo.** Bench ngưng ghi từ 15:19 tới 16:12; kiểm
  `ps` thấy CPU time vẫn tăng (42s→52s) và còn socket TCP mở ⇒ đang stream chậm chứ không
  chết. Cơ chế chống stall của client chặn theo **thời gian rảnh** (120s×2), không chặn
  theo tổng thời gian, nên một câu trả lời chậm không bao giờ bị bỏ.

## Mở / sang sau

- `reliability_baseline_0.15.0.json` giờ đã cũ 4 bản; trục judge mù vẫn chưa đủ n≥3.
- Bộ live đầy đủ của vòng này chạy trên cây template-skills, không phải trên đúng commit
  tag (các commit sau đó không chạm đường live nào) — lần sau nên xếp lịch 3h cho đúng cây.
- Giới hạn đã biết vẫn còn: worker tầng tool có thể chia việc cho peer không có tool.
