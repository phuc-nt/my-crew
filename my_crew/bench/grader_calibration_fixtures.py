"""Fixed artifacts for calibrating the graders (H4) and probing the content role.

Four business deliverables, each in two versions over the SAME hand-off and acceptance
text: `SEEDED` carries three planted defects with the marker strings that count as
"caught" when they appear in a grader's failure list; `CLEAN` is the corrected
counterpart a grader must pass. Kept in the package rather than a scratch script so the
role bench, the calibration report and any future grader change measure against the
same material — a fixture that lives in someone's /tmp is not a baseline.

Markers are the WRONG value or the specific omission, chosen not to occur in correct
content, so a reviewer that names the defect in any wording is credited.
"""

from __future__ import annotations

# Each artifact: what the step was GIVEN (handoff), the rubric it is graded against
# (acceptance), the artifact with three planted defects, and per defect the marker strings
# any of which in the reviewer's failure list counts as "caught". Markers are the WRONG
# value or the specific omission, chosen not to occur in correct content.
SEEDED = [
    {
        "name": "sales_trend",
        "handoff": ("Số liệu bán hàng quý 2. Sản phẩm A: T4 120tr, T5 135tr, T6 128tr. "
                    "Sản phẩm B: T4 95tr, T5 88tr, T6 76tr. Sản phẩm C: T4 30tr, T5 42tr, "
                    "T6 58tr. Chi phí marketing mỗi tháng chia đều cho 3 sản phẩm: T4 45tr, "
                    "T5 60tr, T6 60tr."),
        "acceptance": ("Nêu đúng xu hướng từng sản phẩm theo số liệu; tính đúng tổng doanh thu "
                       "quý của từng sản phẩm; chỉ ra sản phẩm đáng lo; đề xuất dồn ngân sách "
                       "marketing quý tới vào sản phẩm đang tăng, có lý do."),
        "result": (
            "## Xu hướng\n- Sản phẩm A: đi ngang quanh 120–135tr, tổng quý 383tr.\n"
            "- Sản phẩm B: giảm đều 3 tháng liên tiếp, tổng quý 269tr.\n"
            "- Sản phẩm C: đi ngang, tổng quý 130tr.\n\n"
            "## Đáng lo\nSản phẩm B giảm 20% từ T4 sang T6 — cần xem lại giá và kênh.\n\n"
            "## Đề xuất quý tới\nDồn ngân sách marketing vào sản phẩm B để chặn đà giảm, "
            "vì B là dòng có doanh thu lớn thứ hai và chi phí thu hút khách đã ổn định."),
        "errors": [
            {"id": "b_total_wrong", "markers": ["269"]},
            {"id": "c_called_flat", "markers": ["đi ngang", "tăng nhanh", "tăng mạnh", "tăng đều"]},
            {"id": "budget_to_declining", "markers": ["dồn", "sản phẩm đang tăng", "vào b",
                                                      "vào sản phẩm b", "sản phẩm c"]},
        ],
    },
    {
        "name": "office_choice",
        "handoff": ("Ba phương án thuê văn phòng, hợp đồng 24 tháng. A: 28tr/tháng, cọc 3 tháng, "
                    "miễn phí tháng đầu, cách trung tâm 12km. B: 35tr/tháng, cọc 2 tháng, có "
                    "sẵn nội thất (khỏi tốn 120tr đầu tư ban đầu), cách trung tâm 4km. C: "
                    "30tr/tháng, cọc 3 tháng, phải đầu tư nội thất 80tr, cách trung tâm 6km, "
                    "được hủy sau 12 tháng không phạt. Đội 15 người, ngân sách đầu tư ban đầu "
                    "tối đa 150tr, ưu tiên đi lại thuận tiện."),
        "acceptance": ("Tính đúng tổng chi phí 24 tháng của từng phương án theo dữ kiện; nêu "
                       "rủi ro từng phương án; khuyến nghị MỘT phương án trong ngân sách đầu "
                       "tư và đúng ưu tiên đi lại, có lý do."),
        "result": (
            "## Tổng chi phí 24 tháng\n- A: 28tr × 24 = 672tr tiền thuê, cọc 84tr hoàn lại.\n"
            "- B: 35tr × 24 = 840tr tiền thuê, cọc 70tr hoàn lại, không tốn đầu tư.\n"
            "- C: 30tr × 24 = 720tr + 80tr nội thất = 800tr, cọc 90tr hoàn lại.\n\n"
            "## Rủi ro\n- A: xa trung tâm, khó giữ nhân sự.\n- B: chi phí cao nhất.\n"
            "- C: cách trung tâm 16km, xa hơn cả A; đầu tư nội thất khó thu hồi nếu hủy.\n\n"
            "## Khuyến nghị\nChọn phương án A vì rẻ nhất và gần trung tâm nhất, phù hợp ưu "
            "tiên đi lại của đội."),
        "errors": [
            {"id": "a_free_month_ignored",
             "markers": ["672", "644", "miễn phí tháng đầu", "23 tháng"]},
            {"id": "c_distance_wrong", "markers": ["16km", "16 km", "6km", "6 km"]},
            {"id": "a_called_closest", "markers": ["gần trung tâm nhất", "12km", "12 km", "xa nhất",
                                                   "xa trung tâm nhất"]},
        ],
    },
    {
        "name": "event_plan",
        "handoff": ("Buổi offline ra mắt sản phẩm cho 60 khách, ngân sách 90 triệu, chuẩn bị "
                    "trong 5 tuần, đội 4 người."),
        "acceptance": ("Đủ 4 phần: timeline đủ 5 tuần theo từng tuần; bảng ngân sách theo hạng "
                       "mục cộng đúng 90 triệu; rủi ro chính kèm dự phòng; phân công đủ 4 "
                       "người trong đội."),
        "result": (
            "## 1. Timeline\n- Tuần 1: chốt địa điểm, danh sách khách.\n- Tuần 2: thiết kế "
            "ấn phẩm, gửi thư mời.\n- Tuần 3: chốt nhà cung cấp tiệc, âm thanh.\n- Tuần 4: "
            "tổng duyệt, xác nhận khách.\n\n"
            "## 2. Ngân sách\n| Hạng mục | Chi phí |\n|---|---|\n| Địa điểm | 30tr |\n"
            "| Tiệc nhẹ | 25tr |\n| Âm thanh, màn hình | 15tr |\n| Ấn phẩm, quà | 15tr |\n"
            "| Dự phòng | 10tr |\n| **Tổng** | **90tr** |\n\n"
            "## 3. Rủi ro\n- Khách đến ít: gọi xác nhận trước 3 ngày, mời thêm 20% danh sách.\n"
            "- Địa điểm hủy: giữ hợp đồng dự phòng với địa điểm thứ hai.\n\n"
            "## 4. Phân công\n- Lan: địa điểm và tiệc.\n- Minh: khách mời và truyền thông.\n"
            "- Hùng: kỹ thuật và ấn phẩm."),
        "errors": [
            {"id": "budget_sums_to_95", "markers": ["95", "cộng lại", "không khớp", "không bằng 90",
                                                    "tổng thực"]},
            {"id": "week5_missing", "markers": ["tuần 5", "4 tuần", "thiếu tuần", "5 tuần"]},
            {"id": "only_three_assigned", "markers": ["3 người", "ba người", "người thứ 4",
                                                     "người thứ tư", "4 người", "thiếu một"]},
        ],
    },
    {
        "name": "price_increase_email",
        "handoff": ("Bản nháp: 'Chào bạn, do chi phí tăng nên bên mình phải tăng giá 15% kể từ "
                    "tháng sau. Mong bạn thông cảm. Ai không đồng ý có thể hủy dịch vụ. Cảm "
                    "ơn.' Yêu cầu: nêu ít nhất 3 điểm yếu, rồi viết lại giữ đúng thông tin cốt "
                    "lõi (tăng 15%, áp dụng từ tháng sau), giọng chuyên nghiệp, thuyết phục "
                    "khách ở lại."),
        "acceptance": ("Nêu ít nhất 3 điểm yếu của bản nháp; bản viết lại giữ đúng mức tăng 15% "
                       "và thời điểm áp dụng từ tháng sau; giọng chuyên nghiệp; có lý do để "
                       "khách ở lại."),
        "result": (
            "## Điểm yếu của bản nháp\n1. Không giải thích giá trị khách nhận được, chỉ nói chi "
            "phí tăng.\n2. Câu 'Ai không đồng ý có thể hủy' đẩy khách ra thay vì giữ chân.\n\n"
            "## Bản viết lại\nKính gửi Quý khách,\n\nCảm ơn Quý khách đã đồng hành cùng chúng "
            "tôi. Để tiếp tục nâng cấp hạ tầng và mở rộng đội ngũ hỗ trợ 24/7, chúng tôi sẽ "
            "điều chỉnh giá dịch vụ tăng 20%, áp dụng từ quý sau. Trong thời gian tới, Quý "
            "khách sẽ nhận thêm tính năng báo cáo tự động và ưu tiên hỗ trợ kỹ thuật.\n\n"
            "Nếu Quý khách cần trao đổi thêm về gói dịch vụ phù hợp, đội ngũ của chúng tôi "
            "luôn sẵn sàng.\n\nTrân trọng,\nĐội ngũ Chăm sóc khách hàng"),
        "errors": [
            {"id": "only_two_weaknesses", "markers": ["2 điểm", "hai điểm", "3 điểm", "ít nhất 3",
                                                     "thiếu điểm yếu"]},
            {"id": "rate_changed_to_20", "markers": ["20%", "20 %", "15%"]},
            {"id": "timing_changed_to_quarter", "markers": ["quý sau", "tháng sau"]},
        ],
    },
]


