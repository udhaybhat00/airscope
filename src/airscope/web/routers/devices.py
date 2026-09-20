"""Devices: present USB cards with attached state (read-only, Phase 1)."""
from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api", tags=["devices"])


@router.get("/devices")
def devices(request: Request) -> dict:
    """Every supported card on the bus; ``attached`` means the engine owns it."""
    ctx = request.app.state.ctx
    return {"devices": ctx.device_list()}
