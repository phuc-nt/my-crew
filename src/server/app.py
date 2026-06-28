"""FastAPI app factory for the multi-agent web service (v2 M2-P6).

SECURITY POSTURE (M2 sandbox): this service is LOCALHOST-ONLY and has NO AUTH. It can
trigger real report runs (which write to Slack/Confluence through the per-agent Action
Gateway), so it must NOT be exposed beyond 127.0.0.1 without adding authentication —
that is deliberately deferred. The guardrail still applies per-agent (Lớp A/B + audit +
budget + dedup), DRY_RUN default still holds, and external audience still routes through
Lớp B approval.

`create_app()` builds the app; `app = create_app()` is the module-level ASGI target for
both `uvicorn src.server.app:app` and FastAPI's TestClient. The uvicorn `__main__` runner
(binding 127.0.0.1) is added in Slice 3.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.server import (
    routes_agents,
    routes_ops_json,
    routes_runs,
    routes_visualize,
)
from src.server.run_manager import RunManager


def create_app() -> FastAPI:
    """Build the FastAPI app with the agent routers + the per-process run manager.

    ONE `RunManager` lives on `app.state` for the process lifetime (single event loop
    ⇒ its concurrency bookkeeping is race-free without a lock).
    """
    app = FastAPI(
        title="my-project-manager — agent web service",
        description="Localhost-only multi-agent dashboard backend (no auth).",
        version="0.0.0",
    )
    app.state.run_manager = RunManager()
    # API routers first so /api/* and the /static mount keep precedence over the SPA
    # catch-all mounted LAST below.
    app.include_router(routes_agents.router)
    app.include_router(routes_runs.router)
    # M4-S1: read-only JSON API for the React visualization dashboard.
    app.include_router(routes_visualize.router)
    # M4-S4: JSON ops API (approve/reject/config) — the real gateway-routed write path.
    app.include_router(routes_ops_json.router)
    # Legacy /static assets (kept for any non-SPA asset; the SPA's own assets live under
    # static/app and are served by the SPA mount below).
    app.mount(
        "/static",
        StaticFiles(directory=str(Path(__file__).parent / "static")),
        name="static",
    )
    # M4-S5: the React SPA is the UI. Its built assets live under static/app; mount them at
    # `/assets` (the base=/ build references `/assets/*`). Then a catch-all GET returns
    # index.html for `/` AND any unmatched client-routed path (/timeline, /cost, …) so the
    # browser-router deep-links resolve. Registered LAST so /api/* + /static keep precedence.
    _spa_dir = Path(__file__).parent / "static" / "app"
    app.mount("/assets", StaticFiles(directory=str(_spa_dir / "assets")), name="spa-assets")
    _register_spa_catchall(app, _spa_dir)
    return app


def _register_spa_catchall(app: FastAPI, spa_dir: Path) -> None:
    """Serve the SPA index.html for `/` and any non-API client route (browser-router deep-links).

    Excludes `/api` and `/static` (those are handled by their routers/mount, registered first).
    A request for a real file under the SPA dir (favicon.svg, icons.svg) is served directly;
    everything else falls back to index.html so the React router renders the route.
    """
    from fastapi import HTTPException
    from fastapi.responses import FileResponse

    index = spa_dir / "index.html"

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        if full_path.startswith(("api/", "static/", "assets/")):
            raise HTTPException(status_code=404, detail="not found")
        candidate = spa_dir / full_path
        if full_path and candidate.is_file() and spa_dir in candidate.resolve().parents:
            return FileResponse(candidate)
        return FileResponse(index)  # SPA fallback → React router handles the path


app = create_app()


def main() -> None:
    """Run the service with uvicorn, bound to 127.0.0.1 ONLY (localhost sandbox).

    Port from the `PORT` env var (default 8765). NEVER bind 0.0.0.0 here — this
    service has no auth and can trigger real writes; exposing it needs auth first.
    """
    import os

    import uvicorn

    port = int(os.environ.get("PORT", "8765"))
    uvicorn.run(app, host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
