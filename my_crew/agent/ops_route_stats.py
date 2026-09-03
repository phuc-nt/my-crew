"""Read-only routing retro for chat (v78): `route_stats`.

Bộ định tuyến sprint/team quyết mỗi lần giao việc mà không ai nhìn thấy: quyết định
nằm trong `route_json` cạnh outcome, nhưng chưa có mặt nào đọc nó ra. Câu hỏi duy
nhất lệnh này tồn tại để trả lời là "mình còn đẩy việc một người vào bộ máy đội
không?" — và câu hỏi ngược lại, "sprint có đang nhận nhầm việc quá tầm không?".

Hai con số quan trọng nhất, cả hai đều là dấu bộ định tuyến ĐOÁN SAI và đã được lưới
đỡ kéo về:
  - `downgrade`: đoán sai về phía team, `downgrade_to_sprint` kéo lại — rẻ, chỉ mất
    một lượt decompose đã trả tiền.
  - `dead_end`: đoán sai về phía sprint, `sprint_dead_end` kéo lại — đắt hơn, vì việc
    đã chạy hết một chuyến sprint rồi mới lộ.

Thuần đọc store, không gọi model, không ghi gì.
"""

from __future__ import annotations

#: Dùng chung với `render_route_reason` chứ không chép lại: hai chỗ cùng đặt tên một
#: khái niệm cho cùng một người đọc, lệch nhau là lỗi người dùng thấy được.
from my_crew.agent.sprint_intake import _MODE_LABELS

#: Nguồn quyết định → nhãn cho người đọc. Khớp đúng các giá trị `source` mà
#: `_plan_for_brief` ghi ra. `dead_end` KHÔNG còn nằm trong khoá `source` (H1 fix:
#: đè `source` xoá mất nguồn escalation gốc) — giờ là cờ riêng `route["dead_end"]`,
#: đếm riêng bên dưới thay vì qua `_SOURCE_LABELS`/`by_source`.
_SOURCE_LABELS = {
    "prefix": "CEO ép bằng tiền tố",
    "refusal": "rào an toàn (sprint không nhận)",
    "heuristic": "bộ đoán tự động",
    "downgrade": "hạ từ team xuống sprint",
    "upgrade": "đã nâng lên đội (mang theo bối cảnh)",
    "unmeasurable": "kế hoạch đội không đo được → chạy nhanh",
    "shape": "kế hoạch không thuộc dạng đội nào → chạy nhanh",
}

#: Dạng đội (context-crew) → nhãn người đọc. Khớp `CREW_SHAPES` + `CUSTOM_SHAPE` bên
#: `crew_shape`; chỉ route team mới mang khoá `shape`.
_SHAPE_LABELS = {
    # Killed by the bench (a fan-out plan is a sprint now); the label stays so route
    # rows written while the shape existed still count under their own name.
    "fanout": "toả ra / gộp lại",
    "do_review": "làm + soát độc lập",
    "permission_chain": "chuỗi quyền",
    "custom": "ngoài các dạng đội (CEO ép / rào an toàn)",
}

#: Bậc độ khó intake chấm cho việc chạy nhanh → nhãn người đọc. Việc chạy đội không
#: qua intake nên không có bậc; chúng bị bỏ khỏi bảng này thay vì gộp vào "medium".
_EFFORT_LABELS = {"low": "dễ", "medium": "vừa", "high": "khó"}


