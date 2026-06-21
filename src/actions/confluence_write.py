"""Confluence write — create the detail report page via the Action Gateway.

Slice 2 mutation: a new page per run in the configured space. Goes through
`ActionGateway.execute` (allowlist already permits `confluence:createPage`), so
hard-deny / dry-run / rate-limit / idempotency / audit all apply.

The Confluence MCP server returns human-readable text blocks (not JSON), e.g.
`📄 Page ID: 131273` and `🔗 View page: /spaces/MPM/pages/131273/...` (verified
2026-06-21). We parse the page id + relative path from those blocks and build an
absolute URL, falling back to constructing one from site + space + id.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from src.actions.action_gateway import ActionGateway, GatewayResult
from src.adapters.mcp_adapter import call_tool
from src.config.reporting_config import get_reporting_config

logger = logging.getLogger(__name__)

_PAGE_ID_RE = re.compile(r"Page ID:\s*(\d+)")
_VIEW_PATH_RE = re.compile(r"(/spaces/\S+)")


@dataclass(frozen=True)
class ConfluencePage:
    page_id: str | None
    url: str | None


def _blocks_text(result: Any) -> str:
    """Flatten the MCP text-block result into one string for parsing."""
    if isinstance(result, list):
        parts = []
        for b in result:
            if isinstance(b, dict) and "text" in b:
                parts.append(str(b["text"]))
            else:
                parts.append(str(b))
        return "\n".join(parts)
    return str(result)


def parse_created_page(
    result: Any, *, site_name: str | None, space_key: str | None
) -> ConfluencePage:
    """Extract page id + absolute URL from a createPage result.

    URL preference: the `/spaces/...` path from the response (prefixed with the
    site's /wiki base); else build `/wiki/spaces/<key>/pages/<id>` from parts.
    """
    text = _blocks_text(result)
    page_id = None
    m = _PAGE_ID_RE.search(text)
    if m:
        page_id = m.group(1)

    base = f"https://{site_name}/wiki" if site_name else ""
    url = None
    pm = _VIEW_PATH_RE.search(text)
    if pm and base:
        url = base + pm.group(1)
    elif page_id and base and space_key:
        url = f"{base}/spaces/{space_key}/pages/{page_id}"
    elif pm:
        url = pm.group(1)  # relative, better than nothing

    return ConfluencePage(page_id=page_id, url=url)


def _create_page_handler(action: dict[str, Any]) -> str:
    """Gateway Handler: create the Confluence page. Returns a short summary."""
    cfg = get_reporting_config()
    args = action.get("args", {})
    result = call_tool(cfg.confluence_server, "createPage", args)
    page = parse_created_page(
        result, site_name=cfg.atlassian_site_name, space_key=cfg.confluence_space_key
    )
    return f"created page id={page.page_id} url={page.url}"


def create_report_page(
    title: str,
    body_storage: str,
    *,
    gateway: ActionGateway,
    report_date: str,
    rationale: str = "",
) -> tuple[GatewayResult, ConfluencePage | None]:
    """Create the detail report page through the gateway.

    Returns the gateway result plus the parsed page (id + URL) when executed.
    Idempotent per (space, date) so a re-run the same day does not duplicate.
    """
    cfg = get_reporting_config()
    space_id = cfg.confluence_space_id
    if not space_id:
        raise RuntimeError("CONFLUENCE_SPACE_ID is not set (in .env).")
    if not body_storage.strip():
        raise ValueError("Refusing to create an empty report page.")

    action = {
        "type": "mcp_tool",
        "server": "confluence",
        "tool": "createPage",
        "args": {"spaceId": space_id, "title": title, "content": body_storage},
        "dedup_hint": f"confluence-report:{cfg.confluence_space_key}:{report_date}",
    }
    result = gateway.execute(action, handler=_create_page_handler, rationale=rationale)

    page = None
    if result.status == "executed":
        # Re-parse from the handler summary so the caller gets the URL.
        m = re.search(r"url=(\S+)", result.summary)
        idm = re.search(r"id=(\S+)", result.summary)
        page = ConfluencePage(
            page_id=idm.group(1) if idm else None,
            url=m.group(1) if m and m.group(1) != "None" else None,
        )
    return result, page
