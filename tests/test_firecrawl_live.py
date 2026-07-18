"""v20.5: Firecrawl LIVE test — real scrape through the self-hosted container.

Skips cleanly when the local Firecrawl (http://localhost:3002) is not reachable, so CI without
the container passes. Proves the real fetch path: a public URL → markdown, through the tool the
research runtime uses.
"""

from __future__ import annotations

import urllib.request

import pytest


def _firecrawl_up() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:3002/", timeout=3) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(
    not _firecrawl_up(), reason="local Firecrawl (localhost:3002) not reachable"
)


def test_scrape_example_com_real():
    from my_crew.tools.firecrawl_tool import FirecrawlConfig, scrape_url

    fc = FirecrawlConfig(base_url="http://localhost:3002", api_key="local")
    res = scrape_url("https://example.com", fc)
    assert res.status_code == 200
    assert "Example Domain" in res.title or "Example Domain" in res.markdown
    assert len(res.markdown) > 0


def test_web_scrape_tool_returns_content_real():
    # The read_only_toolset web.scrape tool (what the runtime binds) fetches real content.
    from my_crew.runtime_backends.read_only_toolset import _firecrawl_tool

    class _S:
        firecrawl_base_url = "http://localhost:3002"
        firecrawl_api_key = "local"

    fn = _firecrawl_tool(_S())
    out = fn({"query": "https://example.com"})
    assert "Example Domain" in out


def test_web_scrape_ssrf_blocked_real():
    # Even with a live Firecrawl, the SSRF guard blocks localhost/metadata at source.
    from my_crew.runtime_backends.read_only_toolset import _firecrawl_tool

    class _S:
        firecrawl_base_url = "http://localhost:3002"
        firecrawl_api_key = "local"

    fn = _firecrawl_tool(_S())
    assert "bị chặn" in fn({"query": "http://169.254.169.254/latest/meta-data/"})
