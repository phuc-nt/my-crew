"""M4-S2: the React SPA build is served by FastAPI as committed static.

The Vite build is committed under `src/server/static/app/`, so the existing `/static`
mount serves it with no app change this slice. This test asserts the committed index +
its JS asset are reachable — a guard that the dist stays committed and the mount holds.
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


def test_spa_index_served_at_static_mount():
    client = TestClient(create_app())
    r = client.get("/static/app/index.html")
    assert r.status_code == 200
    assert "root" in r.text  # the React mount point


def test_spa_js_asset_served():
    client = TestClient(create_app())
    index = TestClient(create_app()).get("/static/app/index.html").text
    m = re.search(r"/static/app/assets/index-[^\"]+\.js", index)
    assert m, "no JS asset reference in the built index.html"
    r = client.get(m.group(0))
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(("application/javascript", "text/javascript"))


def test_htmx_index_still_works_this_slice():
    """S2 does not touch app routing — the htmx dashboard index at / still serves."""
    r = TestClient(create_app()).get("/")
    assert r.status_code == 200
