# v62 — English hoá toàn bộ định danh (template + fleet + key backend)
2026-08-04 · hoàn thành

## Làm gì

- Template sản phẩm đổi id English: `coordinator`/`researcher`/`content`/`analyst`/`qa`
  (dirs + crew.yaml + skill file `research-with-cited-sources.md`); role hiển thị
  ("Nghiên cứu"…) giữ Việt.
- Key backend còn sót đổi English: snapshot personal-pack `current_time`/`weekday`/
  `calendar_next_24h`/`unread_email` (+ `note`), helper `_time_of_day_vi`. Quét
  heuristic toàn my_crew + domain-packs: 0 định danh tiếng Việt còn lại.
- Migration fleet máy thật (script idempotent, service dừng hẳn bằng `launchctl
  bootout` — `stop` bị KeepAlive respawn): rename 7 cặp `profiles/<id>` +
  `.data/agents/<id>`, registry.yaml, company.yaml::coordinator_id, refs trong
  profile.yaml/MEMORY.md, UPDATE 128 hàng team-task store (pic_id/assigned_to/
  assigned_by). Điều kiện an toàn kiểm trước: 0 task dispatchable (assigned_to nằm
  trong plan_hash — chỉ được đổi khi không còn task sống).
- Tests: 20 file đổi fixture id; docs sống (6 file) đổi id; journals giữ nguyên (lịch sử).

## Quyết định & vì sao

| Quyết định | Vì sao | Trade-off |
|---|---|---|
| kiem-dinh → `qa`, noi-dung → `content` | Id ngắn, chuẩn ngành | Mất nghĩa "kiểm định" trong id — bù bằng role name Việt |
| UPDATE cả store lịch sử | Board/history/search nhất quán một bộ id | plan_hash các task cũ lệch — vô hại vì chỉ verify khi dispatch, mọi task đã terminal |
| Journals không sửa | Nhật ký là lịch sử — id cũ đúng tại thời điểm đó | Grep id cũ vẫn ra hits trong docs/journals |

## Vấp & học được

- `launchctl stop` không dừng được service KeepAlive (respawn ngay, đổi PID) — phải
  `bootout` rồi `bootstrap` lại. Kiểm PID sau lệnh, đừng tin exit code.
- `assigned_to` nằm trong plan_hash: mọi migration đổi id phải kiểm "0 task
  dispatchable" trước khi UPDATE — không kiểm là ticker stall hàng loạt vì hash lệch.

## Mở / sang sau

- Backlog giữ nguyên: Postgres cross-agent memory · nhắc-việc-theo-giờ · cân chỉnh
  review theo cỡ việc · task stalled `9ee8a4f028f0` chờ CEO.
