"""Nhóm C (bậc độ khó) + nhóm D (trợ lý), model thật.

Nhóm C ghim P3: intake chấm độ khó trong CHÍNH lời gọi nó vốn đã gọi, và chỉ bậc "low"
đổi hành vi. Bậc được ghi vào bản ghi định tuyến, nên assert đi vào đó — đo bậc bằng
cách suy ngược từ độ dài đầu ra thì đo nhầm thứ khác.

Nhóm D ghim chân CÒN THIẾU của sự cố production đã có: `test_ops_intent_delegation_live`
chứng minh bộ phân loại trả đúng `assign_team_task`, nhưng dừng ở đó. Ở đây đi hết
đường — từ tin nhắn Telegram tới hàng trong store — vì giữa hai đầu đó còn cả tầng
xác nhận và tầng ops, và một quyết định phân loại đúng vẫn có thể chết dọc đường.
"""

from __future__ import annotations

import pytest

from my_crew.agent.sprint_intake import EFFORT_TIERS

# --- C: ba bậc độ khó ---------------------------------------------------------------


def test_c1_a_trivially_easy_brief_is_scored_low(live_run):
    """Đề dễ tới mức không còn gì để cân nhắc → "low", và low là bậc DUY NHẤT đổi hành
    vi (dùng model rẻ `sprint_low`, cắt bớt ngân sách vòng revise).

    Chấp nhận cả "medium" cho một đề dễ là chấp nhận đúng cái mà P3 tồn tại để bỏ đi,
    nên case này assert cứng — nếu model thật không chấm nổi bậc thấp cho đề này thì
    tính năng không đứng được, và đó là điều cần biết.

    Đề phải nằm TRONG lĩnh vực của dàn diễn viên (domain pack `pm`) VÀ phải tự chứa đủ
    dữ liệu VÀ không được có động từ GỬI ĐI. Ba kiểu hỏng đã gặp trước khi tới bản này,
    cả ba đều chết ở tầng phân loại nên không lần nào tới được tầng chấm bậc — đo nhầm
    tầng chứ không phải lỗi tính năng:

    1. lời cảm ơn khách hàng → bị từ chối vì ngoài lĩnh vực `pm`;
    2. trỏ tới "task 'dọn log cũ' trong sprint này" → agent đi TRA CỨU bản ghi đó trong
       hệ thống rồi báo không tìm thấy, thay vì coi đó là việc cần làm;
    3. "thông báo cho đội rằng..." → đọc thành lệnh GỬI, agent hỏi lại "gửi qua kênh nào?"

    Nên đề phải là việc SOẠN thuần tuý, mang sẵn mọi dữ liệu, không nhắc bản ghi nào
    trong hệ thống và không có động từ gửi/thông báo."""
    run = live_run()
    reply = run.h.trigger(
        "sprint: Soạn giúp anh đoạn mô tả 3 câu cho hạng mục 'Dọn log cũ hơn 30 ngày' "
        "để anh dán vào bảng kế hoạch: nêu mục đích, phạm vi, và định nghĩa hoàn thành."
    )
    rows = run.h.task_rows()
    assert rows, f"phải tạo được task: {reply[:200]!r}"

    route = run.route(rows[-1]["id"])
    assert route.get("mode") == "sprint", route
    assert route.get("effort") == "low", route
    assert not route.get("effort_high"), route


def test_c2_a_hard_brief_is_scored_high_without_changing_the_run(live_run):
    """Bậc "high" được ĐO ở vòng này chứ chưa được hành động: cờ `effort_high` nằm trong
    bản ghi định tuyến để sau này đối chiếu, còn pipeline chạy y hệt medium.

    Nên assert hai vế: cờ có mặt, VÀ dòng bước vẫn đúng một bước sprint như thường. Vế
    thứ hai mới là vế dễ vỡ — một thay đổi vô ý khiến "high" rẽ nhánh sẽ lọt qua nếu
    chỉ assert cái cờ.

    Cùng ràng buộc lĩnh vực như C1. Đề phải khớp ĐÚNG định nghĩa "high" của rubric —
    "tổng hợp nhiều nguồn TRÁI CHIỀU, hoặc phán đoán chuyên môn sâu" — chứ không chỉ là
    một đề dài hay một đề có đánh đổi. Bản trước (tách service hay giữ monolith) hỏi
    đúng một phán đoán nhưng không cần đối chiếu nguồn nào mâu thuẫn nhau, và rubric có
    luật "phân vân thì chọn bậc THẤP hơn", nên "medium" khi đó là rubric chạy đúng thiết
    kế chứ không phải bộ chấm hỏng. Đề dưới đây nêu thẳng các nguồn nói ngược nhau."""
    run = live_run()
    reply = run.h.trigger(
        "sprint: Đội mình đang cãi nhau về việc bỏ REST sang GraphQL. Tài liệu chính "
        "chủ của GraphQL, các bài hậu-kiểm của những công ty đã chuyển, và mấy bài "
        "phản biện gần đây nói ngược nhau về chi phí bảo trì và về N+1. Đọc kỹ các "
        "nguồn trái chiều đó rồi cho anh một khuyến nghị dứt khoát cho đội 3 người, "
        "nêu rõ chỗ nào các nguồn mâu thuẫn và anh tin bên nào hơn vì sao."
    )
    rows = run.h.task_rows()
    assert rows, f"phải tạo được task: {reply[:200]!r}"
    task_id = rows[-1]["id"]

    route = run.route(task_id)
    assert route.get("mode") == "sprint", route
    assert route.get("effort") in EFFORT_TIERS, route
    assert route.get("effort") == "high", route
    assert route.get("effort_high") is True, route

    steps = run.h.step_rows(task_id)
    assert [s["step_type"] for s in steps] == ["sprint"], (
        f'bậc "high" chưa được phép rẽ nhánh — dòng bước phải y hệt medium: {steps}'
    )


