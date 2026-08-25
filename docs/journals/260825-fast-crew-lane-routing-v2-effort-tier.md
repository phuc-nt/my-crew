# Fast/crew lane routing v2 — effort tier + hai lỗ chèn lệnh bậc hai
2026-08-25 · ✅ Phase 1-3 done (plan 6 phase, còn 4-6)

## Làm gì

- **Effort tier cho sprint**: `sprint_intake` chấm độ khó bản chất của việc — `low`/`medium`/`high` — ngay trong lượt gọi intake đã có sẵn, nên tốn 0 lượt gọi model thêm. Ba bậc chứ không bốn; phân vân thì chọn bậc thấp hơn.
- **Chỉ `low` đổi hành vi**: model role mới `sprint_low`, budget tìm kiếm cắt còn 4, tối đa 1 vòng sửa thay vì 2. `medium` là hành vi cũ nguyên vẹn và cũng là đích fail-open của mọi nhánh hỏng.
- **Bậc lưu ở `route_json`**, không phải cột mới; `route_stats` báo số việc và số bế tắc theo từng bậc. Vòng này CHỈ ĐO, effort chưa được quyền đổi lane.
- **Sửa 2 lỗ chèn lệnh bậc hai** trong đường nâng cấp sprint→team đã commit từ Phase 2, do code-reviewer bắt.
- `sprint_low` lên `MODEL_ROLES` + form web + `docs/deployment-guide.md`; chưa cấu hình thì degrade về fleet nên tính năng nằm im cho tới khi có người bật.

## Quyết định & vì sao

| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| Bậc vào `route_json`, không thành cột `team_steps` | Bản ghi định tuyến vốn là dữ liệu quan sát của chính lượt đó, lại nằm cùng chỗ giữ kết cục task — "đề chấm khó bế tắc bao nhiêu %" đọc được ngay | JSON tự do, không có ràng buộc lược đồ |
| 3 bậc, không 4 | Model nhẹ chấm 3 lớp đáng tin hơn hẳn; bậc thứ 4 không mở thêm hành động nào | Ít độ phân giải hơn |
| `medium` = mặc định của `SprintPlan` | Mọi chỗ dựng plan không qua intake (hạ cấp từ team, test cũ) giữ nguyên hành vi mà không phải sửa gì | Tier rác im lặng thành medium, không cảnh báo |
| Sửa cắt chuỗi ở chỗ TIÊU THỤ, không chỉ chỗ dựng đề | Cắt làm hỏng khối bọc là lỗi bất kể ai viết đề; sửa ở consumer chặn cả những đường gọi chưa tồn tại | Thêm một hàm dùng chung phải nhớ gọi |
| Dấu hở ở đầu đề thì vô hiệu hoá dấu, không bỏ khối | "Bỏ cả khối" lúc khối bắt đầu ở offset 0 nghĩa là xoá sạch đề CEO — mà dấu người tự gõ thì luôn hở | Mất cấu trúc khối ở đúng ca đó |

## Vấp & học được

- **Test của chính mình bắt lỗi thật**: `effort_of_task` viết `with TeamTaskStore(...)` nhưng lớp này không phải context manager; `except Exception` fail-open nuốt luôn `TypeError`, nên tier LUÔN đọc ra `medium` — tính năng chết lâm sàng mà nhìn bên ngoài vẫn lành. Fail-open che lỗi lập trình chứ không chỉ che lỗi dữ liệu.
- **Hai lỗ chèn lệnh cùng một gốc**: khối context đi nhờ trường `brief`, mà tầng dưới coi `brief` là lời CEO tự viết — cắt 120 ký tự làm tiêu đề (chữ LLM lọt thẳng vào tin Telegram gửi CEO), cắt lại 2000 ký tự cho prompt mọi bước (lát rơi giữa khối bọc, để lại dấu mở lơ lửng). Bài học: **test bảo vệ đặt ở chỗ DỰNG không bắt được lỗi ở chỗ TIÊU THỤ**.
- **Chuỗi thù địch giấu lỗi**: dùng chuỗi chèn lệnh làm dữ liệu thử thì L2 cách ly nó thành placeholder ngắn, ngắn nên không tràn cửa sổ cắt, nên lỗi biến mất. Test phải dùng nội dung LÀNH mà DÀI.
- **Docstring nói sai hàng rào nào đang chặn**: tài liệu ghi `_already_upgraded` chặn chuỗi nâng cấp, probe cho thấy `_upgradable` chặn trước và hàm kia không bao giờ được gọi tới trên đường thường. Đã sửa tài liệu và thêm test riêng cho lớp thứ hai.
- **`hash()` trong test là nguồn bất định**: id sinh từ `hash(str)` đổi mỗi tiến trình, làm một lần chạy mutation treo 2 phút thay vì trượt ngay. Test hàng rào phải gọi thẳng cửa kiểm tra, đừng để nó rơi xuống đường chạy thật.

## Mở / sang sau

- Phase 4 (steering giữa chừng cho sprint đang chạy), Phase 5 (live fullflow suite), Phase 6 (benchmark v2) chưa bắt đầu.
- Chưa có số thật cho effort tier — cần `route_stats` trên dữ liệu chạy thật trước khi cho effort quyền đổi lane.
- Cửa sổ ghi dấu nâng cấp (`_stamp_upgrade_route` chạy sau khi task đã tồn tại) vẫn hở nếu tiến trình chết giữa chừng; hậu quả chỉ là mất một dòng đếm vì `_upgradable` mới là hàng rào thật.
