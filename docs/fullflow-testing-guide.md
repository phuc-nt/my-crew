# Full-flow Testing Guide — `tests/fullflow/`

> Cơ chế test **toàn pipeline** trong repo: chat (Telegram/Slack/... sau này) chỉ là lớp
> vỏ; test mô phỏng trigger ở đúng seam đó và chạy **thật** mọi thứ phía trong — intent
> routing → decompose → confirm → team tick → step worker → self-check → peer review →
> delivery → mirror → reflection. Zero mạng, zero subprocess, ~1s cho cả bộ.
> Bổ trợ (không thay thế) UAT sống trong `docs/uat-theo-user-story.md`.

## 1. Chạy

```bash
uv run python -m pytest tests/fullflow/ -q          # cả bộ
uv run python -m pytest tests/fullflow/ -q -k stall # một scenario
```

Mỗi scenario **luôn** ghi trace khi teardown (pass hay fail):
`{tmp_path}/fullflow-trace.jsonl` — pytest in đường dẫn ở dòng `[fullflow trace] ...`
(hiện với `-s`, hoặc tự động trong report khi fail).

## 2. Kiến trúc — đúng 2 biên bị thay, còn lại là code thật

| Biên | Thay bằng | Vì sao vẫn "như thật" |
|---|---|---|
| `LlmClient.complete` | `ScriptedLlm` (patch class-level) | Mọi call site (intent, decompose, step, review, util) đi qua đúng 1 choke point; rule route theo `role` + marker trong prompt |
| `telegram_write.api_call` | Outbox capture | Đây là seam urllib duy nhất — gateway thật (dedup, rate-limit, allowlist, truncation) vẫn chạy đủ |

Wiring (không phải logic): `team_tick_runner._make_spawn_step` → gọi `worker.main(argv)`
**đồng bộ in-process** với đúng argv daemon dựng, trả pid chết (worker đã chạy xong —
trung thực với cái ticker thấy). `load_company`/`load_registry`/`load_profile` resolve về
cast của harness ở mọi import site (`_patch_everywhere` — match theo object identity).

Files:

| File | Vai trò |
|---|---|
| `harness.py` | `FullFlowHarness`: cài patch, `trigger()`, `pump()`, `answer_clarify()`, inspectors, trace |
| `scripted_llm.py` | `LlmRule` + `ScriptedLlm` — **fail loud**: call không khớp rule nào → AssertionError kèm role + 600 ký tự đầu prompt |
| `cast.py` | Công ty tí hon: `admin` (ops gateway của CEO), `coordinator` (chạy tick, share bot send-only), 3 worker |
| `scenario_rules.py` | Building block rule theo từng hop pipeline |
| `conftest.py` | Fixture `fullflow` (builder) + luôn ghi trace ở teardown |
| `test_fullflow_team_task.py` | Scenario giao việc đội (DAG nhiều người) |
| `test_fullflow_clarify.py` | Scenario hỏi CEO giữa chừng, không chặn bước |
| `test_fullflow_autopilot.py` | Scenario autopilot tự gỡ việc kẹt, có trần |
| `test_fullflow_sprint.py` | Scenario sprint — một người làm trọn |

## 3. Viết scenario mới

Khung chuẩn — mọi bước tiến đều qua **chat trigger** hoặc **pump nhịp daemon**, không
gọi tay hàm nội bộ:

```python
def test_my_scenario(fullflow):
    h = fullflow(rules=[...])            # kịch bản LLM (mục 3.2)
    h.trigger("Nhờ đội làm X nhé")       # CEO nhắn — qua answer_mention thật
    h.trigger("ok")                       # CEO confirm draft
    h.pump(8)                             # 8 "phút" daemon: team-tick + mirror
    # assert trên cái CEO thấy: h.sent_texts(), h.task_rows(), h.step_rows(id)
```

### 3.1 API harness