def run_route_stats(slots: dict[str, str]) -> str:
    from my_crew.runtime.team_task_paths import team_tasks_db_path
    from my_crew.runtime.team_task_store import TeamTaskStore

    store = TeamTaskStore(team_tasks_db_path())
    try:
        routes = store.list_routes()
    finally:
        store.close()

    if not routes:
        return ("Chưa có bản ghi định tuyến nào. Các việc giao từ phiên bản trước v78 "
                "không lưu lại chế độ, nên chỉ việc giao mới mới được tính.")

    by_mode: dict[str, int] = {}
    by_source: dict[str, int] = {}
    # `route["dead_end"] is True` chỉ được đóng vào lúc `_mark_route_dead_end` chạy,
    # tức là việc đã dừng hẳn — nên không cần lọc thêm theo trạng thái task. Cờ RIÊNG,
    # không còn tái dùng khoá `source` (H1 fix: đè `source` xoá mất nguồn escalation
    # gốc mà `_manager_task_outcome_prefix` cần để báo đúng "(nguồn: ...)" cho owner).
    dead_ends = 0
    # Đếm theo bậc độ khó, kèm số bế tắc của từng bậc. Đây là con số phải có TRƯỚC khi
    # cho `effort` quyền đổi lane: "đề chấm khó bế tắc bao nhiêu phần trăm" chỉ trả lời
    # được khi bậc và kết cục nằm cùng một bản ghi.
    by_effort: dict[str, int] = {}
    dead_by_effort: dict[str, int] = {}
    # Dạng đội của các việc chạy đội — câu hỏi bench H1–H3 cần: "mỗi dạng chạy bao
    # nhiêu việc". Route team trước context-crew không có khoá này và bị bỏ qua.
    by_shape: dict[str, int] = {}
    # Kết cục thất bại, do `_mark_route_failure` đóng lúc việc dừng hẳn. Đếm theo
    # mode và theo nhóm MAST để retro trả lời được "lỗi ở đề, ở soát, hay ở máy".
    by_failure: dict[str, int] = {}
    for route, _ in routes:
        mode = str(route.get("mode") or "?")
        source = str(route.get("source") or "?")
        is_dead_end = route.get("dead_end") is True
        by_mode[mode] = by_mode.get(mode, 0) + 1
        by_source[source] = by_source.get(source, 0) + 1
        shape = str(route.get("shape") or "").strip()
        if mode == "team" and shape:
            by_shape[shape] = by_shape.get(shape, 0) + 1
        if is_dead_end:
            dead_ends += 1
        failure = str(route.get("failure_mode") or "").strip()
        if failure:
            by_failure[failure] = by_failure.get(failure, 0) + 1
        effort = str(route.get("effort") or "").strip().lower()
        if effort in _EFFORT_LABELS:
            by_effort[effort] = by_effort.get(effort, 0) + 1
            if is_dead_end:
                dead_by_effort[effort] = dead_by_effort.get(effort, 0) + 1

    total = len(routes)
    lines = [f"Định tuyến {total} việc gần nhất:"]
    for mode, count in sorted(by_mode.items(), key=lambda kv: -kv[1]):
        label = _MODE_LABELS.get(mode, mode)
        lines.append(f"  • {label}: {count} ({count * 100 // total}%)")

    lines.append("")
    lines.append("Ai quyết:")
    for source, count in sorted(by_source.items(), key=lambda kv: -kv[1]):
        lines.append(f"  • {_SOURCE_LABELS.get(source, source)}: {count}")

    if by_shape:
        lines.append("")
        lines.append("Dạng đội (việc chạy đội):")
        for shape, count in sorted(by_shape.items(), key=lambda kv: -kv[1]):
            lines.append(f"  • {_SHAPE_LABELS.get(shape, shape)}: {count}")

    if by_effort:
        lines.append("")
        lines.append("Độ khó việc chạy nhanh (máy chấm lúc nhận việc):")
        for effort in ("low", "medium", "high"):
            count = by_effort.get(effort, 0)
            if not count:
                continue
            stuck = dead_by_effort.get(effort, 0)
            tail = f", {stuck} bế tắc" if stuck else ""
            lines.append(f"  • {_EFFORT_LABELS[effort]}: {count}{tail}")

    if by_failure:
        lines.append("")
        lines.append(_render_failure_modes(by_failure))

    downgrades = by_source.get("downgrade", 0)
    if downgrades or dead_ends:
        lines.append("")
        lines.append("Bộ đoán chệch (đã được kéo về):")
        if downgrades:
            lines.append(f"  • {downgrades} việc đoán thừa về phía đội, hạ lại thành "
                         "chạy nhanh sau khi thấy kế hoạch thật")
        if dead_ends:
            lines.append(f"  • {dead_ends} việc chạy nhanh bế tắc, phải giao lại cho đội")
    return "\n".join(lines)



def _render_failure_modes(by_failure: dict[str, int]) -> str:
    """"Kết cục thất bại" block: one line per mode, then the MAST-group split.

    Modes this release does not know (stamped by a newer one) keep their raw id and
    fall under "khác" in the group split rather than being dropped — a count that
    quietly loses rows is worse than one with an unlabelled line.
    """
    from my_crew.runtime.task_failure_mode import (
        FAILURE_MODE_LABELS,
        GROUP_LABELS,
        failure_group_for,
    )

    failed = sum(by_failure.values())
    lines = [f"Kết cục thất bại ({failed} việc dừng không có kết quả):"]
    by_group: dict[str, int] = {}
    for mode, count in sorted(by_failure.items(), key=lambda kv: -kv[1]):
        lines.append(f"  • {FAILURE_MODE_LABELS.get(mode, mode)}: {count}")
        group = failure_group_for(mode) or "khác"
        by_group[group] = by_group.get(group, 0) + count
    parts = [f"{GROUP_LABELS.get(g, g)} {n}" for g, n in
             sorted(by_group.items(), key=lambda kv: -kv[1])]
    lines.append("  Theo nhóm: " + " · ".join(parts))
    return "\n".join(lines)
