"""SSRF guard for OPERATOR_WEBHOOK_URL, validated at write time (Connections UI).

Same "reject if any resolved address is non-public" contract as firecrawl_tool's
`_assert_public_url` (see tests/test_firecrawl_tool.py), plus an https-only requirement
since this URL later carries operator-notice content, not just a read-only scrape target.
"""

from __future__ import annotations

import pytest

from my_crew.runtime.webhook_url_guard import WebhookUrlBlocked, assert_safe_webhook_url


def test_https_public_host_accepted():
    assert_safe_webhook_url("https://example.com/hook")  # no raise


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/hook",  # plaintext http rejected outright
        "https://127.0.0.1/hook",  # loopback
        "https://[::1]/hook",  # loopback v6
        "https://169.254.169.254/latest/meta-data/",  # cloud metadata (link-local)
        "https://169.254.0.1/hook",  # link-local
        "https://10.0.0.5/hook",  # RFC1918
        "https://172.16.0.5/hook",  # RFC1918
        "https://192.168.1.5/hook",  # RFC1918
        "https://localhost/hook",  # resolves to loopback
        "https://100.64.0.1/hook",  # CGNAT (RFC6598) — missed by the old denylist form
        "https://100.100.100.1/hook",  # CGNAT, another address in the same /10
    ],
)
def test_blocked_targets_rejected(url):
    with pytest.raises(WebhookUrlBlocked):
        assert_safe_webhook_url(url)


def test_no_host_rejected():
    with pytest.raises(WebhookUrlBlocked):
        assert_safe_webhook_url("https:///nohost")


def test_unresolvable_host_rejected():
    with pytest.raises(WebhookUrlBlocked):
        assert_safe_webhook_url("https://this-host-should-not-exist.invalid/hook")


def test_ipv4_mapped_ipv6_private_address_rejected(monkeypatch):
    """`::ffff:10.0.0.5` is IPv4-mapped IPv6 for a private address — `is_global` must
    see through the mapping and reject it, same as the bare v4 form would."""
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *a, **k: [(None, None, None, None, ("::ffff:10.0.0.5", 0, 0, 0))],
    )
    with pytest.raises(WebhookUrlBlocked):
        assert_safe_webhook_url("https://example.com/hook")
