"""Read-only team-task board for chat (v63): `list_team_tasks`.

Fixes the v61 UAT gap where "liệt kê các thẻ việc" fell through to unsupported (the
only `list_tasks` command covers an agent's PER-AGENT recurring tasks) and doubles as
the retro-metrics surface the review-policy calibration needs: per task, the listing
shows step progress, how many peer-review rounds ran and how many minted a rework
(mỗi rework = một lần soát trượt), the cost so far, and whether the task is waiting on
the CEO (stalled / draft awaiting confirm). Pure store reads — no LLM, no writes.
"""

from __future__ import annotations

#: Status → CEO-facing label. `planning` drafts and `stalled` tasks are the two
#: "waiting on a decision" states the listing must make impossible to miss.
_STATUS_LABELS = {
    "planning": "nháp CHỜ XÁC NHẬN",
    "open": "đang chạy",
    "running": "đang chạy",
    "stalled": "BỊ DỪNG — chờ xử lý",
    "done": "xong",
}


def run_list_team_tasks(slots: dict[str, str]) -> str:
    from my_crew.runtime.team_task_paths import team_tasks_db_path
    from my_crew.runtime.team_task_store import TeamTaskStore

    store = TeamTaskStore(team_tasks_db_path())
    try:
        tasks = store.list_recent_tasks(limit=15, include_planning=True)
        # sum_cost = steps + decompose + aggregate — `cost_usd_total` alone would
        # under-report (it carries step costs only).
        costs = {t.id: store.sum_cost(t.id) for t in tasks}
    finally:
        store.close()
    if not tasks:
        return "Chưa có thẻ việc nhóm nào."

    lines = ["Thẻ việc nhóm gần đây:"]
    waiting = 0
    for t in tasks:
        work = [s for s in t.steps if s.step_type == "work"]
        reviews = [s for s in t.steps if s.step_type == "review"]
        reworks = [s for s in t.steps if s.step_type == "rework"]
        done = len([s for s in t.steps if s.status == "done"])
        label = _STATUS_LABELS.get(t.status, t.status)
        if t.status in ("planning", "stalled"):
            waiting += 1
        retro = f"{done}/{len(t.steps)} bước"
        if reviews:
            retro += f", {len(reviews)} lượt soát/{len(reworks)} lần sửa"
        cost = costs.get(t.id, 0.0)
        if cost:
            retro += f", ${cost:.3f}"
        pic = f" · PIC {t.pic_id}" if t.pic_id else ""
        manual = " · để CEO duyệt" if t.require_ceo_approval else ""
        lines.append(
            f"- `{t.id}` {t.title[:60]} — {label} ({retro}, {len(work)} việc chính{pic}{manual})"
        )
    if waiting:
        lines.append(
            f"\n⚠️ {waiting} thẻ đang chờ quyết định (xác nhận nháp, hoặc "
            "accept/retry/drop cho việc bị dừng)."
        )
    return "\n".join(lines)
