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

from src.server import routes_agents, routes_approvals, routes_dashboard, routes_runs
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
    app.include_router(routes_agents.router)
    app.include_router(routes_runs.router)
    # M2-P7 dashboard: HTML pages + static assets (htmx). Paths resolve from this
    # file's dir (not cwd) so `python -m src.server.app` works from the repo root.
    app.include_router(routes_dashboard.router)
    app.include_router(routes_approvals.router)
    app.mount(
        "/static",
        StaticFiles(directory=str(Path(__file__).parent / "static")),
        name="static",
    )
    return app


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
