# Vá B1 (kế toán chi phí) + B7 (extra tuỳ chọn), và truy nguyên vụ Gmail
2026-08-31 · ✅ Done

## Làm gì

- **B1**: hai màn hình chi phí (control-plane + FE) đang cộng hàng CaptureStore, lệch với số mà
  cap thật sự hành động. Chuyển cả hai sang `TeamTaskStore.sum_cost` qua một hàm chung
  `control_plane_views.task_cost_total`. Hàng capture ở lại `steps` làm vết audit từng lần chạy.
- **B7**: `react_loop` nhập `deepagents` (extra tuỳ chọn `deep`) vô điều kiện → `loop_engine:
  langchain` chết trên bản cài mặc định. Cho degrade: vắng gói thì bỏ scratch middleware **và**
  bỏ luôn mệnh đề hứa scratch trong prompt.
- **Vụ Gmail qua Telegram**: truy ra task thật `30cbc8baa90d` trong instance đang chạy. Không
  phải bug — `secretary` bị CEO cắt quyền gws từ v71 (2026-08-06). Báo cáo:
  `plans/reports/gmail-task-blocked-by-secretary-gws-config-report.md`.

## Quyết định & vì sao

| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| `sum_cost` là thẩm quyền, không phải CaptureStore | Cap enforce theo `sum_cost`; số CEO thấy mà khác số cap hành động thì cái trần vừa nổ trở nên vô hình | Mất "tổng đã đốt kể cả lần bỏ dở" ở dòng tổng — vẫn cộng lại được từ `steps` |
| Vá **cả** `routes_outputs`, không chỉ control-plane | Cùng một lỗi ở hai nơi; vá một nơi thì hai màn hình cãi nhau — tệ hơn cả trước khi vá | Chạm thêm một file ngoài phạm vi B1 ban đầu |
| B7 chọn "bỏ scratch" thay vì thêm deps thật | File nháp là tiện ích, không phải lý do tồn tại của tầng tools; kéo `docker>=7.1` vào bản cài gọn là đi ngược chủ đích extra | Bản không cài `deep` mất chỗ soạn nháp dài |
| KHÔNG tự bật lại gws cho `secretary` | Đảo quyết định CEO đã ghi rõ lý do (agent test, từng lộ dữ liệu cá nhân trong UAT) | Vụ Gmail còn treo tới khi CEO chọn A/B/C |

## Vấp & học được

- **Test xanh không có nghĩa là bản vá có tải.** Lần kiểm-đột-biến đầu cho B1 in "10 passed" —
  tôi tưởng test yếu. Thật ra chuỗi thay thế trúng nhánh **không chạy**: fixture không có
  `captures.sqlite3` nên hàm thoát sớm ở dòng 115, còn tôi đột biến dòng 124. Đúng chỗ thì đỏ
  ngay. Bài học: khi đột biến không đổi kết quả, nghi mình đột biến nhầm nhánh trước khi nghi test.
  Hệ quả tốt: lộ ra nhánh chính (có capture — nhánh production thật sự chạy) **chưa hề có test**;
  đã bổ sung, dựng đúng hình lỗi thật (1 bước, 2 attempt).
- **Một test cũ đỏ không mặc nhiên là test sai.** `test_task_cost_projects_steps_and_sums_totals`
  đỏ vì nó ghi hàng capture cho task **không tồn tại** trong TeamTaskStore → `sum_cost`=0 là
  đúng. Sửa fixture cho nhất quán (seed cả hai kho), không nới assert.
- **Prompt dựng trước middleware.** Bản vá B7 nếu chỉ bọc try/except thì model vẫn đọc mệnh đề
  hứa có file scratch trong khi tool không tồn tại — đúng kiểu đốt lượt đi xin quyền. Phải dời
  việc dựng middleware lên trước rồi mới ghép prompt.
- **Đọc log của instance thật rẻ hơn suy luận từ mã.** Vụ Gmail: grep `service.err.log` +
  sqlite ra ngay `pic_id=secretary`, rồi profile nói thẳng lý do trong comment. Đoán từ mã thì
  đã đi nhầm hướng "thiếu tool Gmail" (thực ra có `gws.gmail`, và OAuth vẫn sống — đã chạy
  `gws gmail +triage` thật để loại trừ).

## Mở / sang sau

- Vụ Gmail chờ CEO chọn A (bật lại gws cho secretary) / B (giao agent khác) / C (agent riêng).
- Task Gmail tiêu $0.029 chỉ để nói "em không có quyền" — chưa có cổng "đề bài cần tool mà người
  nhận không có" ở khâu decompose. Đáng làm, chưa làm.
