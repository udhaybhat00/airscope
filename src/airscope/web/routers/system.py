"""Health: version plus engine state for the dashboard shell."""
from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health(request: Request) -> dict:
    """Liveness plus what the engine is doing (idle/scanning/demo)."""
    from airscope import __version__
    ctx = request.app.state.ctx
    return {"name": "airscope", "version": __version__, "engine": ctx.engine_state(),
            "scanning": not ctx.scan_paused}
