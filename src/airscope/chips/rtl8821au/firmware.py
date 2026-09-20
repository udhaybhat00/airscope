"""RTL8821AU firmware upload — thin shim over the family-shared helpers.

The legacy MCUFWDL upload path is identical across rtw88 8051 chips
(8821a, 8812a, 8723d). The actual implementations live in
:mod:`airscope.chips.rtw88_base.firmware_legacy`. This module just re-exports
them under the old import surface and provides the chip-local FW blob
loader.
"""

from __future__ import annotations

from pathlib import Path

from airscope.chips.rtw88_base.firmware_legacy import (
    DLFW_PAGE_SIZE_LEGACY,
    FW_CHUNK_BIG,
    FW_CHUNK_MID,
    FW_CHUNK_SMALL,
    FW_HDR_LEGACY_SIZE,
    FW_READY_LEGACY,
    FW_START_ADDR_LEGACY,
    download_firmware_legacy,
    download_firmware_validate_legacy,
    en_download_firmware_legacy,
    wlan_cpu_enable,
)


def load_firmware_blob(path: Path | None = None) -> bytes:
    """Read the canonical 8821A FW blob (32B header + body)."""
    if path is None:
        path = Path(__file__).parent / "assets" / "rtw8821a_fw.bin"
    return path.read_bytes()


__all__ = [
    "DLFW_PAGE_SIZE_LEGACY",
    "FW_CHUNK_BIG",
    "FW_CHUNK_MID",
    "FW_CHUNK_SMALL",
    "FW_HDR_LEGACY_SIZE",
    "FW_READY_LEGACY",
    "FW_START_ADDR_LEGACY",
    "download_firmware_legacy",
    "download_firmware_validate_legacy",
    "en_download_firmware_legacy",
    "load_firmware_blob",
    "wlan_cpu_enable",
]
