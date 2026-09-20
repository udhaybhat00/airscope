"""Attacks: start one campaign, poll it, stop it. One radio, so a live
attack makes every other start a 409 (same mutex as the TUI)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from airscope.web.context import _Blocked, _Busy, _NoTarget

router = APIRouter(prefix="/api", tags=["attacks"])


class AttackStart(BaseModel):
    bssid: str
    timeout: Optional[float] = None
    punt: bool = True


def _err(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


@router.post("/attacks/{kind}", status_code=202)
async def start_attack(kind: str, body: AttackStart, request: Request):
    """Start wps/pmkid/handshake/sae/eviltwin against one AP."""
    ctx = request.app.state.ctx
    try:
        return await ctx.start_attack(kind, body.bssid, timeout=body.timeout, punt=body.punt)
    except _Busy as e:
        return _err(409, str(e))
    except _NoTarget:
        return _err(404, f"unknown BSSID: {body.bssid}")
    except _Blocked as e:
        return _err(422, str(e))


@router.get("/attacks/current")
async def current_attack(request: Request) -> dict:
    """The live attack record, or null."""
    ctx = request.app.state.ctx
    return {"attack": ctx.attack and {k: ctx.attack[k] for k in
                                      ("id", "kind", "bssid", "ssid", "started", "state")
                                      if k in ctx.attack}}


@router.delete("/attacks/current")
async def stop_attack(request: Request) -> dict:
    """Stop the live attack (fire-and-forget, like the TUI stop buttons)."""
    ctx = request.app.state.ctx
    stopped = await ctx.stop_attack()
    return {"stopped": stopped is not None}
