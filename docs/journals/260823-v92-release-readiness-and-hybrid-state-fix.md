# v92 — Vòng sẵn sàng release: 3 phát hiện ops + bug hybrid-state
2026-08-23 · ✅ Done — cắt v0.13.0

## Làm gì
- Sửa 3 phát hiện từ UAT ops-chat live: history search rơi hết kết quả khi câu hỏi
  nhiều từ (thêm fallback khớp-bất-kỳ-từ, gắn cờ "kết quả gần đúng"), sửa PIC trỏ vào
  bước đã kết thúc ngay trong code, báo tuổi stall.
- Truy ra + sửa **bug hybrid-state**: task `stalled` giữ bước `pending` mà không lệnh
  cứu nào gỡ được. `_retry` gọi `reset_step_to_pending` (xoá attempt_id), rồi `_give_up`
  cùng chuỗi quyết định vẫn guard theo lease cũ → UPDATE khớp 0 dòng → biến mất im lặng.
  `retry_stalled_step` không cứu nổi (`_dead_steps` chỉ nhận `failed`/`timeout`), chỉ
  còn đường cancel.
- Làm mọi ghi terminal (`mark_done`/`mark_failed`/`mark_needs_decision`/`mark_timeout`)
  đi qua `_terminal_write` chung: no-op giờ có WARNING thay vì nuốt boolean như trước.
- Khôi phục cổng typecheck FE: `tsc --noEmit` đọc `tsconfig.json` rỗng nên không kiểm
  gì cả, trong khi `tsc -b` (thứ build thật chạy) đỏ 15 lỗi. Sửa hết 15 + rebuild dist
  đã trôi sau 38 file `web/src`.
- Full-flow LIVE dữ liệu thật, LLM thật, qua `POST /api/ops/chat`: giao việc →
  decompose → tự xác nhận → spawn → stuck → retry-with-guidance → reassign researcher →
  done → review vòng 0 (trượt) → rework → review vòng 1 (đạt) → task `done`.

## Quyết định & vì sao
| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| `_give_up` sửa lỗi bằng `mark_failed_if_pending` (không guard attempt) | Dòng đã được RELEASE thì không có worker nào để bảo vệ; `only_if_status="pending"` lo tính nguyên tử thay guard | Thêm 1 method vào store; phải hiểu rõ vì sao ở đây bỏ guard là đúng |
| No-op ghi terminal thì LOG chứ không RAISE | Guard làm đúng việc (bị đặt chỗ lại) và guard bắn nhầm (snapshot cũ) nhìn từ đây giống hệt nhau | Vẫn cần người đọc log mới phát hiện |
| Thêm `quiet=True` cho đúng 1 call site | `_give_up` tự sửa được cú trượt, cảnh báo ở đó là nhiễu | Một tham số chỉ phục vụ một caller |
| Sửa test/fixture cho khớp route thật, không nới type production | 15 lỗi `tsc -b` phần lớn do mock bịa field (`count`) và thiếu field bắt buộc (`agent_id`) | Phải đọc route thật để biết shape đúng |

## Vấp & học được
- **Test double trả `None` che mất nhánh hồi phục mới**: `_Store.mark_failed` trong
  `test_reassign_respects_capability.py` không return gì → falsy → nhánh sửa lỗi bắn
  trên store giả. Double phải giữ đúng contract của thật, kể cả giá trị trả về.
- **Cổng xanh không có nghĩa là cổng có kiểm**: `--noEmit` trên root config rỗng pass
  suốt trong khi build đỏ. CI không cài wheel nên bundle cũ cũng lọt. Đo cổng bằng cách
  cố tình làm nó đỏ, đừng tin nó xanh.
- **Giao việc live mới lộ đúng đường code vừa sửa**: task thật chạy trúng nhánh
  needs_decision → retry → reassign, `intervention_count=2`, đúng vùng bug. Không log
  WARNING nào bắn — hành vi khớp thiết kế.
- Agent trả kết quả trung thực khi thiếu dữ liệu (từ chối bịa severity/owner) và QA
  đánh trượt vòng 0 đúng lý do; vòng rework mới có nội dung truy được nguồn thật.

## Mở / sang sau
- Service đang chạy là bản cài cũ, chưa mang bản vá; cần restart sau khi release.
- SMTP chưa cấu hình và chưa có kênh operator ngoài Telegram — lựa chọn cấu hình,
  không phải blocker.
