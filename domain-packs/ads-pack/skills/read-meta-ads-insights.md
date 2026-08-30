# Đọc chỉ số quảng cáo Meta Ads

Khi được hỏi về hiệu quả quảng cáo (chi tiêu, lượt tiếp cận, CTR) trong tuần gần nhất,
chạy report kind `ads-weekly`. Dữ liệu lấy từ Meta Marketing API (chỉ đọc, không sửa/tạo
chiến dịch — nằm ngoài phạm vi worker này). Nếu API không phản hồi được, báo cáo sẽ ghi
rõ "THIẾU" cho từng số liệu không lấy được — không tự suy đoán hay làm tròn thay.
