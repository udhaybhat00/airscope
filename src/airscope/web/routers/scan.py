"""Scan: AP snapshots over REST plus the live ``scan.tick`` socket (``/api/ws/events``)."""
from __future__ import annotations

import time

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

router = APIRouter(prefix="/api", tags=["scan"])


@router.get("/aps")
def aps(request: Request) -> dict:
    """Current APs, same shape as every ``scan.tick`` payload."""
    ctx = request.app.state.ctx
    return {"aps": ctx.snapshot_aps(), "rates": ctx.snapshot_rates(),
            "scanning": not ctx.scan_paused, "at": time.time()}


@router.post("/scan/{action}")
async def scan_control(action: str, request: Request) -> dict:
    """Halt or resume channel hopping (ticks keep flowing with a flag)."""
    from fastapi.responses import JSONResponse
    if action not in ("start", "stop"):
        return JSONResponse(status_code=404, content={"detail": f"unknown action: {action}"})
    ctx = request.app.state.ctx
    on = action == "start"
    await ctx.set_scanning(on)
    return {"scanning": on}


@router.get("/aps/{bssid}")
def ap_detail(bssid: str, request: Request) -> dict:
    """One AP: snapshot, clients, captures, and eligible attacks (Target page)."""
    from fastapi.responses import JSONResponse
    ctx = request.app.state.ctx
    ap = ctx.find_ap(bssid)
    if ap is None:
        return JSONResponse(status_code=404, content={"detail": f"unknown BSSID: {bssid}"})
    snaps = [s for s in ctx.snapshot_aps() if s["bssid"].lower() == bssid.lower()]
    caps = [c for c in ctx.vault.all_captures() if c.bssid.lower() == bssid.lower()]
    return {"ap": snaps[0] if snaps else None,
            "attacks": ctx.eligible_attacks(ap),
            "captures": [{"type": str(c.type), "path": c.path, "timestamp": c.timestamp,
                          "record_count": c.record_count,
                          "has_value": c.value is not None} for c in caps]}


@router.websocket("/ws/events")
async def events(websocket: WebSocket) -> None:
    """One stream for everything live. Phase 1 speaks ``scan.tick`` only:
    ``{"topic": "scan.tick", "payload": {"aps": [...], "at": ...}}`` @2Hz,
    plus a ``hello`` so clients can resync cursors on reconnect."""
    await websocket.accept()
    ctx = websocket.app.state.ctx
    queue = ctx.bus.subscribe()
    try:
        await websocket.send_json({"topic": "hello",
                                   "payload": {"engine": ctx.engine_state()}})
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        ctx.bus.unsubscribe(queue)