| Hàm | Ý nghĩa |
|---|---|
| `trigger(text, user=, ts=)` | 1 tin nhắn CEO qua seam mention thật; trả text reply mới nhất ("" nếu im). `ts=` để phát lại cùng tin (test dedup) |
| `pump(n)` | n vòng nhịp daemon: `run_team_tick(coordinator)` + `run_milestone_mirror(admin)`; step chạy đồng bộ bên trong |
| `answer_clarify(answer)` | Trả lời clarify mới nhất qua đúng đường button (`apply_answer`) |
| `sent_texts()` / `last_message_text()` | Những gì "điện thoại CEO" nhận |
| `task_rows()` / `step_rows(task_id)` | Trạng thái store thật (status, delivery_status, step_type...) |
| `llm.add_rules(*rules)` | Thêm rule giữa chừng scenario |

### 3.2 Kịch bản LLM — building blocks (`scenario_rules.py`)

Rule khớp theo `role` + marker substring; **rule cụ thể đặt trước, catch-all đặt cuối**.

| Helper | Role | Marker | Hop |
|---|---|---|---|
| `intent_assign_team_task()` | plan | `DANH SÁCH LỆNH` | Phân loại ops intent, echo brief |
| `decompose(steps, title=, pic_id=)` | plan | `bộ phân rã công việc` | DAG proposal — qua validator thật |
| `propose_ask_ceo(question, options, once=)` | plan | `Đồng nghiệp có thể hỏi` | Bước quyết định hỏi CEO → mint clarify |
| `propose_no_consult()` | plan | `Đồng nghiệp có thể hỏi` | Bước tự lo, không hỏi ai — đặt SAU `propose_ask_ceo` |
| `sprint_intake(goal, assigned_to=)` | plan | `bộ tiếp nhận việc` | Tiếp nhận việc chế độ sprint |
| `step_work(title_marker, text)` | content | title bước | Nội dung 1 bước |
| `self_check_pass()` | review | `"confidence"` | Self-check (prompt duy nhất hỏi confidence) |
| `peer_review(passed, failures, once=)` | review | "" | Soát chéo — đặt SAU self_check_pass |
| `utility_rules()` | util | — | Reflection + memory extraction sau delivery (bắt buộc có) |
| `catch_all_content(text)` | content | "" | Summary/room message phụ — đặt CUỐI |

Mô phỏng vòng lặp (fail → rework → pass): dùng `once=True` —
`peer_review(False, ["..."], once=True)` rồi `peer_review(True)`.

**Va chạm marker — bẫy nguy hiểm nhất.** Ba prompt khác nhau cùng mang `role="plan"`
(decompose, propose consult trước bước, sprint intake) và cả ba đều render khối nhân sự
có nhãn "danh sách nhân sự". Key rule vào nhãn dùng chung đó thì rule đầu tiên nuốt hết
call của hai hop kia — mà propose lại **degrade âm thầm** thành `[]` khi parse hỏng, nên
scenario vẫn xanh trong khi một nửa pipeline không hề được kịch bản hoá. Luôn key vào
câu mở đầu **riêng** của từng prompt (xem cột Marker ở bảng trên) và script rõ ràng cả
hop propose (`propose_no_consult()`) thay vì để nó rơi vào degrade.

### 3.3 Bẫy contract thật (validator sẽ chặn — đây là feature)

- `decompose` **bắt buộc** `pic_id` top-level, và **bước chốt (cuối) phải do PIC đảm
  nhận** — helper mặc định lấy assignee của bước cuối làm PIC.
- Step fields: `step_id, title, assigned_to, deps, acceptance, needs_review`;
  `step_type` chỉ được `"work"` khi decompose (review/rework do ticker mint).
- **Waiver việc nhỏ**: ≤3 bước toàn nội bộ → KHÔNG mint peer review
  (`SMALL_TASK_MAX_STEPS`). Muốn ép có review: đặt `"external_write": True` ở một bước.
- Trần soát chéo: `MAX_REVIEW_ROUNDS = 2` (`review_insert.py`) — trượt hết →
  `stalled` + đúng 1 escalate "cần CEO xem lại".
