"""Dashboard deep-links for CEO-facing Telegram messages.

The web SPA serves at `PORT` (default 8765, see `server/app.py`) and a task's detail
lives at `/office?room=<room_id>` (the workroom the kanban card links to). Telegram
messages that report a task outcome append this link so the CEO can jump from the
notification to the full artifacts/timeline instead of retyping ids.

`MPM_WEB_BASE_URL` overrides the base (e.g. a Tailscale/LAN address so the link works
from a phone); default matches the local server. Only the BASE is configurable — the
path shape stays in code next to the SPA route it mirrors.
"""

from __future__ import annotations

import os
from urllib.parse import quote


def dashboard_base_url() -> str:
    """Base URL of the web dashboard, without a trailing slash."""
    base = os.environ.get("MPM_WEB_BASE_URL", "").strip() or "http://localhost:8765"
    return base.rstrip("/")


def workroom_url(task_id: str) -> str:
    """Deep-link to a task's workroom (same target as the kanban card's Link)."""
    from my_crew.runtime.office_room_append import room_for_task

    return f"{dashboard_base_url()}/office?room={quote(room_for_task(task_id))}"
