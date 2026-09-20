"""Crack jobs: dictionary attacks on vault captures with live WS progress."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from airscope.web.context import _Blocked, _NoTarget

router = APIRouter(prefix="/api", tags=["crack"])


class CrackStart(BaseModel):
    path: str
    wordlist: str


@router.post("/crack", status_code=202)
async def start_crack(body: CrackStart, request: Request):
    """Launch hashcat (or aircrack-ng) on one capture; progress on the socket."""
    ctx = request.app.state.ctx
    try:
        return await ctx.start_crack(body.path, body.wordlist)
    except _NoTarget:
        return JSONResponse(status_code=404, content={"detail": "unknown capture"})
    except _Blocked as e:
        return JSONResponse(status_code=422, content={"detail": str(e)})


@router.get("/jobs/{job_id}")
async def job_state(job_id: str, request: Request):
    """One crack job's latest state."""
    ctx = request.app.state.ctx
    job = ctx.cracks.get(job_id)
    if job is None:
        return JSONResponse(status_code=404, content={"detail": "unknown job"})
    return {k: job[k] for k in ("id", "path", "bssid", "ssid", "started", "state")
            if k in job}