# --- D: trợ lý trả lời hay giao việc? ------------------------------------------------


def test_d1_an_ordinary_question_is_answered_without_creating_work(live_run):
    """Chiều tốn kém của lỗi phân loại: một câu hỏi thường biến thành task.

    Mỗi lần dương tính giả ở đây là một vòng xác nhận cộng — nếu CEO bấm xác nhận —
    tiền decompose thật cho một việc không tồn tại."""
    run = live_run()
    reply = run.h.trigger("Công ty mình hiện có bao nhiêu người vậy em?")
    assert run.h.task_rows() == [], (
        f"câu hỏi thường không được sinh ra việc: {run.h.task_rows()}"
    )
    assert reply.strip(), "phải có lời đáp cho CEO, không được im lặng"


@pytest.mark.parametrize(
    ("case", "brief"),
    [
        (
            "loi-nho-tu-nhien",
            "Nghiên cứu giúp anh thị trường xe máy điện Việt Nam 2026. Cần biết: 3 hãng "
            "dẫn đầu thị phần, giá bán lẻ từng dòng chủ lực, và chính sách trợ giá/thuế "
            "của nhà nước năm nay. Tổng hợp thành bảng so sánh, ghi rõ nguồn.",
        ),
        (
            "khao-sat-cong-cu",
            "Khảo sát các công cụ cho phép gửi tin nhắn Zalo OA tự động qua API: so sánh "
            "giá và giới hạn tin/tháng, gợi ý nên dùng cái nào",
        ),
    ],
)
def test_d2_a_naturally_phrased_delegation_becomes_a_real_task(live_run, case, brief):
    """Chân CÒN THIẾU của sự cố production.

    `test_ops_intent_delegation_live` đã ghim rằng bộ phân loại trả `assign_team_task`
    cho đúng hai câu này. Nhưng CEO không đọc kết quả phân loại — CEO đọc xem việc có
    được tạo ra không. Giữa hai đầu còn tầng ops và tầng xác nhận, nên chặng cuối cần
    được ghim riêng.

    Hai câu giữ NGUYÊN VĂN như CEO đã gửi lúc sự cố: một regression test so với đầu vào
    thật thì mới là regression test. Không sửa hai chuỗi này cho dễ xanh — sửa đầu vào
    thật đi thì bài test không còn bảo vệ được sự cố nữa.

    Cái giá phải trả: dàn diễn viên ở đây chỉ có domain `pm`, nên câu nghiên cứu thị
    trường xe máy điện có lúc bị chính agent đáp "ngoài phạm vi" ngay ở tầng ops, trước
    khi tới tầng định tuyến — trong khi câu khảo sát công cụ Zalo OA thì qua. Đó là hạn
    chế của FIXTURE (một domain duy nhất), không phải của sản phẩm, nên khi case này đỏ
    thì phải đọc `reply` trước: đáp "ngoài phạm vi" là hạn chế fixture, còn im lặng hay
    đáp suông mới là sự cố cũ tái phát."""
    run = live_run()
    reply = run.h.trigger(brief)
    rows = run.h.task_rows()
    assert rows, (
        f"[{case}] lời giao việc phải thành việc thật, không phải một lời đáp suông.\n"
        f"reply={reply[:400]!r}"
    )
    route = run.route(rows[-1]["id"])
    assert route.get("mode") in {"sprint", "team"}, route
