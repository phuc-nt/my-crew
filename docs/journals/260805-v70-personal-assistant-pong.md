# v70 — Trợ lý cá nhân `pong` (thay OpenClaw personal assistant)
2026-08-05 · ✅ Done (chờ 1 thao tác người: `/start` bot mới)

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
- Quét bí mật sau commit bắt được **id Goodreads thật của CEO hardcode 16 chỗ** trong 2
  file test. Repo PUBLIC + ship PyPI ⇒ dữ liệu cá nhân bị phát tán, dù chỉ là fixture.
  Mọi test đều stub `urlopen` nên id thật không làm gì — thay bằng id giả. Bài học: quét
  bí mật phải soi cả **giá trị nhận-dạng-người**, không riêng token/khoá; và quét trước
  khi commit chứ không phải trước khi push.

## Mở / sang sau
- **Chặn 1 bước người:** Telegram cấm bot mở hội thoại trước; `chat_id` chỉ tồn tại sau
  khi user nhắn bot lần đầu. Đến khi CEO `/start` bot mới, API trả `chat not found` —
  không vá bằng code được. Không cần restart daemon (registry đọc lại mỗi tick, `.env`
  đọc lại mỗi worker).
- `_recent_lessons` đọc namespace memory của **coordinator**, không phải của agent cá
  nhân — an toàn với fleet một chủ, nhưng đây là chỗ duy nhất v70 nới tầm nhìn của pack.
- `tasks_pending` chỉ đọc tasklist `@default`; tasklist thứ hai sẽ hỏng đúng kiểu im
  lặng như H1.
