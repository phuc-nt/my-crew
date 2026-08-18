# v83 — Rà "no sub-agent": benchmark live 8 run vs v0.10.0 + 9 fix từ bằng chứng sống
2026-08-17 · ✅ Done

## Làm gì
- 4 fullflow test failure-path sprint (needs_decision, give_up, delivery khi stalled) + fix ⛔ delivery-head: task stalled giờ luôn bàn giao "KHÔNG LÀM ĐƯỢC + lý do" — verify sống 2 lần (R3, R4).
- Benchmark live 8 run (7 candidate + 1 baseline) cùng brief streaming-5-dịch-vụ vs v0.10.0 (sandbox MY_CREW_HOME cô lập, blind judge v78 3 vòng đảo nhãn): báo cáo `plans/reports/benchmark-260817-0646-no-subagent-fullflow-vs-v0100-report.md`.
- Fix `_proper_noun_items`: brief prose có mệnh đề thuộc tính mang dấu phẩy + "và" không còn nuốt mất danh sách entity → prefetch fan-out 5 query/đợt thay vì 1 query kitchen-sink (verify R4, R5).
- Fix gate reassign `_can_do_step`: chỉ tin khai báo `needs_web` của bước, bỏ so năng lực người đang giữ; kèm `ops_stalled_task` rework kế thừa `needs_web`. 4 test mới.
- Fix keep-best-draft (`team_task_graph.py` self_check): theo dõi bản nháp trượt không-rỗng ít lỗi nhất, cạn budget rework thì bàn giao bản tốt nhất thay vì bản cuối — verify sống R6 ĐẠT (artifact 4.160 ký tự có giá+nguồn thay vì vỏ rỗng kiểu R4). Fix chuẩn nguồn (`react_loop.py` contract tool-loop): ưu tiên trang chính thức + domain/ngày truy cập cạnh số liệu, gate theo tool "web". 4 test mới, full BE 3374 xanh.

- Fix trượt-vì-thiếu-dữ-liệu tới được search (3 lỗi tất định từ transcript R6/R7): `build_sprint_work(retry_round=…)` nhận `intervention_count` → retry xoay query sang angle chưa gửi thay vì lặp byte-identical; `_run_rework` chạy search hook với query dựng từ danh sách failures; `step_is_toolless()` tách khỏi biểu thức inline để sprint `needs_web` giữ hook cho node rework. Kèm fix thứ 4: colon toàn chữ thường (mệnh đề thuộc tính) không còn thắng danh sách chủ thể trong prose. 8 test mới. **Verify sống R8: done + delivered, 612.9s, $0.1038, 0 can thiệp** — chấm dứt chuỗi 3/4 stall.
- Fix brief cho judge kẹt (`coordinator_nodes/stuck_decision.py`): `self_check_failures` đã được ghi vào artifact từ trước nhưng `build_stuck_brief` — chính hàm mở file đó — không đọc, nên judge phải suy ra "thiếu gì" từ bản output thô (thứ không thể cho thấy cái vắng mặt). Chèn danh sách failures vào brief. 2 test mới, full BE 3384 xanh.

## Quyết định & vì sao
| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| Judge chấm mù 3 vòng, đảo nhãn A/B | Loại hiệu ứng vị trí nhãn | 3 call LLM (~$0.053) |
| R4 stalled → chạy lại R5 cùng điều kiện thay vì kết luận ngay | Tách phương sai model khỏi lỗi code | +$0.13, +15 phút |
| Gate reassign bỏ hẳn nhánh chống-downgrade | R3 sống: step tổng hợp (không cần web) kẹt vì người giữ CÓ web → task ~90% bị kết luận thất bại | Mất lớp chặn phụ; khai báo needs_web là nguồn sự thật duy nhất |

