"""Google Workspace READ tools via the `gws` CLI (v39 #1) — Gmail / Calendar / Drive.

Agents could already read Google Sheets (hr-pack); this opens the other Workspace context
an office/admin/researcher needs: unread-inbox summary, upcoming calendar, and Drive file
listing. All READ — spawned through the `gws` CLI (like `gh`/Sheets), NOT the Action
Gateway (reads never mutate). The credential is the CLI's own OAuth; nothing new in .env.

Safety: the LLM never supplies an argv. Each helper builds a FIXED argv from
`_READ_ALLOWLIST` and injects only a data parameter (a query/max-results), json-escaped —
so a crafted "argument" can never turn a read into a write/delete. Results are bounded and
returned as short text; a CLI failure degrades to a "(gws … lỗi)" string (like Firecrawl)
so one flaky read never crashes the loop.
"""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import UTC

from my_crew.runtime.content_caps import TOOL_RESULT_CHARS, cap_with_footer

logger = logging.getLogger(__name__)

_TIMEOUT_S = 60

#: Google payloads can be large — bound them, and say so when the bound bites.
_MORE_HINT = "Kết quả dài hơn khung hiển thị — thu hẹp truy vấn hoặc khoảng thời gian để xem đủ."


def _bounded_json(data: dict) -> str:
    return cap_with_footer(json.dumps(data, ensure_ascii=False), TOOL_RESULT_CHARS, _MORE_HINT)

#: The ONLY gws read invocations these tools may make, as fixed argv prefixes. A helper
#: picks one and appends a json --params it built from a bounded data arg — never an
#: LLM-supplied argv. Read-only helper subcommands (`+triage`, `+agenda`) + list/get.
_READ_ALLOWLIST: dict[str, list[str]] = {
    "gmail": ["gmail", "+triage"],
    "calendar": ["calendar", "+agenda"],
    "calendar_events": ["calendar", "events", "list"],
    "drive": ["drive", "files", "list"],
    "tasks_list": ["tasks", "tasks", "list"],
}

#: Verbs that must never appear in a read argv (defense in depth over the fixed table).
_FORBIDDEN_TOKENS = ("send", "insert", "create", "update", "delete", "trash", "patch",
                     "+write", "+send", "+reply", "share", "permission")


class GwsReadError(RuntimeError):
    """A gws read failed (CLI missing, OAuth expired, bad response)."""


def _run(prefix_key: str, params: dict | None = None) -> dict:
    """Run one allowlisted gws read; return the parsed JSON object. Raises GwsReadError."""
    argv = ["gws", *_READ_ALLOWLIST[prefix_key]]
    if any(tok in _FORBIDDEN_TOKENS for tok in argv):  # invariant guard on the fixed table
        raise GwsReadError(f"read argv {argv!r} contains a non-read verb — refused.")
    if params is not None:
        argv += ["--params", json.dumps(params)]
    # The +triage/+agenda helpers default to a TABLE; force JSON so parsing is stable.
    argv += ["--format", "json"]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=_TIMEOUT_S, check=False)
    except FileNotFoundError as exc:
        raise GwsReadError("gws CLI chưa cài — cài Google Workspace CLI để đọc Google.") from exc
    except subprocess.TimeoutExpired as exc:
        raise GwsReadError("gws đọc quá lâu (timeout).") from exc
    if proc.returncode != 0:
        raise GwsReadError(f"gws đọc lỗi: {(proc.stderr or proc.stdout).strip()[:200]}")
    out = proc.stdout
    brace = out.find("{")
    if brace == -1:
        raise GwsReadError(f"gws không trả JSON: {out.strip()[:200]}")
    return json.loads(out[brace:])


def gmail_triage() -> str:
    """Unread-inbox summary (sender · subject · date). Bounded text for the loop."""
    data = _run("gmail")
    return _bounded_json(data)


