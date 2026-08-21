# v91 — UX real-use journeys: sửa cold-start + nút-hoá ops sẵn có
2026-08-20 · 🟡 In progress (P6 live-UAT còn cần người) · chưa release

## Làm gì

- **P1 cold-start integrity** — 4 dead-end bịt lại: wizard không còn brick khi thiếu
  bước, đường không-mật-khẩu render sạch (auth OFF tới khi có `WEB_AUTH_PASSWORD_HASH`),
  dry-run không còn bẫy im lặng, và thông báo "restart" không nói dối về cơ chế thật.
- **P2 dry-run visibility** — trạng thái dry-run hiện rõ + điều khiển được từ web, không
  phải sửa env tay.
- **P3 one-click unstick + task control** — `routes_team_task_actions.py` mới: gỡ kẹt,
  hủy task thành REST; FE nút "Giao lại việc này" từ trang chi tiết task.
- **P4 agent config forms** — `profile_patch.py` mới (ruamel round-trip, whitelist khối,
  atomic temp+os.replace) + `routes_agent_profile_settings.py`/`routes_agent_safety.py`;
  sửa profile.yaml qua form giữ nguyên comment + key viết tay, không rebuild-from-dict.
  `webhook_url_guard.py` chặn URL webhook rác.
- **P5 assign + manage quick wins** — seed brief giao-lại (router state, one-shot clear),
  edit-request client-side (không cần confirm API), command-seed + context chip trong
  assistant thread, toggle autopilot + ô concurrency trong tab Cài đặt.

## Quyết định & vì sao

| Quyết định | Vì sao | Trade-off |
|---|---|---|
| `save_company` chuyển sang ruamel round-trip (P5-D0) | Bản cũ rebuild từ dict 6-key cứng → nuốt mọi key/comment viết tay (đúng lớp sự cố `profile_patch` sinh ra để tránh) | Drift mỹ phẩm ở indent list/spacing comment; giá trị byte-an-toàn |
| Thêm ruamel.yaml (giữ comment) thay PyYAML cho write path | PyYAML dump mất comment + đảo key-order | 1 dep nữa; chỉ dùng ở write, đọc vẫn safe_load |
| Autopilot ghi thẳng qua `save_company` ở route Settings | `run_set_autopilot` (chat-ops) cũng chỉ load+save không audit riêng → tương đương hành vi | Không có event audit riêng cho toggle (đã có ở chat-ops path) |
| Giao-lại = hủy + seed brief mới, KHÔNG endpoint refine | Red-team cắt `POST /api/office/assign/refine`; seed qua router state tránh giới hạn URL | Mất "sửa tại chỗ" server-side; bù bằng edit-request client |

## Vấp & học được

- **Cook không tự chạy được live-UAT.** Bước 2/3/4 (wizard thật trên browser, bind bot
  Telegram thật + chào, gửi dry-run-off thật) cần OpenRouter key + Telegram token + trình
  duyệt — controller không có. Không bịa pass; tách phần tự động (gate, doctor, docs,
  cold-start smoke đều xanh) khỏi phần chỉ người làm được, rồi bàn giao đúng 1 handoff.
- **Bẫy CWD của Bash** — một `cd web` từ lượt trước dính lại khiến lệnh `python3`/`ruff`
  path tương đối nổ; luôn `cd <repo> && …` hoặc path tuyệt đối.
- **e2e cold-start "2 failed"** không phải regression — `playwright.cold-start.config.ts`
  không có `webServer`; phải chạy `scripts/cold-start-smoke.sh --browser` để dựng wheel +
  serve. Sau đó xanh hết.
- **Review P3→P5 một lượt (6 cụm, verify đối kháng) ra 4 lỗi thật, 0 bị bác.** Nặng nhất:
  nút gỡ-kẹt/hủy ở trang chi tiết task invalidate thiếu `artifacts.room` → bấm xong màn
  đứng im tới lúc remount (board card không dính vì đọc `tasks.board`). Còn lại: retry
  đua ghi trùng step_id → 500 thay vì 409; `profile_patch` temp cố định thiếu PID; preview
  giao-trong-phòng thiếu `pic_dry_run`. Sửa hết + thêm test hồi quy.
- **Thêm test làm lộ bug cô-lập test có sẵn.** +130 test đổi thứ tự suite khiến
  `test_push_no_operator_is_noop` lật: route Connections gọi `load_dotenv(override=True)`
  rò `OPERATOR_EMAIL`/`OPERATOR_WEBHOOK_URL` vào `os.environ` thật, mà `channels_for` đọc
  đúng 2 env đó. Fix ở fixture (snapshot+restore), không phải ở logic diff.

## Mở / sang sau

- **Live-UAT (P6) cần người:** chạy bước 2/3/4 với key/bot/trình-duyệt của CEO rồi tick nốt.
- 1 test đỏ tồn từ trước: `deepagents` (extra `deep` EXPERIMENTAL) vắng khỏi venv — không
  liên quan diff, giống lần "deep extra biến mất" ở v56. Cài lại extra nếu muốn xanh tuyệt đối.
