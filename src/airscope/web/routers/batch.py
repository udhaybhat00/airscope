"""Batch jobs: plan (build_plan verbatim) and run in the background."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from airscope.web.context import _Blocked

router = APIRouter(prefix="/api", tags=["batch"])


class BatchStart(BaseModel):
    bssids: Optional[List[str]] = None
    timeouts: Optional[dict] = None


@router.post("/batch", status_code=202)
async def start_batch(body: BatchStart, request: Request):
    """Build the WPS -> PMKID -> handshake -> SAE plan and run it."""
    ctx = request.app.state.ctx
    try:
        return await ctx.start_batch(body.bssids, body.timeouts or {})
    except _Blocked as e:
        return JSONResponse(status_code=422, content={"detail": str(e)})


@router.get("/batch/{job_id}")
async def batch_state(job_id: str, request: Request):
    """One batch job with its steps, skips, and results so far."""
    from airscope.web.context import _public_batch
    ctx = request.app.state.ctx
    job = ctx.batches.get(job_id)
    if job is None:
        return JSONResponse(status_code=404, content={"detail": "unknown job"})
    return _public_batch(job)


@router.delete("/batch/{job_id}")
async def stop_batch(job_id: str, request: Request) -> dict:
    """Stop after the current step (no-op when already done)."""
    ctx = request.app.state.ctx
    stopped = await ctx.stop_batch(job_id)
    return {"stopped": stopped is not None}