def calendar_agenda() -> str:
    """Upcoming events across the user's calendars. Bounded text."""
    data = _run("calendar")
    return _bounded_json(data)


def calendar_events_window(query: str = "", days: int = 14) -> list[dict]:
    """Upcoming events on the PRIMARY calendar in the next `days` days, as raw event
    dicts (id/summary/start/end). `query` rides the Calendar API free-text `q`. Read-only
    lookup for the v60 edit/delete chat commands — the resolver matches titles on top."""
    from datetime import datetime, timedelta

    now = datetime.now().astimezone()
    params: dict = {
        "calendarId": "primary",
        "timeMin": now.isoformat(timespec="seconds"),
        "timeMax": (now + timedelta(days=max(1, min(days, 60)))).isoformat(timespec="seconds"),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": 50,
    }
    q = (query or "").strip()[:200]
    if q:
        params["q"] = q
    data = _run("calendar_events", params=params)
    items = data.get("items", [])
    return [e for e in items if isinstance(e, dict)]


#: Số dòng tối đa mỗi bản kê task — briefing/weekly là bản tin ngắn, không phải dump.
_TASK_LINES = 15
#: Trần một trang task. Mặc định của API nhỏ (20) và trang bị cắt TRƯỚC khi lọc phía
#: mình, nên thiếu trần này thì một danh sách bận sẽ đẩy hết task đã xong ra khỏi trang
#: đầu và weekly báo "(không có)" — sai một cách im lặng, không phải lỗi.
_TASK_PAGE = 100


def _task_lines(items: list, keep) -> str:
    """Render task items thành "- tiêu đề (hạn …)". `keep` lọc theo từng nhu cầu.

    Google Tasks cho phép task rỗng tiêu đề mà chỉ có `notes` (data thật của CEO có),
    nên tiêu đề rơi về notes trước khi bỏ qua — nếu không bản kê sẽ có dòng cụt.
    """
    lines: list[str] = []
    for item in items:
        if not isinstance(item, dict) or not keep(item):
            continue
        title = (item.get("title") or "").strip() or (item.get("notes") or "").strip()
        if not title:
            continue
        due = (item.get("due") or "")[:10]
        lines.append(f"- {title[:100]}" + (f" (hạn {due})" if due else ""))
        if len(lines) >= _TASK_LINES:
            break
    return "\n".join(lines) if lines else "(không có)"


def tasks_pending() -> str:
    """Google Tasks chưa xong trên danh sách mặc định — bản kê ngắn cho briefing."""
    data = _run("tasks_list", {"tasklist": "@default", "showCompleted": False,
                               "maxResults": _TASK_PAGE})
    return _task_lines(data.get("items", []), lambda t: t.get("status") != "completed")


def tasks_completed(days: int = 7) -> str:
    """Task đã xong trong `days` ngày qua — nguyên liệu cho weekly review.

    `completedMin` chỉ thu hẹp phía server chứ không loại hết task chưa xong khỏi
    response, nên lọc `status == "completed"` lần nữa ở đây.
    """
    from datetime import datetime, timedelta

    since = datetime.now(UTC) - timedelta(days=max(1, min(days, 90)))
    data = _run("tasks_list", {
        "tasklist": "@default",
        "showCompleted": True,
        "showHidden": True,
        "maxResults": _TASK_PAGE,
        "completedMin": since.isoformat(timespec="seconds").replace("+00:00", "Z"),
    })
    return _task_lines(data.get("items", []), lambda t: t.get("status") == "completed")


def drive_list(query: str = "") -> str:
    """List Drive files (metadata: name/id/link/modified) — NOT file contents. A bounded
    `query` narrows the search; empty lists recent files."""
    params: dict = {"pageSize": 20, "fields": "files(id,name,mimeType,modifiedTime,webViewLink)"}
    q = (query or "").strip()[:200]
    if q:
        params["q"] = f"name contains '{q.replace(chr(39), '')}'"
    data = _run("drive", params)
    return _bounded_json(data)
