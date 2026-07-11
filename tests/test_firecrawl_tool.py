"""v20.5: Firecrawl scrape tool — SSRF guard + parse + degrade. Offline (fake urlopen)."""

from __future__ import annotations

import io
import json

import pytest

from src.tools.firecrawl_tool import (
    FirecrawlBlocked,
    FirecrawlConfig,
    _assert_public_url,
    scrape_url,
)

# --- SSRF guard (at source) ----------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:3002/x",
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://10.0.0.1/",
        "http://192.168.1.1/",
        "http://[::1]/",
    ],
)
def test_ssrf_blocks_internal_hosts(url):
    with pytest.raises(FirecrawlBlocked):
        _assert_public_url(url)


def test_ssrf_blocks_non_http_scheme():
    with pytest.raises(FirecrawlBlocked, match="http/https"):
        _assert_public_url("file:///etc/passwd")


def test_ssrf_allows_public():
    _assert_public_url("https://example.com")  # no raise


# --- config availability -------------------------------------------------------------


def test_available_gate():
    assert FirecrawlConfig(base_url="http://localhost:3002", api_key=None).available()
    assert not FirecrawlConfig(base_url="", api_key=None).available()
    assert not FirecrawlConfig(base_url=None, api_key=None).available()


def test_scrape_unconfigured_raises():
    with pytest.raises(RuntimeError, match="chưa cấu hình"):
        scrape_url("https://example.com", FirecrawlConfig(base_url="", api_key=None))


# --- parse (offline, injected urlopen) ----------------------------------------------


def _fake_urlopen(body: dict):
    def _open(req, timeout=None):
        class _Resp:
            def read(self):
                return json.dumps(body).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _Resp()

    return _open


def test_scrape_parses_markdown_and_metadata(monkeypatch):
    body = {
        "success": True,
        "data": {
            "markdown": "# Hello\n\nbody text",
            "metadata": {"sourceURL": "https://example.com", "title": "Hello", "statusCode": 200},
        },
    }
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen(body))
    fc = FirecrawlConfig(base_url="http://localhost:3002", api_key="dummy")
    res = scrape_url("https://example.com", fc)
    assert res.title == "Hello"
    assert res.status_code == 200
    assert "Hello" in res.markdown


def test_scrape_raises_on_success_false(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen({"success": False, "error": "x"}))
    fc = FirecrawlConfig(base_url="http://localhost:3002", api_key="dummy")
    with pytest.raises(RuntimeError, match="scrape failed"):
        scrape_url("https://example.com", fc)


def test_scrape_ssrf_checked_before_request(monkeypatch):
    # The SSRF guard runs BEFORE any HTTP call — even with a fake urlopen, a private URL raises.
    called = {"n": 0}
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *a, **k: called.__setitem__("n", called["n"] + 1)
    )
    fc = FirecrawlConfig(base_url="http://localhost:3002", api_key="dummy")
    with pytest.raises(FirecrawlBlocked):
        scrape_url("http://127.0.0.1/secret", fc)
    assert called["n"] == 0  # never reached the HTTP layer


def test_read_toolset_exposes_web_scrape_when_configured():
    from src.runtime_backends.read_only_toolset import assert_read_only, build_read_toolset

    class _S:
        firecrawl_base_url = "http://localhost:3002"
        firecrawl_api_key = "local"

    tools = build_read_toolset(None, audience="internal", settings=_S())
    assert "web.scrape" in tools
    assert_read_only(list(tools))  # web.scrape is not a write tool

    # Absent config → no scrape tool (degrade).
    assert "web.scrape" not in build_read_toolset(None, settings=None)


_ = io  # keep import used if a future test streams a response body
