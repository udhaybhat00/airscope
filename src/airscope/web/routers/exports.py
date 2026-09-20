"""Exports: csv/netxml/cracked/html generated from the live array + vault."""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

from airscope import exports

router = APIRouter(prefix="/api", tags=["exports"])

KINDS = ("csv", "netxml", "cracked", "html")
_FILENAMES = {"csv": "airscope.csv", "netxml": "airscope.netxml",
              "cracked": "cracked.txt", "html": "report.html"}
_MEDIA = {"csv": "text/csv", "netxml": "application/xml",
          "cracked": "text/plain", "html": "text/html"}


@router.get("/exports/{kind}")
async def export_report(kind: str, request: Request):
    """Generate one report on the fly and download it."""
    if kind not in KINDS:
        return JSONResponse(status_code=404, content={"detail": f"unknown export: {kind}"})
    ctx = request.app.state.ctx
    aps = exports.ap_snaps_from_array(ctx.array) if ctx.array is not None else []
    cracks = exports.cracks_from_vault(ctx.vault)
    keys = {c.bssid: c.psk for c in cracks}
    outdir = tempfile.mkdtemp(prefix="airscope-export-")
    made = exports.export_all(Path(outdir), aps, cracks, [], keys)
    path = made[kind]
    # Inline disposition: the Reports page previews HTML in an iframe, and the
    # download links carry their own `download` attribute, so inline is right
    # for every kind here.
    return FileResponse(path, media_type=_MEDIA[kind], filename=_FILENAMES[kind],
                        headers={"Content-Disposition": "inline"})
