# v71 — Build team nhanh: crew cá nhân + cổng `gws_enabled`
2026-08-06 · ✅ Done (còn 1 UAT giao việc chờ CEO nhắn tay)

## Làm gì
- **Đa crew manifest**: `profiles/templates/crew.yaml` (1 crew cứng) tách thành
  `profiles/templates/crews/office.yaml` + `crews/personal.yaml`. `create_crew(crew_id)`,
  `crew_preview(crew_id)`, `list_crews()` — `office` là `DEFAULT_CREW_ID` nên client
  cũ không gửi `crew_id` vẫn ra đúng đội cũ.
- **Thành viên dạng adopt**: manifest nhận cả chuỗi trơn (role == id) lẫn `{role, id}`.
  Crew cá nhân dùng dạng sau để lấy `pong` SẴN CÓ làm trợ lý — không đẻ bot thứ ba.
  5 vai: personal-assistant (pong) + coordinator + researcher + analyst + content.
- **Template `personal-assistant`** mới cho người dùng mới dựng trợ lý từ wizard.
- **Cổng `gws_enabled`** (profile-only, mặc định true): chặn CẢ đọc
  (`domain-packs/personal-pack/tools.py`) lẫn ghi (`_catalog_for_agent` trong
  `chat_command.py` loại mọi lệnh `gws_write`).
- **Bề mặt**: CLI `mpm crew init [office|personal]` + web 1-click có chip chọn crew
  (`/api/crews` mới, preview/create nhận `crew_id`).
- **`secretary` thành agent test thuần**: tắt gws, tắt schedule, cắt 3 đường ký ức.
  `pong` nhận `ops_operator_id` ⇒ chính thức là cửa giao việc cho đội.

## Quyết định & vì sao
| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| Đảo quyết định v32 "nhiều crew là YAGNI" | Yêu cầu CEO hôm nay chính là ca dùng thứ hai — YAGNI hết hiệu lực khi cái "ain't gonna need" đã tới | Thêm 1 lớp id phải validate (traversal) |
| Adopt `pong` theo id thay vì tạo role mới | Bot thứ ba = thêm token, thêm chat, CEO phải nhớ nhắn ai | Skip keyed theo AGENT id, không theo role |
| Lọc lệnh ghi ở `chat_command`, không ở `packs/registry` | Catalog pack là cấp fleet (1 object dùng chung cả domain); chỉ chỗ này mới có `config` của CHÍNH agent trong tầm | Lọc mỗi lần vào chat |
| Bỏ ở CATALOG, không chặn ở gateway | Lệnh không lọt vào prompt classifier ⇒ agent không **đề nghị** làm được, mạnh hơn là từ chối sau khi đã hứa | — |
| `gws_enabled` profile-only, không env fallback | Cùng lý do `goodreads_user_id` v70: env là fleet-wide ⇒ không thể tắt 1 agent mà không tắt cả đội | Muốn tắt phải sửa profile |
| Tắt gws vẫn GIỮ NGUYÊN key snapshot, chỉ đổi giá trị thành "(chưa cấu hình)" | Prompt phải cùng hình dạng giữa agent bật và tắt; drop key là đổi contract ngầm | — |
| `MEMORY.md` của secretary **archive, không xoá** | Dữ liệu CEO tự tay viết; thao tác phải đảo ngược được | Còn 1 file thừa trong thư mục (gitignored) |

## Vấp & học được
- **Tắt gws KHÔNG đủ để agent ngừng giữ thông tin cá nhân.** Cổng gws đã xanh, đếm
  đúng 0 lời gọi, 2812 test pass — mà bản tin vẫn đọc vanh vách deadline hợp đồng,
  sinh nhật người nhà, email của chủ nhân. Rò từ BA đường ký ức **tách rời khỏi gws**:
  `MEMORY.md` (static provider, nạp nguyên văn, **không có công tắc tắt theo agent**),
  ghi chú ngày, và recall vault kioku. Phải tắt cả ba mới sạch. Bài học: khi yêu cầu là
  "đừng giữ dữ liệu của tôi nữa", liệt kê MỌI kho agent đọc được, đừng sửa đúng cái kho
  mình vừa nghĩ ra.
- Nối tiếp v66 "đã wired ≠ có điện": test xanh + call count = 0 vẫn không chứng minh
  được gì về nội dung. Chỉ **đọc lại bản tin thật** mới bắt được. Quét 7 từ khoá nhạy
  cảm sau khi tắt: sạch cả 7; chi phí 0.0027588 → 0.0004997.
- Lại đúng bẫy config layering v70: field mới phải khai ở CẢ `loader_mapping.py` LẪN
  `build_reporting_config_from_dict` — thiếu 1 nơi thì chết im. Lần này không tin diff,
  chạy probe round-trip 3 ca (false / true / vắng key) trước khi đi tiếp.

## Mở / sang sau
- **UAT giao việc thật** còn treo: cần CEO nhắn `pong` qua Telegram giao 1 việc research
  đi hết vòng DAG. Không tự chạy thay được.
- **Đường trả kết quả team task hiện CHỈ PULL**: không path nào trong vòng đời task gọi
  `notify_operator_best_effort`, và `assigned_by` lưu chuỗi cứng `"ceo-chat"` — nhãn
  audit, không phải id định tuyến được. CEO phải tự hỏi `get_status`/`list_team_tasks`.
  Đề xuất vòng sau: cho `assigned_by` mang id định tuyến được + đẩy 1 tin khi task `done`.
- `secretary` vẫn giữ `heartbeat: 30m` — đó chính là bề mặt đang test, cố ý để lại.
