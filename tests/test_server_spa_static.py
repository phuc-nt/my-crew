"""M4-S5: the React SPA is served at `/` (committed build, no Node step at serve time).

The Vite build is committed under `src/server/static/app/`; the app serves index.html at `/`
and for any non-API client route (browser-router deep-links), assets at `/assets/*`. These
tests guard that the dist stays committed and the SPA-serve + `/api` precedence hold.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from src.server.app import create_app

_DIST = Path(__file__).resolve().parents[1] / "src" / "server" / "static" / "app"


def test_spa_index_is_committed():
    """The build artifact must be present in the repo (committed dist, not gitignored)."""
    assert (_DIST / "index.html").exists(), "SPA dist missing — run `npm run build` in web/"


def test_spa_served_at_root():
    r = TestClient(create_app()).get("/")
    assert r.status_code == 200
    assert "root" in r.text  # the React mount point


def test_spa_js_asset_served():
    client = TestClient(create_app())
    index = client.get("/").text
    m = re.search(r"/assets/index-[^\"]+\.js", index)
    assert m, "no JS asset reference in the built index.html"
    r = client.get(m.group(0))
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(("application/javascript", "text/javascript"))


def test_client_route_deep_link_serves_index():
    """A browser-router deep-link (/cost, /approvals) falls back to index.html (SPA routing)."""
    client = TestClient(create_app())
    for path in ("/cost", "/approvals", "/timeline"):
        r = client.get(path)
        assert r.status_code == 200
        assert "root" in r.text  # served the SPA shell, not a 404


def test_api_precedence_over_spa_catchall():
    """The SPA catch-all must NOT shadow /api/* — the API still routes."""
    client = TestClient(create_app())
    assert client.get("/api/agents").status_code == 200