## Vấp & học được
- Baseline v0.10.0 thắng judge **cả 3 vòng** (26 vs 19; 27 vs 21.5; 27 vs 22) — thua lặp lại ở trục nguồn: candidate deep-loop lấy nguồn thứ cấp/đại lý, baseline ra trang chủ + ngày truy cập. Gap lặp 3/3 → tật hệ thống, không phải nhiễu. Ban đầu quy cho prompt rework và đã sửa; vòng 3 cho thấy chẩn đoán đó mới đúng một nửa (xem bài học prompt-vs-năng-lực bên dưới).
- R4 lộ failure mode có sẵn: reviewer in-attempt đòi dữ liệu prefetch không có, vòng attempt không có tool search → model xóa sạch draft thành "Không có dữ liệu" → chết trước khi tới đường rework-có-search. Đo thêm R6/R7: stall kiểu này là **3/4 cùng brief** (chỉ R5 done; baseline 1/1 done) — TẦN SUẤT cao chứ không phải phương sai hiếm; `_run_rework` là call LLM trần không tool, đó là gốc.
- Gán "phương sai model" cho R4 sau đúng 1 run đối chứng (R5 done) là kết luận vội: chạy thêm R6/R7 thì ra 3/4 stall, và đào transcript thì lộ 3 lỗi code TẤT ĐỊNH (retry lặp query y hệt, rework không tool, sprint bị wire tool-less). Bài học: "chạy lại thấy pass" chứng minh được sự tồn tại của phương sai, KHÔNG chứng minh được vắng lỗi tất định — phải đọc transcript so query giữa các attempt mới thấy.
- Đọc transcript còn lộ lỗi thứ 4 không ai ngờ: title R7 dùng "trên các tiêu chí:" nên nhánh colon nuốt mất 5 chủ thể, sprint đi tìm 3 TIÊU CHÍ. Cùng ngữ nghĩa nhánh ngoặc-đơn đã encode từ trước, chỉ khác dạng viết — luật ưu tiên nên đóng theo ngữ nghĩa (chủ thể thắng thuộc tính) chứ không theo từng dạng dấu câu gặp phải.
- Sửa prompt để đòi nguồn chất lượng hơn: model tuân **đúng** (R8 tự thêm cột Chính thức/Thứ cấp) nhưng điểm nguon vẫn thua 7 vs 9. Bài học: khi model đã làm đúng thứ mình bảo mà kết quả không lên, gốc rễ nằm ở **năng lực đầu vào** chứ không phải chỉ dẫn — ở đây là snippet search không chứa số giá của trang chủ, nên "ưu tiên trang chính thức" là mệnh lệnh bất khả thi. Nhận nguồn kém một cách trung thực không ghi điểm bằng có nguồn tốt.
- Ghi "`needs_decision` thiếu `pause_reason`" vào báo cáo suốt 3 mốc mà không kiểm schema: cột đó **không tồn tại** trên `team_steps`, nó là nhãn của đường PAUSED (clarify/approval) hoàn toàn khác. Lỗi thật hẹp hơn nhiều và nằm chỗ khác: `self_check_failures` được GHI vào artifact nhưng không ai ĐỌC. Bài học: quan sát "field X rỗng" phải kiểm X có thuộc về đường code đang xét không, trước khi ghi thành việc cần fix — nếu không sẽ đi sửa đúng triệu chứng của sai bệnh.
- Suýt ghi số liệu R5 bịa vào báo cáo khi run còn đang chạy — bắt được, thay bằng placeholder rồi điền số thật sau. Report benchmark chỉ được chứa số đo thật.

## Mở / sang sau
- R8 done nhưng đi hết đường tất định (`intervention_count=0`) nên retry-rotation + rework-search **chưa từng được kích hoạt sống** — vẫn chỉ có unit test. Muốn verify phải dựng brief cố tình thiếu dữ liệu.
- Trục `nguon`: baseline thắng **3/3 vòng** (candidate 5 → 6.5 → 7, baseline 8-9). Fix chuẩn nguồn đã được model tuân (R8 tự thêm cột Độ tin cậy) nhưng không đủ thắng — nút thắt ở tầng thu thập, cần năng lực đọc trang chính thức thay vì chỉ snippet. Là thay đổi năng lực, chưa làm.
- Delivery thất-bại nên đính kèm best draft; mức watch cost theo mode; PIC sprint nondeterministic; deferred v80.
