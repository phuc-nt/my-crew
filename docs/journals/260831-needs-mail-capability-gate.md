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
- E2E sống 2 fleet cùng 1 brief: M1 (không ai đọc được thư) + M2 (chỉ `secretary` đọc được),
  qua seam mới `seed_home(..., mail_capable={...})` trong `tests/fullflow_live/topology.py`
  (mặc định `frozenset()` ⇒ mọi ca cũ giữ nguyên fleet byte-y-hệt).

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
- **Timeout E2E: đoán sai 2 lần, mỗi lần log sửa lại.** (a) Đoán "guard ép retry nhiều vòng
  nên quá 180s" — đọc `serve.log` thì M1 chỉ retry 1, M2 retry 0 mà vẫn timeout. (b) Đoán
  tiếp "brief 6 phần quá nặng" — rút còn 3 phần, M1 vẫn timeout ở 420s với **0** retry được
  ghi. Số đo cuối mới nói đúng: M2 (kế hoạch được duyệt ngay) tốn **$0.062 cho 1 lần
  decompose** và xong gọn trong 420s; M1 buộc phải decompose ≥2 lần (bị guard chặn rồi lập
  lại) nên không thể vừa. `confirm: true` gộp preview+confirm vào **1 request đồng bộ** ⇒
  mọi lượt thử đều trả giá trước khi POST trả về; tách 2 bước cũng vô ích vì preview vẫn
  decompose y hệt. Nâng ceiling lên 900s. Bài học: đọc log lần chạy hỏng (pytest giữ 3 tmp
  home gần nhất) thay vì chạy lại bộ test tốn tiền — và đừng vá theo giả thuyết chưa đo.
- **Kiểm đột biến trên test SỐNG: hai assert của M1 không ngang nhau.** Vô hiệu
  `validate_mail_steps` rồi chạy M1 thật ($0.063, 497s): assert `claimed` (không bước nào đặt
  `needs_mail`) vẫn **XANH**, chỉ assert log đỏ. Vì không còn guard, planner ra thẳng kế hoạch
  **không có bước mail nào** — đúng cái thế giới "cờ bị xoá khỏi prompt" mà docstring cảnh báo.
  Tức `claimed` ghim BẤT BIẾN, còn assert log mới là thứ chứng minh bất biến đó **đang chịu
  tải**. Test unit offline đỏ cả 2 nhánh, nhưng chúng tiêm thẳng `capable_ids` nên không trả
  lời được câu hỏi này — chỉ ca sống mới lộ.
- **Lần chạy lại sau khi hoàn nguyên đột biến đỏ vì lý do KHÁC — và lộ bug harness thật.**
  M1 timeout 900s với `cost_usd=0`, `last=None`, nhưng đọc log ra: guard bắn đúng 1 lần,
  2 bước đều `needs_mail=0` — tức mọi assert của ca đều đã đạt. Thủ phạm là
  `is_settled`: kế hoạch ra `[step1 done, step2 waiting_clarify]`, mà luật cũ đòi **TẤT CẢ**
  bước phải parked, `done` không nằm trong `SETTLED_STEP_STATES` ⇒ task đã đứng hẳn (không
  ai trả lời CEO thì không gì nhúc nhích nữa) vẫn bị poll tới hết giờ rồi đánh trượt một ca
  đang xanh. Sửa ở predicate dùng chung: settled khi **không bước nào còn tự chạy được VÀ có
  ít nhất một bước parked** — vế sau bắt buộc, vì all-`done` phải nhường quyền quyết cho
  task state (còn aggregate/delivery chưa xong). Bản vá ngây thơ (nhét `done` vào
  `SETTLED_STEP_STATES`) bị chính test mới bắt. Pin bằng guard **offline**
  `tests/test_live_topology_settle_predicate.py` — cố ý KHÔNG đặt trong `fullflow_live/` vì
  conftest ở đó dán marker `live` + `addopts = ["-m","not live"]` ⇒ guard sẽ bị skip đúng lúc
  cần. Mutation 2 chiều, mỗi chiều đỏ ở **một assert khác nhau**.
- **M2 xanh rỗng — M1 mới là chỗ chứng minh cờ có thật.** Chạy sống: M2 (fleet có quyền)
  ra 4 bước, **không bước nào** đặt `needs_mail`; M1 (fleet không quyền) lại đặt ngay ở
  bước 1. Tức assert có điều kiện của M2 sẽ xanh cả trong thế giới `needs_mail` bị xoá khỏi
  prompt. Đã chuyển bằng chứng "cờ còn sống" sang M1: assert log có đúng câu guard từ chối —
  cái đó tất định, không phụ thuộc model chọn gì.

## Mở / sang sau

- Chưa đo được một bước `needs_mail` **chạy xong** (mở hộp thư thật, trả kết quả): E2E hiện
  dừng ở tầng lập kế hoạch + giao đúng người. Muốn đo tiếp phải có hộp thư test thật.
- Nếu sau này cần Drive/Calendar riêng lẻ: hoặc đổi `needs_mail` thành `needs_gws`, hoặc
  thêm cờ — nên quyết trước khi có ca thật thứ hai.
- Quyền GHI gws của `secretary` giờ mở theo; nếu CEO chỉ muốn đọc thì cần nấc read-only mới.
- **Lỗ phát hiện cắt cụt** (thấy khi chạy E2E, chưa vá): `ops_assign_team_task` có sẵn nhánh
  xử lý câu trả lời bị cắt — báo model "viết ngắn lại" thay vì "JSON sai" — nhưng nhánh đó
  chỉ kích hoạt khi `finish_reason == "length"` (`llm/client.py`). Chạy sống gặp ca body bị
  cắt giữa field mà KHÔNG có tín hiệu đó ⇒ rơi vào nhánh "JSON sai", model viết lại đúng cái
  kế hoạch quá dài, đốt thêm 1 lượt trong 4. Nên nhận diện cắt cụt bằng cả hình dạng body.
