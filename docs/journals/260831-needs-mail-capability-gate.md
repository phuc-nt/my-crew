# v92 — cờ `needs_mail`: chặn "giao việc cần tool mà người nhận không có"
2026-08-31 · hoàn thành

## Làm gì

- Mở lại quyền Google cho `secretary` (`gws_enabled` + `gws_context`) — CEO chốt, đảo
  quyết định v71 của chính CEO. Verify sống: `build_read_toolset` bind
  `['gws.calendar', 'gws.drive', 'gws.gmail']`.
- Thêm cờ thứ ba `needs_mail` trên team step, **hai cổng** như bảng mẫu đã có:
  `validate_mail_steps` (plan-time, cạnh guard shell v64) + `_can_do_step` (reassign-time,
  cạnh guard web v74).
- Ép routing: `resolve_step_runtime` giữ bước `needs_mail` **khỏi tier native**, và
  `prefetched` không huỷ được cờ (không có seam prefetch cho mail).
- Kế thừa cờ ở mọi chỗ mint dòng mới: review (`review_insert`), sub fanout
  (`fanout_insert`), rework + thay-người-chết (`ops_stalled_task`), swap khi amend.
- Persist: cột DB + migration + reader + 2 đường INSERT + `_confirmed_plan_hash`.
- Backlog: thêm mục nghiên cứu harness openhuman vào `docs/project-roadmap.md`.

## Quyết định & vì sao

| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Tên `needs_mail`, không `needs_gws` | Đề bài nói "đọc mail"; Drive/Calendar chưa có ca thật | Mở Drive/Calendar sau sẽ phải đặt tên lại hoặc thêm cờ |
| Bind hash **có điều kiện** (chỉ khi True) | Theo tiền lệ `needs_web` ⇒ mọi DAG cũ hash byte-y-hệt, không stall lúc migrate | Cờ False và cờ vắng mặt là một — không phân biệt được |
| Copy guard thứ ba, KHÔNG gộp 3 guard | 2 guard cũ **khác failure mode** cố ý (shell raise ở plan, web degrade ở reassign); gộp sẽ bẹp hành vi | Trùng lặp ~15 dòng |
| Probe KHÔNG kiểm runtime tier | Tier là thuộc tính của BƯỚC (router đã ép), không của AGENT — kiểm ở đây loại oan agent native-pinned | Khác `_web_search_enabled`, dễ tưởng là bỏ sót |
| Bật `gws_enabled` = mở lại cả quyền GHI | Không có nấc read-only; hàng rào thật nằm ở allowlist (`gmail +send`, không reply/forward) + Lớp B có audit | Bề mặt ghi rộng hơn mức CEO yêu cầu (chỉ xin đọc) |

## Vấp & học được

- **Suýt làm tính năng chết ngay từ đầu**: `resolve_step_runtime` ép bước `work` thường
  xuống native, mà native **không bao giờ** nhận `gws_context` (`team_step_runner.py:557`
  chặn `_extra` cho non-native). Không sửa router thì bước mail vẫn bị tước đúng cái tool
  nó vừa khai báo — thất bại y hệt task đã đốt $0.029. Cờ mới phải hỏi "tool này đi đường
  nào tới bước việc", không chỉ "ai được cấp quyền".
- **Đoán tên hàm private thay vì tra**: viết test gọi `_plan_hash_from_rows` — tên thật là
  `_confirmed_plan_hash`. Docstring quanh đó đủ để đoán nhầm mà vẫn thấy hợp lý.
- Mutation test 5 phát đều đỏ đúng chỗ (bỏ cờ khỏi điều kiện native, vô hiệu guard, bỏ
  emit hash, bỏ cờ khỏi restamp, bỏ cờ khỏi reader) — trong đó 2 phát cuối đỏ ở **hai dòng
  assert khác nhau** của cùng một test, tức cả hai nửa test đều chịu tải.

## Mở / sang sau

- Chưa có test E2E thật cho một bước `needs_mail` chạy hết vòng (mới có unit + routing).
- Nếu sau này cần Drive/Calendar riêng lẻ: hoặc đổi `needs_mail` thành `needs_gws`, hoặc
  thêm cờ — nên quyết trước khi có ca thật thứ hai.
- Quyền GHI gws của `secretary` giờ mở theo; nếu CEO chỉ muốn đọc thì cần nấc read-only mới.
