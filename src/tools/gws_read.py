"""Google Workspace READ tools via the `gws` CLI (v39 #1) — Gmail / Calendar / Drive.

Agents could already read Google Sheets (hr-pack); this opens the other Workspace context
an office/admin/researcher needs: unread-inbox summary, upcoming calendar, and Drive file
listing. All READ — spawned through the `gws` CLI (like `gh`/Sheets), NOT the Action
Gateway (reads never mutate). The credential is the CLI's own OAuth; nothing new in .env.

Safety: the LLM never supplies an argv. Each helper builds a FIXED argv from
`_READ_ALLOWLIST` and injects only a data parameter (a query/max-results), json-escaped —
so a crafted "argument" can never turn a read into a write/delete. Results are bounded and
returned as short text; a CLI failure degrades to a "(gws … lỗi)" string (like Firecrawl /
OpenAlex) so one flaky read never crashes the loop.
"""

from __future__ import annotations

import json
import logging
import subprocess

logger = logging.getLogger(__name__)

_TIMEOUT_S = 60
#: Cap on the text handed back to the loop — Google payloads can be large; keep bounded.
_MAX_CHARS = 6000

#: The ONLY gws read invocations these tools may make, as fixed argv prefixes. A helper
#: picks one and appends a json --params it built from a bounded data arg — never an
#: LLM-supplied argv. Read-only helper subcommands (`+triage`, `+agenda`) + list/get.
_READ_ALLOWLIST: dict[str, list[str]] = {
    "gmail": ["gmail", "+triage"],
    "calendar": ["calendar", "+agenda"],
    "drive": ["drive", "files", "list"],
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
    return json.dumps(data, ensure_ascii=False)[:_MAX_CHARS]


def calendar_agenda() -> str:
    """Upcoming events across the user's calendars. Bounded text."""
    data = _run("calendar")
    return json.dumps(data, ensure_ascii=False)[:_MAX_CHARS]


def drive_list(query: str = "") -> str:
    """List Drive files (metadata: name/id/link/modified) — NOT file contents. A bounded
    `query` narrows the search; empty lists recent files."""
    params: dict = {"pageSize": 20, "fields": "files(id,name,mimeType,modifiedTime,webViewLink)"}
    q = (query or "").strip()[:200]
    if q:
        params["q"] = f"name contains '{q.replace(chr(39), '')}'"
    data = _run("drive", params)
    return json.dumps(data, ensure_ascii=False)[:_MAX_CHARS]
