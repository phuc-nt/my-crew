# v70 — Trợ lý cá nhân `pong` (thay OpenClaw personal assistant)
2026-08-05 · ✅ Done — UAT sống, DM thật cả 2 kind

## Làm gì
- Dựng agent thứ hai trên `personal-pack`: `pong`, bot Telegram riêng, không đụng
  `secretary` đang test. Thay 3 job còn sống của OpenClaw — Morning Briefing (7:00),
  Weekly Review (CN 8:00), memory qua daily-notes SQLite sẵn có.
- Nguồn snapshot mới ở tầng pack (cả 2 agent cùng hưởng): `tasks_pending` +
  `tasks_completed` trong `my_crew/tools/gws_read.py`, và `my_crew/tools/goodreads_read.py`
  — RSS kệ sách công khai, stdlib thuần, không key mới.
- `PersonalToolProvider.read` thành **kind-aware**: mọi kind lấy dải ngày (7 nguồn),
  riêng `weekly-review` cộng dải 7 ngày (11 nguồn) — lịch tuần, việc đã xong, sách đọc
  trong tuần, bài học phản tư v69.
- `goodreads_user_id` là field profile mới (`reporting_config.py` + `loader_mapping.py`),
  **cố ý không có env fallback**.

## Quyết định & vì sao
| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| Chỉ hồi sinh 3 job còn sống, bỏ 8 job chết từ tháng 3–5 | Job chết = chưa từng có ai thiếu nó | Muốn lại phải dựng tay |
| Agent mới + bot mới thay vì thêm kind cho `secretary` | `secretary` đang UAT, briefing 7:00 hằng ngày sẽ nhiễu | 2 profile phải bảo trì |
| Nguồn mới đặt ở pack, không ở profile pong | `secretary` cùng pack cũng cần lịch/việc/sách | Đường đọc chung phải degrade-soft tuyệt đối |
| `goodreads_user_id` profile-only, không env | Kệ sách của MỘT người; env là fleet-wide ⇒ đặt biến là `secretary` âm thầm đọc kệ CEO | Muốn dùng phải sửa profile, không set biến nhanh được |
| `integrations:` KHÔNG dùng cho key này | Builder ép block đó thành `McpServerSpec`; entry lạ **biến mất im lặng** | Field phẳng ở top-level, hơi lệch nhóm |

## Vấp & học được
- Thiết kế ban đầu định nhét `goodreads_user_id` vào `integrations:`. Sai: block đó
  coerce sang typed spec, key không map trong `build_reporting_dict` thì **không bao giờ**
  tới config — hỏng không kêu. Đọc đường config layering trước khi chọn chỗ đặt field.
- `tasks_list` không khai `maxResults` trong khi mọi helper gws khác đều có trần. Lọc
  `completed` chạy SAU khi API cắt trang ⇒ danh sách bận sẽ đẩy hết việc đã xong khỏi
  trang đầu và weekly báo "(không có)" — **sai im lặng, không phải lỗi**. Latent vì CEO
  đang có 7 task. Thêm `_TASK_PAGE = 100` cả 2 đường đọc.
- Đo thật thay vì tin diff: weekly snapshot 5470/6000 ký tự, riêng `unread_email` chiếm
  4248 (78%). `render_snapshot` cắt phẳng theo vị trí ⇒ nhóm tuần đứng sau sẽ mất trước.
  Đưa hộp thư xuống CUỐI: mất đuôi danh sách email (thừa sẵn) chứ không mất trọn weekly.
- `git checkout -- <file>` lên file có thay đổi CHƯA commit = xoá sạch phần chưa commit.
  Mất `tools.py` v70 sau một lệnh undo mutation-test. Khôi phục được, nhưng bài học:
  copy ra scratchpad trước khi cố tình làm hỏng file để test.
- Test "briefing không trả giá nhóm tuần" ban đầu chỉ chứng minh key vắng mặt — chưa
  phải khẳng định về CHI PHÍ. Nâng lên đếm-lượt-gọi; mutation-test xác nhận bản cũ cho
  lọt mutant "gọi rồi vứt kết quả".
- **UAT sống bắt lỗi 2802 test xanh không thấy** (lại đúng bài học v66 "wired ≠ có điện"):
  weekly viết "Nguồn chưa nối: Goodreads" trong khi `goodreads_activity_7d` đang cầm sách
  thật, lại bịa thêm GitHub/LinkedIn/Substack — vốn chỉ là NGƯỜI GỬI trong hộp thư. Prompt
  bắt viết dòng "nguồn chưa nối" mà không định nghĩa thế nào là chưa nối ⇒ model tự đoán.
  Sửa cả 2 prompt: chỉ gọi tên key mang đúng "(chưa cấu hình)"/"(chưa đọc được: …)", key có
  nội dung thật là ĐÃ nối, cấm suy nguồn từ tên người gửi, không có thì bỏ hẳn dòng. Đúng
  lớp honest-drop v64: snapshot đúng nhưng bản tin nói sai — chỉ đọc NỘI DUNG mới bắt được.
- Quét bí mật sau commit bắt được **id Goodreads thật của CEO hardcode 16 chỗ** trong 2
  file test. Repo PUBLIC + ship PyPI ⇒ dữ liệu cá nhân bị phát tán, dù chỉ là fixture.
  Mọi test đều stub `urlopen` nên id thật không làm gì — thay bằng id giả. Bài học: quét
  bí mật phải soi cả **giá trị nhận-dạng-người**, không riêng token/khoá; và quét trước
  khi commit chứ không phải trước khi push.

## Mở / sang sau
- Telegram cấm bot mở hội thoại trước: `chat_id` chỉ tồn tại sau khi user nhắn bot lần
  đầu, trước đó API trả `chat not found` — ràng buộc nền tảng, không vá bằng code. CEO
  `/start` xong là thông ngay, KHÔNG cần restart daemon (registry đọc lại mỗi tick,
  `.env` mỗi worker). Chạy thật: briefing $0.0024, weekly $0.0014.
- `_recent_lessons` đọc namespace memory của **coordinator**, không phải của agent cá
  nhân — an toàn với fleet một chủ, nhưng đây là chỗ duy nhất v70 nới tầm nhìn của pack.
- `tasks_pending` chỉ đọc tasklist `@default`; tasklist thứ hai sẽ hỏng đúng kiểu im
  lặng như H1.
