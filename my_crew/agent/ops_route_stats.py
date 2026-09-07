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
    return render_route_stats(aggregate_route_stats(routes))


def _ranked(counts: dict[str, int], labels: dict[str, str]) -> list[dict]:
    """Count dict → `[{id, label, count}]`, biggest first (stable, so ties keep first-seen
    order). Unknown ids keep their raw id as label rather than vanishing."""
    return [
        {"id": key, "label": labels.get(key, key), "count": count}
        for key, count in sorted(counts.items(), key=lambda kv: -kv[1])
    ]


def aggregate_route_stats(routes: list[tuple[dict, str]]) -> dict:
    """The routing retro as data — one dict the chat renderer and the web tab both read.

    Ids stay English (the store's vocabulary); every entry also carries the reader label
    from the same dicts `render_route_reason` uses, so the two surfaces can never name
    one lane two ways. `routes` is `TeamTaskStore.list_routes()` output.
    """
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

    from my_crew.runtime.task_failure_mode import (
        FAILURE_MODE_LABELS,
        GROUP_LABELS,
        failure_group_for,
    )

    failures = []
    by_group: dict[str, int] = {}
    for mode, count in sorted(by_failure.items(), key=lambda kv: -kv[1]):
        # A mode this release does not know (stamped by a newer one) keeps its raw id
        # and falls under "khác" — a count that quietly loses rows is worse than one
        # with an unlabelled line.
        group = failure_group_for(mode) or "khác"
        by_group[group] = by_group.get(group, 0) + count
        failures.append({
            "id": mode, "label": FAILURE_MODE_LABELS.get(mode, mode), "count": count,
            "group": group, "group_label": GROUP_LABELS.get(group, group),
        })

    return {
        "total": len(routes),
        "by_mode": _ranked(by_mode, _MODE_LABELS),
        "by_source": _ranked(by_source, _SOURCE_LABELS),
        "by_shape": _ranked(by_shape, _SHAPE_LABELS),
        # Tier order, not count order: "dễ / vừa / khó" is the axis the reader scans.
        "by_effort": [
            {"id": tier, "label": _EFFORT_LABELS[tier], "count": by_effort[tier],
             "dead_ends": dead_by_effort.get(tier, 0)}
            for tier in ("low", "medium", "high") if by_effort.get(tier)
        ],
        "by_failure": failures,
        "failure_groups": _ranked(by_group, GROUP_LABELS),
        "failed": sum(by_failure.values()),
        "dead_ends": dead_ends,
        "downgrades": by_source.get("downgrade", 0),
    }


def render_route_stats(stats: dict) -> str:
    """The chat rendering of `aggregate_route_stats` — plain lines, no markdown."""
    total = int(stats.get("total") or 0)
    if not total:
        return ("Chưa có bản ghi định tuyến nào. Các việc giao từ phiên bản trước v78 "
                "không lưu lại chế độ, nên chỉ việc giao mới mới được tính.")

    lines = [f"Định tuyến {total} việc gần nhất:"]
    for row in stats["by_mode"]:
        lines.append(f"  • {row['label']}: {row['count']} ({row['count'] * 100 // total}%)")

    lines.append("")
    lines.append("Ai quyết:")
    for row in stats["by_source"]:
        lines.append(f"  • {row['label']}: {row['count']}")

    if stats["by_shape"]:
        lines.append("")
        lines.append("Dạng đội (việc chạy đội):")
        for row in stats["by_shape"]:
            lines.append(f"  • {row['label']}: {row['count']}")

    if stats["by_effort"]:
        lines.append("")
        lines.append("Độ khó việc chạy nhanh (máy chấm lúc nhận việc):")
        for row in stats["by_effort"]:
            tail = f", {row['dead_ends']} bế tắc" if row["dead_ends"] else ""
            lines.append(f"  • {row['label']}: {row['count']}{tail}")

    if stats["by_failure"]:
        lines.append("")
        lines.append(_render_failure_modes(stats))

    downgrades = stats["downgrades"]
    dead_ends = stats["dead_ends"]
    if downgrades or dead_ends:
        lines.append("")
        lines.append("Bộ đoán chệch (đã được kéo về):")
        if downgrades:
            lines.append(f"  • {downgrades} việc đoán thừa về phía đội, hạ lại thành "
                         "chạy nhanh sau khi thấy kế hoạch thật")
        if dead_ends:
            lines.append(f"  • {dead_ends} việc chạy nhanh bế tắc, phải giao lại cho đội")
    return "\n".join(lines)


def _render_failure_modes(stats: dict) -> str:
    """"Kết cục thất bại" block: one line per mode, then the MAST-group split."""
    lines = [f"Kết cục thất bại ({stats['failed']} việc dừng không có kết quả):"]
    for row in stats["by_failure"]:
        lines.append(f"  • {row['label']}: {row['count']}")
    parts = [f"{g['label']} {g['count']}" for g in stats["failure_groups"]]
    lines.append("  Theo nhóm: " + " · ".join(parts))
    return "\n".join(lines)
