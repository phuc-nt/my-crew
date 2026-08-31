# Benchmark live 5 trục + 2 bug (sản phẩm & harness)

2026-09-01 · ✅ Done (3/5 trục đo được; L3/L5 xanh)

## Làm gì

- Chạy benchmark 4 journey live (j1, j1b, j2, j5) hai vế baseline `c00ca30` ↔ candidate HEAD:
  **0 vượt ngưỡng** ở cả 3 trục đo được (chi phí / thời gian tường / số lần gọi model);
  `llm_calls` + `terminal_state` khớp tuyệt đối.
- Viết bộ live cho Phase 1-5: L1/L1b (trần chi phí), L2 (cap dep vào prompt), L3/L5 (audit
  trail + bảng thống kê tool), L4/L4b. Chạy được: L1 (ra bug), L3/L5 (xanh, 1132s).
- Sửa bug do L1 tìm ra: ghi chú trần chi phí bị nhánh drop vứt mất (`397fecb`).
- Sửa bug harness do L3/L5 lộ ra: fixture khai dùng chung 1 journey nhưng chạy 2 (`928f496`).
- Thu hoạch deliverable hai vế + chấm mù bằng `quality_judge` cho trục 5.
- Báo cáo 4 trục + phần "chưa đo được" ở
  `plans/260831-1841-openhuman-borrow-budget-output-guards/reports/bench-260831-phase6-five-axis-delta.md`.

## Quyết định & vì sao

| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| Giữ sàn 200 ký tự, miễn trừ riêng ghi chú trần chi phí | Sàn đang lọc stub thật (`"Lỗi: hết lượt web."`); hạ sàn sẽ phá guard đó | Thêm một nhánh điều kiện thay vì một con số |
| Marker lấy từ `COST_CAP_GAP_NOTE.split("{")[0]`, không chép tay | Chép tay thì đổi câu chữ sau này sẽ để scan khớp vào chuỗi guard không còn phát ra | Phụ thuộc import chéo module |
| Ghi trục 4 + trục 5 là **chưa đo được**, không nới assert/timeout | Nới chỉ mua màu xanh, không chứng minh thêm gì về guard | Báo cáo có ô trống |
| L3/L5 dùng `scope="module"`, `journey_budget` giữ function scope | Budget dùng chung với mọi file journey khác + key theo `node.name`; nới scope nó sẽ đổi hành vi cả bộ live | Phải thêm `live_api_key_module` vì module-scoped không request được function-scoped |
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
- **Docstring nói một đằng, scope làm một nẻo.** L3/L5 ghi rõ "ride ONE journey... paying
  twice would measure two different runs while claiming to cross-check one", nhưng cả hai
  fixture để scope mặc định (function) ⇒ chạy 2 journey, tức **làm đúng cái nó nói nó tồn
  tại để tránh**, và làm rỗng chính bất biến L5 kiểm — vẫn xanh. Bắt được vì cặp kết quả
  `E.` (L3 timeout + L5 pass) là **bất khả thi** nếu thật sự dùng chung journey. → Khi con
  số/hình dạng kết quả *không thể xảy ra*, đừng bỏ qua vì "dù sao cũng xanh".

## Mở / sang sau

- `worker coordinator/team-tick failed`: lỗi có sẵn, 1/5 lần, chưa bắt được traceback.
- Brief L2 phải đủ nặng để dep vượt 8000 ký tự nhưng đủ nhẹ để settle < 900s; cân nhắc dep
  dài bằng fixture thay vì nhờ model viết dài. Brief L1b chưa giữ `needs_web` ổn định.
- Trục 5 cần fleet có web + một cờ đánh dấu bài nộp cuối trên artifact.
