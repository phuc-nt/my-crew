# Review-cap salvage + verdict-lock + bench isolation
2026-08-29 · ✅ Done

## Làm gì
- Trần soát chéo (MAX_REVIEW_ROUNDS / budget task) không stall + escalate nữa: chuỗi soát kết thúc lặng lẽ (`return False`, zero side effect) và task **tự giao** — `make_aggregate` dựng header code "Soát chéo chưa đạt (đã hết lượt soát/sửa): …" nêu ý kiến reviewer còn bỏ ngỏ, trên cả 3 đường giao (fallback, direct, LLM).
- Fix verdict-None re-mint: review mint lại giờ mang `source_step_id=deps[0]` (đúng artifact vòng cũ đang chấm — content ở vòng 0, rework ở vòng ≥1), hết cảnh re-review vòng ≥1 chấm nhầm bản gốc.
- Harness fullflow patch thêm `my_crew.config.settings.DATA_DIR` — bịt leak band store thật của repo (`.data/agent_bands.sqlite3`) vào bench qua các import call-time (band_store/tick_poke/band_loop/heartbeat).
- Dọn theo review: nhánh phân loại `"stalled"` trong `_maybe_insert_review_rows` (nay bất khả đạt) bị gỡ; prompt aggregate LLM nhận thêm LƯU Ý soát trượt để body không mâu thuẫn header.

## Quyết định & vì sao
| Quyết định | Vì sao | Trade-off |
|---|---|---|
| Nhánh cap zero side effect, không reflect/escalate | Row review done bị re-inspect MỖI tick — mọi side effect sẽ lặp vô hạn; header trên bản giao là bản ghi bền | Không có notification riêng cho CEO ngoài bản giao |
| Aggregate suy cap-exhaustion từ "verdict trượt + không có rework ≥ vòng" | Dưới cap verdict trượt LUÔN mint rework → tương đương chính xác, không cần cột trạng thái mới | Reviewer xác nhận tương đương trên mọi path (kể cả drop, race) |
| Gỡ guard override_pending v63 | Không còn stall thì không còn race re-stall — guard bị subsume | — |
| Giữ nguyên nhánh escalate `review_rounds_exhausted` (dormant) | Task stalled từ trước fix vẫn cần đường ra; ngoài scope | Nợ dọn sau khi hết task legacy |

## Vấp & học được
- Test cũ pin stall nằm rải 3 tầng (unit `test_review_stall_escalate` cũ, e2e `test_rework_round_cap`, fullflow autopilot) — đổi semantics một rule ticker phải quét cả suite, không tin chạy focused; full suite bắt thêm đúng 1 file e2e sót.
- Pipe suite nền qua `tail -8` nuốt mất log — chạy nền phải ghi log đầy đủ rồi tail sau.
- LLM summarizer không thấy row review trượt → có thể viết "hoàn thành tốt đẹp" ngay dưới header trượt (review L1) — header code-built là chưa đủ, phải nhét fact vào prompt.

## Mở / sang sau
- Gap cascade (skip đầu chuỗi → bước sau thiếu input) vẫn DEFER — đo tiếp, chưa cap.
- Dọn machinery stall-review dormant (`ops_stalled_task` accept/retry review, escalate evidence) khi hết task legacy.
- Budget soát vẫn cho mint review vượt budget (chỉ chặn rework) — pre-existing, chưa sửa.

Suite: 4045 BE xanh + ruff sạch. Bench lanes10 (2 case prose ×60 tick) chạy xác nhận live.
