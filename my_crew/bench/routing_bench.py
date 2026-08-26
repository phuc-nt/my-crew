"""Đo QUYẾT ĐỊNH của bộ định tuyến, offline và không tốn một lời gọi model nào.

Bộ định tuyến là thứ rẻ nhất và đồng thời rủi ro nhất trong hai lane: rẻ vì thuần
luật, rủi ro vì nó quyết CẢ chuyến chạy phía sau. Một ngưỡng bị chỉnh sai một chữ số
không làm test nào đỏ — nó chỉ lặng lẽ đẩy hàng loạt đề sang lane đắt hơn (hoặc tệ
hơn: sang lane rẻ hơn mà không đủ sức làm). Mode này biến đúng thứ đó thành một con số
so được giữa hai bản.

0 lời gọi model là điều kiện thiết kế, không phải hệ quả: `classify_brief`,
`sprint_refusal` và `route_signals` đều thuần luật, nên chạy được trong worktree của
một tag cũ mà không cần key, không cần mạng, không cần store. Đó chính là điều khiến
nó dùng được để so bản.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from my_crew.bench.brief_suite import ALL_CASES
from my_crew.bench.pipeline_bench import BriefCase

#: Bản của định dạng JSON mode này ghi ra. `compare_routing` từ chối so hai bản lệch
#: nhau — im lặng so nhầm hai định dạng khác nhau còn tệ hơn là không so được.
FORMAT_VERSION = 1


@dataclass(frozen=True)
class RouteDecision:
    """Bộ định tuyến quyết gì cho một đề, cùng số liệu nó dựa vào.

    Cùng bốn khoá với bản ghi `route_json` trong store (`mode`/`source`/`reason`/
    `signals`) — cố ý: cái đo offline và cái ghi lúc chạy thật phải nói cùng một thứ
    tiếng thì mới đối chiếu được với nhau."""

    case: str
    mode: str
    source: str
    reason: str
    signals: dict[str, int]


def decide(brief: str) -> tuple[str, str, str, dict[str, int]]:
    """Chạy đúng chuỗi quyết định mà `preview_assign_team_task` chạy, không hơn.

    Thứ tự ở đây là thứ tự CÓ THẨM QUYỀN, không phải thứ tự tuỳ ý: rào an toàn đứng
    trước tiền tố ép chế độ của CEO (tiền tố chọn lane, không gỡ rào), và tiền tố đứng
    trước bộ đoán. Đảo bất kỳ cặp nào cũng ra một hệ thống khác hẳn — nên nó được viết
    lại ở đây một lần, cạnh chỗ nó được đo.
    """
    from my_crew.agent.ops_assign_team_task import parse_pic_prefix
    from my_crew.agent.sprint_intake import (
        classify_brief,
        route_signals,
        sprint_refusal,
        strip_mode_prefix,
    )

    # Bóc tiền tố đúng THỨ TỰ của đường thật: `sprint:`/`team:` bọc cả đề nên bóc
    # trước, rồi mới tới `@<id> `/`@all ` bên trong. Bỏ bước thứ hai thì `brief_len`
    # của bench dài hơn đường thật đúng bằng độ dài tiền tố PIC — mà `brief_len` lại
    # là một trục được so và có ngưỡng, nên bench sẽ đo chính bản sao của nó.
    forced, after_mode = strip_mode_prefix(brief)
    _pic, stripped = parse_pic_prefix(after_mode)
    signals = route_signals(stripped)

    refusal = sprint_refusal(stripped)
    if refusal:
        return "team", "refusal", refusal, signals
    if forced:
        return forced, "prefix", f"CEO ép chế độ {forced!r}", signals

    is_sprint, reason = classify_brief(stripped)
    return ("sprint" if is_sprint else "team"), "heuristic", reason, signals


def bench_case(case: BriefCase) -> RouteDecision:
    mode, source, reason, signals = decide(case.goal)
    return RouteDecision(case=case.name, mode=mode, source=source, reason=reason,
                         signals=signals)


def run_suite(cases: tuple[BriefCase, ...] = ALL_CASES, *,
              repeats: int = 1) -> dict[str, Any]:
    """Chấm cả bộ đề. `repeats` > 1 là để KHẲNG ĐỊNH tính tất định.

    Bộ định tuyến thuần luật nên hai lượt phải khớp từng chữ. Không khớp nghĩa là có
    trạng thái ẩn đâu đó — và một bộ định tuyến có trạng thái ẩn thì mọi con số so bản
    phía sau đều vô nghĩa. Vì thế nó nổ chứ không cảnh báo."""
    first: dict[str, Any] | None = None
    for _ in range(max(1, repeats)):
        report = {case.name: asdict(bench_case(case)) for case in cases}
        if first is None:
            first = report
        elif report != first:
            raise RuntimeError("routing bench is non-deterministic between repeats")
    return {"format_version": FORMAT_VERSION, "schema": 1, "cases": first or {}}


#: Trục được so. `signals` nằm trong danh sách vì một thay đổi ngưỡng thường lộ ra ở
#: số liệu TRƯỚC khi nó đủ lớn để lật một quyết định — bắt được nó ở đây là bắt sớm
#: hơn một bản. `reason` cũng được so: cùng một quyết định vì một lý do khác vẫn là
#: một thay đổi hành vi cần người đọc nhìn thấy.
COMPARED_FIELDS = ("mode", "source", "reason", "signals")


def compare_routing(baseline: dict[str, Any],
                    candidate: dict[str, Any]) -> list[dict[str, Any]]:
    """Từng ô khác nhau giữa hai bản, phẳng, sẵn sàng in ra bảng.

    Từ chối so hai định dạng lệch bản: nếu một bản sau thêm trường mà `compare` cứ thế
    so tiếp, kết quả sẽ là một danh sách khác biệt trông như thay đổi hành vi trong khi
    thật ra chỉ là đổi định dạng — đúng loại kết luận sai mà cả mode này sinh ra để
    tránh."""
    b_ver = baseline.get("format_version", 0)
    c_ver = candidate.get("format_version", 0)
    if b_ver != c_ver:
        raise ValueError(
            f"routing report format_version lệch nhau ({b_ver} vs {c_ver}) — "
            "chạy lại baseline bằng bản script hiện tại trước khi so"
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
        for field in COMPARED_FIELDS:
            if b.get(field) != c.get(field):
                rows.append({"case": name, "field": field,
                             "baseline": b.get(field), "candidate": c.get(field)})
    return rows
