"""SSRF guard for `OPERATOR_WEBHOOK_URL` — validated at WRITE time (Connections UI), not
read time, because that is the only point a human enters the value in this codebase.

Before this module, `operator_channels._try_webhook` trusted the env value outright (see
its `# noqa: S310 — operator-supplied URL, not user input` comment) — true when the URL
could only be hand-edited into `.env`. Once the Connections screen can write it from the
web (this phase), the same value becomes attacker-reachable if a session is ever hijacked:
an internal URL turns the operator-notice webhook into a stored-SSRF / exfil sink that
fires on every escalation. Blocking it here, once, at the single write path, is cheaper
and more complete than teaching every future reader of the env var to re-check it.

https-only (no plaintext creds over http to an attacker-controlled MITM) + reject any
host that resolves to a non-globally-routable address: loopback, link-local (incl. the
169.254.169.254 cloud-metadata address), RFC1918 private, CGNAT (100.64.0.0/10),
unique-local IPv6 (fd00::/8), and anything else IANA has not delegated as public.

Checked via `ipaddress`'s `is_global`, an allowlist (not a denylist of the ranges we
happened to think of) — a denylist of `is_loopback or is_private or is_link_local or
is_reserved or is_multicast or is_unspecified` silently ALLOWS any range nobody added
explicitly, which is how CGNAT (100.64.0.0/10) slipped through in an earlier version of
this guard. `is_global` already excludes all of the above and stays correct as new
special-purpose ranges get registered, so the guard does not need updating every time
IANA reserves something new.

Called from two places: at WRITE time (Connections screen) and again at SEND time
(`operator_channels._try_webhook`, right before the POST) — DNS can rebind between a
save and a later send, so the write-time check alone is not sufficient.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.parse


class WebhookUrlBlocked(ValueError):
    """The URL failed the SSRF guard — message is user-facing (Vietnamese)."""


def assert_safe_webhook_url(url: str) -> None:
    """Raise WebhookUrlBlocked if `url` is not an https URL pointing at a public host.

    Resolves the hostname and rejects if ANY resolved address is non-public — mirrors
    `firecrawl_tool._assert_public_url`'s "reject if any" rule so a host with mixed
    public/private DNS answers cannot slip through on the public one.
    """
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme != "https":
        raise WebhookUrlBlocked("Webhook URL phải dùng https.")
    host = parsed.hostname
    if not host:
        raise WebhookUrlBlocked("Webhook URL không có host hợp lệ.")
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise WebhookUrlBlocked(f"Không phân giải được host {host!r}: {exc}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise WebhookUrlBlocked(
                f"Webhook URL bị từ chối: host {host!r} phân giải tới địa chỉ nội bộ/"
                f"loopback/metadata ({ip}) — chỉ chấp nhận host công khai."
            )


__all__ = ["WebhookUrlBlocked", "assert_safe_webhook_url"]
