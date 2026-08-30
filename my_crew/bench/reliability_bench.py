"""Đo ĐỘ ỔN ĐỊNH của lớp intake khi chạy lại cùng một đề nhiều lần.

Bench v2 chạy mỗi đề đúng một lượt, nên nhiễu model bị làm tròn thành "kết quả". Một
bản mới làm intake bấp bênh hơn hẳn vẫn qua được bench v2 miễn là lượt chạy may mắn đó
đúng. Mode này biến chính sự bấp bênh đó thành con số so được giữa hai bản.

**Đo cái gì, và vì sao KHÔNG đo lớp định tuyến.** Kế hoạch ban đầu định chạy lại cả
`classify_brief` lẫn dự đoán định tuyến k lượt. Nhưng cả hai đều THUẦN CODE —
`classify_brief` ghi rõ "Thuần code, không gọi model", và `routing_bench.run_suite` đã
NỔ khi hai lượt lệch nhau. Chạy lại một hàm tất định k lượt thì `pass_rate` bằng 1.0 ở
mọi case, mọi bản, mãi mãi: một trục không bao giờ tụt được thì không phải là trục.

Nhiễu thật nằm ở `sprint_intake` — nó gọi model (`role="plan"`) rồi FAIL-OPEN về một
kế hoạch tối thiểu khi model trả rỗng/không phải JSON/thiếu trường/chọn người không có
thật. Chính đường fail-open đó là thứ cần theo dõi: nó không làm test nào đỏ, không làm
lệnh giao việc hỏng, chỉ lặng lẽ hạ chất lượng kế hoạch. Một bản mới làm tỉ lệ fail-open
tăng từ 0/5 lên 3/5 là một hồi quy thật mà không có bài kiểm tra nào khác nhìn thấy.

Lớp định tuyến vẫn được ghim ở đây, nhưng bằng một khẳng định tất định rẻ tiền
(`routing_stable`) chứ không bằng k lượt chạy vô nghĩa.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from my_crew.bench.brief_suite import ALL_CASES
from my_crew.bench.pipeline_bench import BriefCase

#: Bản của định dạng JSON mode này ghi ra. `compare_reliability` từ chối so hai bản
#: lệch nhau — im lặng so nhầm hai định dạng còn tệ hơn là không so được.
FORMAT_VERSION = 1

#: k=5 là đủ để phân biệt "luôn đúng" với "thỉnh thoảng trượt" mà vẫn rẻ. k=3 không tách
#: được 1/3 khỏi nhiễu lấy mẫu; k=10 gấp đôi tiền để làm rõ một chữ số thập phân mà
#: quyết định nào ở đây cũng không cần tới.
DEFAULT_K = 5

#: Đội giả lập dùng cho mọi case, cố định. `sprint_intake` chọn `assigned_to` TRONG
#: danh sách này, nên danh sách phải ổn định giữa các bản thì `assignee_mode` mới so
#: được. Hai người để việc chọn sai người là một khác biệt quan sát được — một người
#: thì mọi lượt đều "đúng" một cách tầm thường.
BENCH_STAFF: list[tuple[str, str]] = [
    ("writer", "Người viết nội dung"),
    ("analyst", "Người phân tích số liệu"),
]


@dataclass(frozen=True)
class CaseReliability:
    """Một đề chạy k lượt ra cái gì.

    `pass_rate` ở đây nghĩa là "tỉ lệ lượt KHÔNG rơi vào fail-open", không phải "tỉ lệ
    trả lời đúng". Không có đáp án vàng cho một bản rút gọn đề bằng văn xuôi, nên chấm
    đúng/sai sẽ phải viết một judge — mà judge thì cũng là model, cũng nhiễu, và khi đó
    mình đo nhiễu của judge chứ không đo nhiễu của intake. Fail-open thì QUAN SÁT ĐƯỢC
    một cách tất định: kế hoạch fallback dựng nguyên văn đề của CEO.
    """

    case: str
    k: int
    pass_rate: float
    #: Người được giao hay gặp nhất qua k lượt. Đổi người giữa hai bản là thay đổi hành
    #: vi cần người đọc nhìn thấy, kể cả khi `pass_rate` không đổi.
    assignee_mode: str
    #: `pass_rate` không nằm ở 0 hay 1 — tức là cùng một đề, cùng một bản, lúc được lúc
    #: không. Đây là con số v2 vứt đi và mode này sinh ra để giữ lại.
    flake: bool
    #: `needs_web` hay gặp nhất. Lật trục này làm đổi cả chi phí lẫn chất lượng lượt sau.
    needs_web_mode: bool
    #: Số lượt lệch khỏi đáp án hay gặp nhất, để đọc được mức phân tán mà không cần k.
    minority_runs: int
    errors: tuple[str, ...] = field(default=())


def _is_fallback(plan: Any, brief: str) -> bool:
    """Lượt này có rơi về kế hoạch fail-open không?

    Dấu vết tất định: `_fallback` dựng `SprintPlan(goal=brief.strip(), acceptance="")`.
    Một lượt intake THẬT gần như không bao giờ trả lại nguyên văn đề kèm acceptance
    rỗng — cả hai điều kiện cùng lúc mới tính, để một bản rút gọn tình cờ trùng đề ngắn
    không bị đếm nhầm là hỏng.
    """
    return (plan.goal or "").strip() == brief.strip() and not (plan.acceptance or "").strip()


def bench_case(case: BriefCase, *, k: int = DEFAULT_K,
               intake: Callable[..., Any] | None = None) -> CaseReliability:
    """Chạy một đề k lượt qua intake thật và tổng hợp lại.

    `intake` tiêm được để test offline chứng minh comparator BẮT ĐƯỢC pass_rate tụt mà
    không tốn một lời gọi model nào. Mặc định là đường thật.
    """
    if intake is None:
        from my_crew.agent.sprint_intake import sprint_intake as intake

    ok = 0
    assignees: Counter[str] = Counter()
    needs_web: Counter[bool] = Counter()
    errors: list[str] = []

    for _ in range(max(1, k)):
        try:
            plan, _cost = intake(case.goal, BENCH_STAFF)
        except Exception as exc:  # noqa: BLE001 — một lượt nổ là một điểm dữ liệu
            # Nổ hẳn KHÁC fail-open: fail-open là đường đã thiết kế, còn nổ là ngoài dự
            # kiến. Đếm vào phần trượt nhưng giữ lại lý do, nếu không một bản làm intake
            # nổ sạch k lượt sẽ trông y hệt một bản chỉ fail-open nhiều.
            errors.append(f"{type(exc).__name__}: {exc}")
            continue
        if not _is_fallback(plan, case.goal):
            ok += 1
        assignees[plan.assigned_to] += 1
        needs_web[bool(plan.needs_web)] += 1

    k_eff = max(1, k)
    # `most_common(1)` trên Counter rỗng nổ IndexError, và Counter rỗng là chuyện có
    # thật khi cả k lượt đều nổ — nên mặc định phải có, không được để nó vỡ ở đây.
    top_assignee = assignees.most_common(1)[0] if assignees else ("", 0)
    top_web = needs_web.most_common(1)[0] if needs_web else (True, 0)
    rate = ok / k_eff
    return CaseReliability(
        case=case.name,
        k=k_eff,
        pass_rate=rate,
        assignee_mode=top_assignee[0],
        flake=0.0 < rate < 1.0,
        needs_web_mode=bool(top_web[0]),
        minority_runs=k_eff - top_assignee[1],
        errors=tuple(errors),
    )


def routing_stable(cases: tuple[BriefCase, ...] = ALL_CASES) -> bool:
    """Lớp định tuyến vẫn tất định chứ?

    Rẻ và tất định, nên nó nằm ở đây thay cho k lượt chạy vô nghĩa. `run_suite` của
    routing_bench đã NỔ khi hai lượt lệch nhau, nên hàm này chỉ cần gọi nó và để lỗi
    nổi lên — bọc lại thành False sẽ nuốt mất đúng thông tin cần đọc.
    """
    from my_crew.bench.routing_bench import run_suite as routing_suite

    routing_suite(cases, repeats=2)
    return True


def run_suite(cases: tuple[BriefCase, ...] = ALL_CASES, *, k: int = DEFAULT_K,
              intake: Callable[..., Any] | None = None) -> dict[str, Any]:
    report = {c.name: asdict(bench_case(c, k=k, intake=intake)) for c in cases}
    return {"format_version": FORMAT_VERSION, "k": k, "cases": report}


#: Trục được so. `pass_rate` là trục chính; `assignee_mode`/`needs_web_mode` bắt được
#: thay đổi hành vi xảy ra mà tỉ lệ không đổi; `flake` bắt được đúng trường hợp một bản
#: đi từ ổn định sang lúc được lúc không.
COMPARED_FIELDS = ("pass_rate", "assignee_mode", "needs_web_mode", "flake")


def compare_reliability(baseline: dict[str, Any],
                        candidate: dict[str, Any]) -> list[dict[str, Any]]:
    """Từng ô khác nhau giữa hai bản, phẳng, sẵn sàng in ra bảng.

    Từ chối so hai định dạng lệch bản, theo tiền lệ `compare_routing`: một danh sách
    khác biệt sinh ra do đổi định dạng trông hệt như thay đổi hành vi, đúng loại kết
    luận sai mà cả mode này sinh ra để tránh.

    Cũng từ chối so hai bản chạy khác `k`: `pass_rate` của k=3 và của k=5 không cùng
    độ phân giải, nên 0.67 so với 0.60 là một dòng delta VÔ NGHĨA — nó chỉ phản ánh
    mẫu số khác nhau chứ không phản ánh hành vi khác nhau.
    """
    b_ver = baseline.get("format_version", 0)
    c_ver = candidate.get("format_version", 0)
    if b_ver != c_ver:
        raise ValueError(
            f"reliability report format_version lệch nhau ({b_ver} vs {c_ver}) — "
            "chạy lại baseline bằng bản script hiện tại trước khi so"
        )
    b_k = baseline.get("k")
    c_k = candidate.get("k")
    if b_k != c_k:
        raise ValueError(
            f"reliability report chạy khác k ({b_k} vs {c_k}) — pass_rate hai bên khác "
            "mẫu số nên không so trực tiếp được; chạy lại baseline với cùng k"
        )

    rows: list[dict[str, Any]] = []
    b_cases = baseline.get("cases", {})
    c_cases = candidate.get("cases", {})
    for name in sorted(set(b_cases) | set(c_cases)):
        b = b_cases.get(name)
        c = c_cases.get(name)
        if b is None or c is None:
            rows.append({"case": name, "field": "case",
                         "baseline": "—" if b is None else "có",
                         "candidate": "—" if c is None else "có"})
            continue
        for fname in COMPARED_FIELDS:
            if b.get(fname) != c.get(fname):
                rows.append({"case": name, "field": fname,
                             "baseline": b.get(fname), "candidate": c.get(fname)})
    return rows
