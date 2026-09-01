# Release readiness gates → cắt 0.16.0
2026-09-01 · ✅ Done 4/5 trục · trục 5 đo một phần, push chờ duyệt

## Làm gì

- **Đóng trục 4 ở live, cả hai nửa.** L2 (cap dep 8000 ký tự) xanh 2 mẫu
  ($0.006516/502.1s · $0.012265/1029.5s) sau 7 vòng; L4 (stash tool result >12k) xanh
  2 lần chạy ($0.0062/lần) với ngưỡng `TOOL_RESULT_STASH_CHARS` **giữ nguyên 12.000** —
  chuỗi dài cấp bằng fixture, không hạ ngưỡng cho dễ chạm.
- **Sản phẩm tự đánh dấu bài nộp cuối.** Cờ `final_deliverable` suy từ hình dạng DAG
  (`team_task_steps.py:341-343`: step nào không là dep của ai) thay cho heuristic "artifact
  dài nhất" từng bốc nhầm bài reviewer. Harvest chỉ nhận "via flag" khi **đúng một** row
  mang cờ, gặp nhiều terminal thì từ chối chứ không đoán. Live: 4/4 case harvest via flag.
- **`team-tick failed` hết treo**: tái hiện 5/5 lần, cùng một traceback, phân loại xong.
- **Cắt bản 0.16.0**: CHANGELOG tách rõ default-on ↔ opt-in (`b4c1845`), baseline journey
  4 chặng (`8e08e9c`), tag local `v0.16.0`. Gate: BE 4404 passed/70 skipped · FE 417
  vitest · ruff sạch · tsc 0 · cold-start smoke `--browser` 6/6.

## Quyết định & vì sao

| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| Trục 5 ghi **"chưa đủ mẫu"**, không ghi "không hồi quy" | Chỉ 2/4 case chấm được (cần ≥3), n=2 hoà 1-1 kèm confound độ dài. Số đó không đỡ nổi chữ "không hồi quy" | Bản release thiếu một trục có số; nhưng thiếu số thật hơn là có số bịa |
| Cờ `final_deliverable` **không** vào `plan_hash` | Nó là thuộc tính suy ra từ hình dạng, không phải nội dung kế hoạch; đưa vào sẽ làm plan hash cũ stale vô cớ | Cờ không được version hoá cùng kế hoạch |
| Không nới assert / không nới ngưỡng để mua màu xanh | 7 vòng L2 trượt vì 5 nguyên nhân khác nhau, mỗi lần sửa đúng nguyên nhân đó | Tốn 7 vòng thay vì 1 |
| Baseline giữ `j2 cost_usd: 0.0` thay vì "sửa" cho đẹp | `total_cost_usd` lấy từ `sum_cost` (sổ step — thứ cost cap enforce), escalation là one-step vehicle nên call rơi vào capture. Đặc tính có sẵn, tái hiện cả 2 lần cắt | Bản sau so vào baseline sẽ thấy số 0; đã ghi caveat kèm |

## Vấp & học được

- **Giả thuyết của tôi về trục 5 SAI, và phải mất một vòng chạy lại mới biết.** Hai case
  hỏng, tôi đoán do tranh provider → chạy lại lúc máy rảnh → **hỏng y hệt**. Lúc đó mới đi
  đọc transcript (19 lần "429" cạnh `academic_search`) rồi `curl` xác nhận: **OpenAlex
  rate-limit theo IP** sau ~14 brief. Bài học: đoán rồi thử lại thì rẻ hơn đọc log đúng
  một lần — nhưng chỉ đúng lần đầu; lần hai phải đi tìm bằng chứng.
- **Suýt chấm dữ liệu vô nghĩa lần thứ hai.** Byte count của 4 file nhìn đều bình thường.
  Mở nội dung ra mới thấy 1 file là marker `waiting_clarify` (không phải bài nộp) và 1 file
  là lời từ chối do chính 429 gây ra. **Kích thước file không chứng minh file có nội dung.**
- **Baseline bị dán nhãn sai version, và không phải lỗi code.** File tên `0.16.0` ghi
  `"version": "0.15.0"`: `conftest._version()` đọc **metadata bản đã cài**, không đọc
  `pyproject.toml`, mà editable install không tự refresh khi bump version. Hàm làm đúng ý
  đồ (docstring: nhãn sai version còn tệ hơn nhãn "uninstalled"). Lỗ hổng ở **quy trình**
  → thêm bước reinstall trước khi cắt baseline vào checklist releasing.
- **Exit code nói dối lần thứ 4 trong vòng này.** Notification báo "exit code 0" khi log
  ghi `1 failed, 8 passed`. Chỉ thân log mới là bằng chứng.
- **Tôi nghi cờ `final_deliverable` bắn sai** (nó chấm `review_final` làm bài nộp) rồi tự
  bác bằng chứng cứ: cờ suy từ DAG và bỏ qua loại step, harvest chỉ nhận khi đúng 1 row
  mang cờ ⇒ planner thật sự đã làm step review thành terminal. Không phải bug.

## Mở / sang sau

- **Trục 5 cần chạy lại từ IP khác hoặc giãn nhịp gọi OpenAlex** mới đủ 3 case. Cũng nên
  lưu ý: trục 5 đo trên brief tra cứu học thuật, trục 1-4 đo trên brief thương mại — hai
  tập đề khác nhau, không đặt cạnh nhau được.
- **Đã release**: 62 commit + tag `v0.16.0` lên `origin/main` (`d924c41`). Bằng chứng
  release chốt vào `docs/release-evidence-0.16.0.md` để trace được từ repo; ghi chú làm
  việc vẫn ở `plans/` (gitignored) có chủ đích. Trục 5 đóng bằng **waive**, không phải
  bằng số đo — nợ này sang bản sau.
