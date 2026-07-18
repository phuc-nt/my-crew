"""watch-task check logic (v6 M15) — track a PR/issue until it closes, remind on cadence.

A watch-task's params: {"target": "pr", "number": <int>, "note": <str optional>}. M15a
supports target="pr" only (issue-via-Jira lands in M15b). Each check reads the PR's current
state via `gh` and a CODE stop condition decides done — the LLM is NEVER asked "is it
finished?". The reminder text is deterministic prose built here; no model call is needed for
a watch check, so a watch-task costs no tokens (only report/qa tasks in M15b will).

`check_watch` returns a WatchResult telling the runner what to do: keep watching (post a
reminder or stay quiet), or stop (done). It performs the READ only; POSTING the reminder is
the runner's job through the Action Gateway (so audit/dedup/kill-switch apply).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

#: A watch with no explicit deadline still stops eventually (R1: no task runs forever).
DEFAULT_DEADLINE_DAYS = 14


@dataclass(frozen=True)
class WatchResult:
    done: bool
    reason: str  # human summary for history + the stop/reminder message
    remind: bool  # runner should post a reminder this check (only when not done)


def _pr_number(params: dict[str, Any]) -> int:
    try:
        return int(params["number"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"watch-task thiếu 'number' hợp lệ: {params!r}") from exc


def _deadline_passed(created_at: str, deadline_days: int, *, now: datetime | None = None) -> bool:
    """True when the task is older than its deadline — a hard stop so a watch on a PR that
    never merges does not linger forever."""
    try:
        created = datetime.fromisoformat(created_at)
    except (ValueError, TypeError):
        return False
    current = now or datetime.now(UTC)
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return (current - created).days >= deadline_days


def check_pr_watch(
    params: dict[str, Any], *, repo: str, created_at: str, run_gh, now: datetime | None = None,
) -> WatchResult:
    """Read the PR's current state and decide done/remind. `run_gh` is injected so tests
    stub the CLI. A PR that is MERGED or CLOSED ⇒ done; still open ⇒ remind unless the
    deadline passed (then done with a timeout note)."""
    number = _pr_number(params)
    deadline_days = int(params.get("deadline_days") or DEFAULT_DEADLINE_DAYS)
    rows = run_gh(
        ["pr", "view", str(number), "--repo", repo, "--json", "state,title,mergedAt"]
    )
    data = rows if isinstance(rows, dict) else {}
    state = str(data.get("state") or "").upper()
    title = str(data.get("title") or f"PR #{number}")

    if not state:
        # `gh` returned no state (e.g. exit 0 but auth expired / empty body): treat as a
        # CONTENT ERROR, not "still open" — a silently-empty read must bump the stall streak,
        # not spam a bogus daily reminder (review L3).
        raise ValueError(f"gh không trả trạng thái cho PR #{number} (phản hồi rỗng?)")
    if state == "MERGED":
        return WatchResult(True, f"PR #{number} ({title}) đã MERGE. Hoàn tất theo dõi.", False)
    if state == "CLOSED":
        return WatchResult(True, f"PR #{number} ({title}) đã bị ĐÓNG (không merge). Dừng theo dõi.",
                           False)
    if _deadline_passed(created_at, deadline_days, now=now):
        return WatchResult(
            True,
            f"PR #{number} ({title}) vẫn mở sau {deadline_days} ngày — hết hạn theo dõi, "
            "mình dừng.",
            False,
        )
    note = str(params.get("note") or "").strip()
    suffix = f" — {note}" if note else ""
    return WatchResult(
        False, f"⏳ Nhắc: PR #{number} ({title}) vẫn đang mở, chưa merge{suffix}.", True
    )


def watch_reminder_dedup(task_id: int, *, on: date | None = None) -> str:
    """One reminder per task per DAY: the gateway dedup keys on (task, calendar day), so
    two ticks in the same day (or a restart) never double-remind."""
    day = (on or datetime.now(UTC).date()).isoformat()
    return f"watch-task-remind:{task_id}:{day}"
