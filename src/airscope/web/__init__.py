"""Local web dashboard backend (Phase 1: read-only live scan).

Dependency-light on purpose: only stdlib + the engine here. FastAPI/uvicorn
are imported lazily by ``create_app`` so TUI installs never pay for them.
"""
from __future__ import annotations


def create_app(context=None):
    """Build the FastAPI app over a HeadlessContext (created when omitted)."""
    try:
        from fastapi import FastAPI
    except ImportError as e:
        raise SystemExit(
            "airscope: web extras missing. Install them with:\n"
            "  uv sync --extra web        (or: pip install 'airscope[web]')"
        ) from e

    from airscope.web.context import HeadlessContext
    from airscope.web.routers import attacks as attacks_router
    from airscope.web.routers import batch as batch_router
    from airscope.web.routers import crack as crack_router
    from airscope.web.routers import devices as devices_router
    from airscope.web.routers import exports as exports_router
    from airscope.web.routers import scan as scan_router
    from airscope.web.routers import system as system_router
    from airscope.web.routers import vault as vault_router

    ctx = context or HeadlessContext()
    app = FastAPI(title="airscope web", version="1")
    app.state.ctx = ctx
    app.include_router(system_router.router)
    app.include_router(devices_router.router)
    app.include_router(scan_router.router)
    app.include_router(attacks_router.router)
    app.include_router(batch_router.router)
    app.include_router(vault_router.router)
    app.include_router(crack_router.router)
    app.include_router(exports_router.router)

    from pathlib import Path

    from fastapi.staticfiles import StaticFiles

    static = Path(__file__).parent / "static"
    if (static / "index.html").is_file():
        app.mount("/", StaticFiles(directory=static, html=True), name="static")
    else:
        @app.get("/")
        def _no_ui():
            return {"detail": "web UI not built yet (see webui/)"}

    @app.on_event("startup")
    async def _startup() -> None:
        await ctx.start()

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await ctx.stop()

    return app
