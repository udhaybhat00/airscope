"""Vault: capture tree, file download, delete, and per-AP detail for Target."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter(prefix="/api", tags=["vault"])


def _entry(cap) -> dict:
    return {"type": str(cap.type), "path": cap.path, "timestamp": cap.timestamp,
            "ssid": cap.ssid, "record_count": cap.record_count,
            "has_value": cap.value is not None}


@router.get("/vault")
async def vault_tree(request: Request) -> dict:
    """Every AP with captures, newest-first (the VaultView shape)."""
    from airscope.persist.config import Config
    ctx = request.app.state.ctx
    groups: dict[str, dict] = {}
    for cap in ctx.vault.all_captures():
        g = groups.setdefault(cap.bssid, {"bssid": cap.bssid, "ssid": cap.ssid,
                                          "captures": []})
        if g["ssid"] is None and cap.ssid:
            g["ssid"] = cap.ssid
        g["captures"].append(_entry(cap))
    for g in groups.values():
        g["captures"].sort(key=lambda c: c["timestamp"], reverse=True)
    out = sorted(groups.values(), key=lambda g: (g["ssid"] or "\uffff").lower())
    return {"aps": out, "captures_dir": Config.captures_dir}


def _resolve(ctx, path: str) -> Path | None:
    """A vault path, contained in captures/ (no directory escapes)."""
    from airscope.persist.config import Config
    try:
        base = Path(Config.captures_dir).resolve()
        target = (base / Path(path).name).resolve()
    except (OSError, ValueError):
        return None
    if target.parent != base or not target.is_file():
        return None
    known = set()
    for c in ctx.vault.all_captures():
        try:
            known.add(str(Path(c.path).resolve()))
        except OSError:
            pass
    if str(target) not in known:
        return None
    return target


@router.get("/vault/file")
async def download_capture(path: str, request: Request):
    """Download one capture file."""
    target = _resolve(request.app.state.ctx, path)
    if target is None:
        return JSONResponse(status_code=404, content={"detail": "unknown capture"})
    return FileResponse(target)


@router.delete("/vault/file")
async def delete_capture(path: str, request: Request) -> dict:
    """Delete one capture (same file-drop semantics as the TUI)."""
    ctx = request.app.state.ctx
    cap = next((c for c in ctx.vault.all_captures() if c.path == path), None)
    if cap is None:
        return JSONResponse(status_code=404, content={"detail": "unknown capture"})
    ctx.vault.delete_capture(cap)
    ctx.bus.publish("vault.changed", {})
    return {"deleted": True}