- Coordinator trong cast **phải có** telegram block (send-only): fast path
  "✅ HOÀN THÀNH" + escalate resolve telegram từ profile của tick.
- Decompose có retry budget thật (4); trượt hết sẽ fallback sprint —
  nếu scenario "tự nhiên" rơi vào sprint, kiểm tra lại payload decompose.
- **Bật autopilot là bật luôn tự-xác-nhận** (`ops_assign_team_task`: `autopilot_enabled()`
  ⇒ auto-confirm — thiết kế v63). Scenario `autopilot=True` **không được** gõ "ok": tin đó
  bị hiểu là brief MỚI và đẻ thêm task sprint thứ hai.
- **Sprint không dùng `step_type="work"`**: bước làm là `step_type="sprint"`
  (`step_id="sprint"`), bước soát là `sprint-review-0-0`. Sprint luôn mint soát chéo bất
  kể band tin cậy.
- `classify_brief` là **code thuần, mặc định chọn sprint**; chỉ rẽ sang đội khi brief
  >1200 ký tự, >10 thực thể, quá nhiều yêu cầu rời, hoặc bị từ chối vì an toàn. Muốn
  scenario đi đường đội thì brief phải đủ tín hiệu.
- `sprint_intake` **fail-open** ở product: intake hỏng vẫn ra kế hoạch tối thiểu từ brief
  của CEO. Nghĩa là thiếu rule ở đây degrade âm thầm chứ không fail loud — luôn script.
- Trường của `Clarification` là **`id`**, không phải `clarify_id`.

## 4. Truy vết khi scenario đỏ

1. **ScriptedLlm fail loud** — lỗi thường gặp nhất: AssertionError `llm_unmatched` kèm
   `role` + đầu prompt → cho biết chính xác hop nào thiếu rule (hoặc product đổi
   contract prompt — regression thật).
2. **Trace JSONL** — đọc tuần tự: `trigger` → `llm_*` → `spawn_step`/`step_worker_exit`
   → `telegram_api` (method, chat_id, text head) → `tick_result` → `tasks_snapshot`.
   Hop nào thiếu = pipeline dừng ở đó.
3. **Store** — `task_rows()`/`step_rows()` in vào assertion message sẵn; status
   `stalled`/`pending` + step nào kẹt chỉ thẳng nguyên nhân.

## 5. Phạm vi & vòng 2

Đã phủ (8 scenario):

- **Đội (`test_fullflow_team_task.py`)** — happy DAG + review ép bởi `external_write` ·
  waiver việc nhỏ nội bộ · fail→rework→pass · exhausted→stall→escalate đúng 1 lần rồi im
  (chống flood) · dedup trigger phát lại cùng `ts`.
- **Clarify (`test_fullflow_clarify.py`)** — bước hỏi CEO kèm nút bấm, hỏi mà KHÔNG chặn
  (không stall), CEO bấm nút xong việc về đích, giao đúng 1 lần.
- **Autopilot (`test_fullflow_autopilot.py`)** — reviewer trượt mọi vòng, autopilot tự
  leo thang trong trần (`MAX_AUTOPILOT_ATTEMPTS`), không kẹt vĩnh viễn và không flood khi
  cạn lượt.
- **Sprint (`test_fullflow_sprint.py`)** — brief đơn giản đi đường một người làm trọn,
  đúng 1 bước `sprint` + 1 bước soát, delivered một lần.

Còn để mở: transport khác Telegram (chỉ cần thêm capture seam tương ứng, phần trong giữ
nguyên) · kịch bản nhiều task chạy song song tranh nhau một tick.

**Kiểm chứng bộ test có răng.** Đã chạy mutation thủ công: nới `MAX_REVIEW_ROUNDS` 2→99
làm đỏ đúng 2 scenario phụ thuộc trần soát (stall/escalate + autopilot), 6 scenario còn
lại vẫn xanh. Khi sửa harness hoặc thêm scenario, lặp lại một mutation tương tự — bộ test
xanh 100% mà không đỏ khi đảo invariant thì nó chỉ đang xác nhận chính nó.
