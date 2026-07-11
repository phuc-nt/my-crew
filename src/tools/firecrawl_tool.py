"""Firecrawl scrape — fetch a URL's full content as markdown via a local self-hosted Firecrawl.

This is the capability the codebase deliberately withheld from `web_search_tool.py` (which is
snippets-only: "NEVER a follow-up GET to any result URL"). Fetching a whole page is riskier —
the returned content is UNTRUSTED (prompt-injection surface), so this tool:

- is READ-only (it fetches, never writes; every mutation still goes through the Action Gateway);
- blocks SSRF targets AT SOURCE (localhost / loopback / private / link-local / cloud-metadata),
  so an agent cannot use Firecrawl as a pivot to reach internal services;
- degrades to a no-op when `FIRECRAWL_BASE_URL` is empty (Docker offline / not deployed) — the
  caller sees `available() == False` and skips it, no crash.

Stdlib-only HTTP (`urllib.request`), matching the `web_search_tool` convention (2 simple REST
calls do not warrant an SDK/httpx dependency). The returned markdown must be treated as untrusted
content by callers (wrap/quarantine before it reaches a prompt) exactly like a search result.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import urllib.parse
import urllib.request
from dataclasses import dataclass

_TIMEOUT_S = 60


class FirecrawlBlocked(RuntimeError):
    """A scrape target was refused by the SSRF guard (private/loopback/metadata host)."""


@dataclass(frozen=True)
class FirecrawlConfig:
    base_url: str | None  # e.g. http://localhost:3002 (env: FIRECRAWL_BASE_URL); "" ⇒ off
    api_key: str | None  # self-host no-auth → any dummy (env: FIRECRAWL_API_KEY)

    def available(self) -> bool:
        return bool(self.base_url)


@dataclass(frozen=True)
class ScrapeResult:
    url: str
    title: str
    status_code: int
    markdown: str


def _assert_public_url(url: str) -> None:
    """Reject SSRF targets AT SOURCE (guide §4.3): the agent must not scrape internal hosts.

    Blocks non-http(s) schemes, and any host that resolves to a loopback / private / link-local
    / reserved (incl. cloud-metadata 169.254.169.254) address. This runs BEFORE the Firecrawl
    call so even a self-hosted Firecrawl (no built-in SSRF protection) cannot be a pivot.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise FirecrawlBlocked(f"chỉ scrape http/https, got scheme {parsed.scheme!r}.")
    host = parsed.hostname
    if not host:
        raise FirecrawlBlocked(f"URL không có host: {url!r}.")
    # Resolve every address the host maps to and reject if ANY is non-public.
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise FirecrawlBlocked(f"không phân giải được host {host!r}: {exc}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_loopback or ip.is_private or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified
        ):
            raise FirecrawlBlocked(
                f"scrape bị chặn (SSRF guard): host {host!r} → {ip} là địa chỉ nội bộ/loopback."
            )


def scrape_url(
    url: str, config: FirecrawlConfig, *, only_main_content: bool = True
) -> ScrapeResult:
    """POST /v1/scrape → markdown. Raises FirecrawlBlocked on an SSRF target, RuntimeError on
    a non-2xx / `success:false` response. The target URL is SSRF-checked before any request."""
    if not config.available():
        raise RuntimeError("Firecrawl chưa cấu hình (FIRECRAWL_BASE_URL rỗng) — tính năng tắt.")
    _assert_public_url(url)  # SSRF guard at source

    payload = json.dumps(
        {"url": url, "formats": ["markdown"], "onlyMainContent": only_main_content}
    ).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    req = urllib.request.Request(
        f"{config.base_url}/v1/scrape", data=payload, headers=headers, method="POST",
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:  # noqa: S310 — validated http(s)
        body = json.loads(resp.read().decode("utf-8"))
    if not body.get("success"):
        raise RuntimeError(f"firecrawl scrape failed: {body}")
    data = body.get("data", {})
    meta = data.get("metadata", {})
    return ScrapeResult(
        url=str(meta.get("sourceURL", url)),
        title=str(meta.get("title", "")),
        status_code=int(meta.get("statusCode", 0) or 0),
        markdown=str(data.get("markdown", "")),
    )
