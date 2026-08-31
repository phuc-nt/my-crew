# Benchmark live 5 trục + bug ghi chú trần chi phí

2026-09-01 · ✅ Done (3/5 trục đo được)

## Làm gì

- Chạy benchmark 4 journey live (j1, j1b, j2, j5) hai vế baseline `c00ca30` ↔ candidate HEAD:
  **0 vượt ngưỡng** ở cả 3 trục đo được (chi phí / thời gian tường / số lần gọi model);
  `llm_calls` + `terminal_state` khớp tuyệt đối.
- Viết bộ live cho Phase 1-5: L1/L1b (trần chi phí), L2 (cap dep vào prompt), L4/L4b.
- Sửa bug do L1 tìm ra: ghi chú trần chi phí bị nhánh drop vứt mất (`397fecb`).
- Thu hoạch deliverable hai vế + chấm mù bằng `quality_judge` cho trục 5.
- Báo cáo 4 trục + phần "chưa đo được" ở
  `plans/260831-1841-openhuman-borrow-budget-output-guards/reports/bench-260831-phase6-five-axis-delta.md`.

## Quyết định & vì sao

| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| Giữ sàn 200 ký tự, miễn trừ riêng ghi chú trần chi phí | Sàn đang lọc stub thật (`"Lỗi: hết lượt web."`); hạ sàn sẽ phá guard đó | Thêm một nhánh điều kiện thay vì một con số |
| Marker lấy từ `COST_CAP_GAP_NOTE.split("{")[0]`, không chép tay | Chép tay thì đổi câu chữ sau này sẽ để scan khớp vào chuỗi guard không còn phát ra | Phụ thuộc import chéo module |
| Ghi trục 4 + trục 5 là **chưa đo được**, không nới assert/timeout | Nới chỉ mua màu xanh, không chứng minh thêm gì về guard | Báo cáo có ô trống |
| Không lấy phiếu 2–2 của judge làm kết luận | Phép trích sai + fleet không có web → judge chấm "bên nào từ chối hay hơn" | Mất một con số nhìn rất gọn |

## Vấp & học được

- **J5 phân loại sai ba lần.** "Quá tải harness" → sai (baseline fail cả khi chạy một mình);
  "baseline chậm hơn có hệ thống" → sai (mẫu 4 settle 192.9s rồi fail ở assertion KHÁC);
  cuối cùng mẫu 5 pass 120.86s — nhanh nhất mọi mẫu. Là **nhiễu lấy mẫu ở cả hai vế**.
  Dừng ở mẫu 4 thì đã viết ngược hẳn vào báo cáo. → Đừng kết luận từ mẫu chưa đủ, kể cả khi
  câu chuyện đã "hợp lý".
- **`git diff` trả lời được câu hỏi tưởng phải mua bằng tiền.** `worker coordinator/team-tick
  failed` nghi là hồi quy; diff `team_tick_runner.py` + `coordinator/` ra **rỗng** → lỗi CÓ
  SẴN, kết luận với chi phí 0 thay vì chạy thêm mẫu trả phí.
- **Bug 9 ký tự.** Ghi chú trần chi phí dài 191, sàn cứu nháp 200 → step bị drop vứt luôn
  lý do dở dang, bước sau báo "KHÔNG CÓ KẾT QUẢ". Hỏng **đúng lúc guard siết mạnh nhất**
  (cap nổ sớm ⇒ chưa kịp sinh prose ⇒ note là toàn bộ text). 14 ca offline không thấy vì
  stub qua nhánh drop — đúng lý do bộ live tồn tại.
- **Heuristic "artifact dài nhất" bốc nhầm bài phê bình.** Review của câu trả lời tệ thì dài
  hơn chính câu trả lời. 2/8 file đem đi chấm là bài của reviewer. Sửa sang "step cuối" thì
  trúng stub `waiting_clarify` 145 ký tự. → Không đoán deliverable bằng heuristic; để sản
  phẩm tự đánh dấu bài nộp cuối.

## Mở / sang sau

- `worker coordinator/team-tick failed`: lỗi có sẵn, 1/5 lần, chưa bắt được traceback.
- Brief L2 phải đủ nặng để dep vượt 8000 ký tự nhưng đủ nhẹ để settle < 900s; cân nhắc dep
  dài bằng fixture thay vì nhờ model viết dài. Brief L1b chưa giữ `needs_web` ổn định.
- Trục 5 cần fleet có web + một cờ đánh dấu bài nộp cuối trên artifact.