# CLEAN counterparts of SEEDED, keyed by name: the same handoff + acceptance, with every
# planted defect corrected. A grader that fails these is failing correct work.
CLEAN = {
    "sales_trend": (
        "## Xu hướng\n- Sản phẩm A: đi ngang quanh 120–135tr, tổng quý 383tr.\n"
        "- Sản phẩm B: giảm đều 3 tháng liên tiếp (95 → 88 → 76), tổng quý 259tr.\n"
        "- Sản phẩm C: tăng nhanh (30 → 42 → 58, gần gấp đôi), tổng quý 130tr.\n\n"
        "## Đáng lo\nSản phẩm B giảm 20% từ T4 sang T6 — cần xem lại giá và kênh.\n\n"
        "## Đề xuất quý tới\nDồn ngân sách marketing vào sản phẩm C vì đây là dòng duy nhất "
        "đang tăng đều qua cả 3 tháng; với cùng mức chi 15tr/tháng chia đều, C tăng 28tr "
        "trong khi A đi ngang và B giảm, nên đồng chi thêm ở C có xác suất sinh doanh thu "
        "cao nhất."),
    "office_choice": (
        "## Tổng chi phí 24 tháng\n- A: 28tr × 23 tháng (miễn phí tháng đầu) = 644tr tiền "
        "thuê, cọc 84tr hoàn lại, không nêu đầu tư nội thất.\n"
        "- B: 35tr × 24 = 840tr tiền thuê, cọc 70tr hoàn lại, không tốn đầu tư ban đầu.\n"
        "- C: 30tr × 24 = 720tr + 80tr nội thất = 800tr, cọc 90tr hoàn lại.\n\n"
        "## Rủi ro\n- A: cách trung tâm 12km, xa nhất trong ba phương án — khó giữ nhân "
        "sự, ngược ưu tiên đi lại.\n- B: tiền thuê cao nhất; ràng buộc 24 tháng không có "
        "điều khoản hủy.\n- C: đầu tư nội thất 80tr khó thu hồi nếu hủy sau 12 tháng.\n\n"
        "## Khuyến nghị\nChọn phương án B: gần trung tâm nhất (4km) nên đúng ưu tiên đi "
        "lại; không cần đầu tư ban đầu nên nằm trong ngân sách 150tr; tổng chi phí 24 "
        "tháng (840tr) chỉ cao hơn C (800tr) 40tr, đổi lại không phải bỏ 80tr nội thất "
        "khó thu hồi và gần trung tâm hơn."),
    "event_plan": (
        "## 1. Timeline\n- Tuần 1: chốt địa điểm, danh sách khách.\n- Tuần 2: thiết kế "
        "ấn phẩm, gửi thư mời.\n- Tuần 3: chốt nhà cung cấp tiệc, âm thanh.\n- Tuần 4: "
        "tổng duyệt, xác nhận khách.\n- Tuần 5: dựng sân khấu, chạy sự kiện, thu dọn.\n\n"
        "## 2. Ngân sách\n| Hạng mục | Chi phí |\n|---|---|\n| Địa điểm | 30tr |\n"
        "| Tiệc nhẹ | 25tr |\n| Âm thanh, màn hình | 15tr |\n| Ấn phẩm, quà | 10tr |\n"
        "| Dự phòng | 10tr |\n| **Tổng** | **90tr** |\n\n"
        "## 3. Rủi ro\n- Khách đến ít: gọi xác nhận trước 3 ngày, mời thêm 20% danh sách.\n"
        "- Địa điểm hủy: giữ hợp đồng dự phòng với địa điểm thứ hai.\n\n"
        "## 4. Phân công\n- Lan: địa điểm và tiệc.\n- Minh: khách mời và truyền thông.\n"
        "- Hùng: kỹ thuật và ấn phẩm.\n- Thảo: hậu cần, tiếp đón và điều phối ngày sự kiện."),
    "price_increase_email": (
        "## Điểm yếu của bản nháp\n1. Không giải thích giá trị khách nhận được, chỉ nói chi "
        "phí tăng.\n2. Câu 'Ai không đồng ý có thể hủy' đẩy khách ra thay vì giữ chân.\n"
        "3. Không có lời cảm ơn/ghi nhận và không có kênh để khách trao đổi thêm.\n\n"
        "## Bản viết lại\nKính gửi Quý khách,\n\nCảm ơn Quý khách đã đồng hành cùng chúng "
        "tôi. Để tiếp tục nâng cấp hạ tầng và mở rộng đội ngũ hỗ trợ 24/7, chúng tôi sẽ "
        "điều chỉnh giá dịch vụ tăng 15%, áp dụng từ tháng sau. Trong thời gian tới, Quý "
        "khách sẽ nhận thêm tính năng báo cáo tự động và ưu tiên hỗ trợ kỹ thuật.\n\n"
        "Nếu Quý khách cần trao đổi thêm về gói dịch vụ phù hợp, đội ngũ của chúng tôi "
        "luôn sẵn sàng.\n\nTrân trọng,\nĐội ngũ Chăm sóc khách hàng"),
}

