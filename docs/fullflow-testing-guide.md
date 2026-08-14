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
| `test_fullflow_team_task.py` | Bộ scenario giao việc đội |

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
| `decompose(steps, title=, pic_id=)` | plan | `danh sách nhân sự` | DAG proposal — qua validator thật |
| `step_work(title_marker, text)` | content | title bước | Nội dung 1 bước |
| `self_check_pass()` | review | `"confidence"` | Self-check (prompt duy nhất hỏi confidence) |
| `peer_review(passed, failures, once=)` | review | "" | Soát chéo — đặt SAU self_check_pass |
| `utility_rules()` | util | — | Reflection + memory extraction sau delivery (bắt buộc có) |
| `catch_all_content(text)` | content | "" | Summary/room message phụ — đặt CUỐI |

Mô phỏng vòng lặp (fail → rework → pass): dùng `once=True` —
`peer_review(False, ["..."], once=True)` rồi `peer_review(True)`.

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

Đã phủ (5 scenario): happy DAG + review ép bởi external_write · waiver nội bộ ·
fail→rework→pass · exhausted→stall→escalate đúng 1 lần rồi im (chống flood) ·
dedup trigger phát lại cùng `ts`.

Chưa phủ (vòng 2, ghi ở `plans/260814-1138-full-flow-test-harness/plan.md`):
scenario clarify (contract `propose_consults`→`ask_ceo` — helper `answer_clarify` đã
sẵn) · scenario sprint (`sprint_intake`/`sprint_runner`) · transport khác Telegram khi
có (chỉ cần thêm capture seam tương ứng, phần còn lại giữ nguyên).
