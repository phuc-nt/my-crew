# Đọc sổ quỹ và báo cáo dòng tiền

Khi được hỏi về tình hình thu chi/dòng tiền trong tuần gần nhất, chạy report kind
`cashflow-weekly`. Dữ liệu lấy từ sổ quỹ (Google Sheet hoặc file CSV đã cấu hình sẵn —
chỉ đọc). Nếu không đọc được sổ quỹ, báo cáo sẽ ghi rõ "THIẾU" cho từng số liệu không lấy
được — không tự suy đoán hay làm tròn thay.

Muốn ghi thêm một dòng vào sổ quỹ, dùng lệnh `append_ledger_row` (cần được bật riêng cho
từng agent — không tự động chạy).
