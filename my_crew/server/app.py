"""FastAPI app factory for the multi-agent web service (v2 M2-P6; auth added v6 M16).

SECURITY POSTURE: localhost dev runs with NO auth (byte-identical to pre-M16). For a real
deployment, set `WEB_AUTH_PASSWORD_HASH` + `WEB_SESSION_SECRET` (v6 M16) — then every route
except /health + login requires a signed session, and binding to a non-loopback host with
auth OFF is refused at startup (`auth.assert_bind_safe`). The per-agent guardrail (Lớp A/B +
audit + budget + dedup) applies regardless; auth protects the web's Lớp B approve surface.

`create_app()` builds the app; `app = create_app()` is the module-level ASGI target for
both `uvicorn my_crew.server.app:app` and FastAPI's TestClient.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from my_crew.server import (
    auth,
    routes_agent_company_docs,
    routes_agent_knowledge,
    routes_agent_studio_shared,
    routes_agent_telegram,
    routes_agents,
    routes_agents_admin,
    routes_clarify,
    routes_company,
    routes_company_docs,
    routes_connections,
    routes_office_artifacts,
    routes_office_assign,
    routes_office_room_chat,
    routes_office_stream,
    routes_ops_chat,
    routes_ops_json,
    routes_outputs,
    routes_runs,
    routes_setup,
    routes_tasks,
    routes_visualize,
)
from my_crew.server.run_manager import RunManager


def create_app() -> FastAPI:
    """Build the FastAPI app with the agent routers + the per-process run manager.

    ONE `RunManager` lives on `app.state` for the process lifetime (single event loop
    ⇒ its concurrency bookkeeping is race-free without a lock).
    """
    app = FastAPI(
        title="my-crew — agent web service",
        description="Localhost-only multi-agent dashboard backend (no auth).",
        version="0.0.0",
    )
    app.state.run_manager = RunManager()
    # v6 M16: single-user session auth. SessionMiddleware signs the cookie; AuthMiddleware
    # gates every non-public route. Both are no-ops when auth is disabled (no password hash
    # configured) → byte-identical to pre-M16 on localhost dev. add_middleware runs middleware
    # in REVERSE add-order, so AuthMiddleware must be added FIRST (runs last, inside) and
    # SessionMiddleware SECOND (runs first, outside) — otherwise AuthMiddleware would read the
    # session before SessionMiddleware populated it.
    import os

    from starlette.middleware.sessions import SessionMiddleware

    # Weak-secret refusal at APP-BUILD time (not just in main()): the docstring advertises
    # `uvicorn my_crew.server.app:app` as a target, which skips main()'s assert_bind_safe — so
    # the "auth ON but no real session secret ⇒ forgeable cookie" check must also fire here,
    # on every entry path (review M1). auth OFF ⇒ the dev fallback secret is fine.
    auth.assert_session_secret_safe()
    app.add_middleware(auth.AuthMiddleware)
    app.add_middleware(
        SessionMiddleware,
        secret_key=os.environ.get("WEB_SESSION_SECRET") or auth._DEV_SESSION_SECRET,
        https_only=False,  # LAN/localhost HTTP; TLS is a reverse-proxy concern (see docs)
        same_site="lax",
    )
    app.include_router(auth.router)
    # v7 M17: first-run Setup Wizard (only active before setup completes; 410 after).
    app.include_router(routes_setup.router)

    # API routers first so /api/* and the /static mount keep precedence over the SPA
    # catch-all mounted LAST below.
    app.include_router(routes_agents.router)
    app.include_router(routes_runs.router)
    # M4-S1: read-only JSON API for the React visualization dashboard.
    app.include_router(routes_visualize.router)
    # M4-S4: JSON ops API (approve/reject/config) — the real gateway-routed write path.
    app.include_router(routes_ops_json.router)
    # M7: agent admin (packs list / create wizard / lifecycle / integration health).
    app.include_router(routes_agents_admin.router)
    # Company identity (config-only) + staff-template picker read API.
    app.include_router(routes_company.router)
    # v33 P1: Connections screen — env-key presence + whitelisted merge + restart.
    app.include_router(routes_connections.router)
    # v33 P3: outputs hub (cross-room artifact index + downloads) + team-task board.
    app.include_router(routes_outputs.router)
    # v33 P4: clarify — agent questions the CEO answers from web or Telegram buttons.
    app.include_router(routes_clarify.router)
    # v15: office composer assignment (thin wrappers over the assign command's own
    # preview/confirm/cancel — hash-bind and @PIC parsing live there, not here).
    app.include_router(routes_office_assign.router)
    # v16: workroom listing + chat-in-room (3 intent) + coordinator health.
    app.include_router(routes_office_room_chat.router)
    app.include_router(routes_office_room_chat.health_router)
    # v17: read-only step-artifact viewer (the Kết quả column).
    app.include_router(routes_office_artifacts.router)
    # v6 M14b: CEO chat-ops web endpoint (same engine as the Telegram DM path).
    app.include_router(routes_ops_chat.router)
    # v7 M18: Agent Studio — telegram bind (M18a) + knowledge/skills form (M18b).
    # The studio modules (telegram M18a + knowledge/skills M18b + company-docs opt-in M19)
    # attach their endpoints to the one shared router; importing them registers the
    # decorators, then we mount it once.
    _ = (routes_agent_knowledge, routes_agent_telegram, routes_agent_company_docs)
    app.include_router(routes_agent_studio_shared.router)
    app.include_router(routes_company_docs.router)
    # v6 M15b: assigned-tasks board (view + cancel; assigning stays on the chat path).
    app.include_router(routes_tasks.router)
    # v12 M29: office group-chat room — SSE store-tail (multi-subscriber), protected
    # (NOT in auth._PUBLIC_PREFIXES — a room's events are internal team activity).
    app.include_router(routes_office_stream.router)
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


@app.get("/health")
def health() -> dict:
    """Liveness probe — public (no auth), so install.sh / launchd can check the service."""
    return {"ok": True}


def main() -> None:
    """Run the service with uvicorn.

    Host from `BIND_HOST` (default 127.0.0.1), port from `PORT` (default 8765). Binding to a
    non-loopback host (LAN) is REFUSED unless web auth is enabled (`assert_bind_safe`, R3):
    an unauthenticated dashboard on the network could approve Lớp B actions.
    """
    import os

    import uvicorn

    from my_crew.config.home_seed import ensure_home_seeded

    ensure_home_seeded()
    host = os.environ.get("BIND_HOST", "127.0.0.1")
    auth.assert_bind_safe(host)
    port = int(os.environ.get("PORT", "8765"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
