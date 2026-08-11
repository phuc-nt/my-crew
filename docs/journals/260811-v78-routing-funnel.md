# v78 — Phễu định tuyến: router không cần đúng, chỉ cần có lưới đỡ

2026-08-11 · ✅ Done

## Làm gì

- **Lật mặc định** `classify_brief`: v77 whitelist-mới-được-sprint (nghi ngờ → team),
  v78 **mặc định sprint**, chỉ đẩy team khi có tín hiệu CẤU TRÚC — >1200 ký tự,
  >10 thực thể (`_MAX_SPRINT_ENTITIES`), hoặc ≥3 đầu việc tách dòng (`_MAX_DISTINCT_ASKS`).
- **`downgrade_to_sprint`** (`agent/sprint_intake.py`): chạy SAU decompose, TRƯỚC khi
  băm/lưu. Plan suy biến (≤2 bước, 1 người, tuyến tính, không shell/ghi-ra-ngoài) →
  kéo về sprint, **0 lượt gọi model thêm**. Nghi ngờ → trả None, để team chạy.
- **Routing log**: cột `route_json` (`team_task_store`) ghi `mode`/`source`/`reason`/
  `signals` cho MỌI nhánh — prefix, refusal, heuristic, downgrade, dead_end. Chỉ số
  đo được, không chứa nguyên văn đề.
- **Dead-end nối vào log**: sprint bế tắc thì `_mark_route_dead_end` ghi đè `source`
  thành `dead_end` nhưng giữ quyết định gốc dưới `previous`.

## Quyết định & vì sao

| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| Lật mặc định sang sprint | Chi phí route sai **bất đối xứng**: sai về sprint thì dead-end kéo về sau vài phút; sai về team tốn 20m14s/$0.0757 vs 7m48s/$0.0191 CÙNG đề, chấm mù 10 vs 29, **và không ai biết** | Đề to lọt sprint sẽ mất một vòng dead-end trước khi về đúng chỗ |
| Tín hiệu cấu trúc, không phải từ khóa | Whitelist từ khóa là thứ vừa fail: đề tự nhiên ("cho tôi biết giá X, Y, Z") không chứa từ nào trong đó | Đếm dòng bullet không bắt được văn xuôi kể 3 việc trong 1 đoạn |
| Downgrade đặt SAU decompose | Kế hoạch model vừa dựng là bằng chứng mạnh hơn mọi heuristic đọc chữ — nó đã biết roster, đã chia việc | Đã tốn lượt decompose rồi mới hạ; không tiết kiệm được lượt đó |
| `route_json` chỉ lưu số, không lưu đề | Log để auto-tune ngưỡng, không phải để đọc lại nội dung | Không tra ngược được đề nào gây route sai nếu task bị xoá |
| Không backfill task cũ | Task trước v78 không có câu trả lời trung thực về "lớp nào quyết định" | `route_json` NULL trên task cũ, mọi read path phải chịu None |

## Vấp & học được

- **Test cũ đỏ vì đề cũ đổi hướng**: hai test dùng `"chuẩn bị demo cho khách hàng lớn"`
  làm đề-phải-đi-team; lật mặc định xong nó đi sprint. Phải soạn `_TEAM_SHAPED_BRIEF`
  (3 bullet) mới có đề thật sự team-shaped. Học: khi lật một mặc định, test nào dựa
  vào mặc định cũ sẽ đỏ **đúng chỗ nó nên đỏ** — đó là tín hiệu, không phải phiền toái.
- **Lớp downgrade chưa kích hoạt được trên live**: soạn đề 1335 ký tự cho việc một
  người, decompose trả 4 bước / 2 người (tách mỗi dịch vụ một bước + thêm bước `qa`
  riêng) → vượt cả `_MAX_DEGENERATE_STEPS` lẫn guard cùng-một-người. Guard từ chối là
  ĐÚNG hợp đồng, nhưng nó chỉ cứu plan đã suy biến sẵn, **không kéo ngược được plan đã
  bị thổi phồng**. Lưới đỡ còn lại cho nhóm này chỉ là ngưỡng 1200 ký tự.
- **Tải review giảm chứ không tăng**: lo mặc-định-sprint làm phình review là lo sai —
  review mint theo content step, sprint chỉ có một. Cặp benchmark v77: sprint 2 review
  vs team 6 review trên cùng đề.
- **Bất biến an toàn sống sót qua replan**: ca `sprint:` + "gửi email" kẹt giữa chừng,
  hệ tự chỉnh kế hoạch; bước ghi-ra-ngoài trong kế hoạch MỚI vẫn giữ
  `external_write=True` + `needs_review=True`. Kiểm được ở đường replan, không chỉ
  đường assign.

## Mở / sang sau

- Ngưỡng 10 thực thể vẫn là phỏng đoán: mọi cặp benchmark đã đo đều 5 thực thể.
- Ngưỡng 1200 ký tự là biến duy nhất còn kéo được cho đề dài-nhưng-một-người — cần số
  ở vùng 600–1200 trước khi đụng vào; quyết định của CEO.
- Cần ≥20 dòng `route_json` có outcome mới auto-tune được ngưỡng từ dữ liệu thật.
