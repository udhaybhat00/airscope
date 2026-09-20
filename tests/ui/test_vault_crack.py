"""VAULT dictionary crack: Crack button placement, modal validation, and the
hashcat flow (backend stubbed) through to a saved CRACKED PSK."""
import pytest
from textual.widgets import Button, DataTable, Input, Label

from airscope.crack.external import CrackRun, CrackTools
from airscope.models import AccessPoint
from airscope.ui.app import AirscopeApp
from airscope.ui.screens.vault import VaultView
from airscope.ui.screens.vault_item import CrackModal, VaultItemView, _CapturePanel
from airscope.ui.screens import vault_item as vi

_HS_LINE = "WPA*02*" + "0" * 32 + "*aabbccddeeff*112233445566*5465737431***2\n"


def _write(d, name, content):
    (d / name).write_text(content, encoding="utf-8")


def _ap():
    return AccessPoint(bssid="aa:bb:cc:dd:ee:ff", ssid="HomeNet")


async def _open_vault(app) -> VaultView:
    app.push_screen("vault")
    return app.screen


@pytest.mark.asyncio
@pytest.mark.usefixtures("no_usb_devices")
async def test_hs_panel_has_crack_button_wep_panel_does_not(tmp_path):
    _write(tmp_path, "HomeNet_aa-bb-cc-dd-ee-ff_1000_handshake.hc22000", _HS_LINE)
    _write(tmp_path, "HomeNet_aa-bb-cc-dd-ee-ff_1001_wep_key.txt",
           "SSID: HomeNet\nBSSID: aa:bb:cc:dd:ee:ff\nWEP key (hex):   6162636465\n")
    app = AirscopeApp()
    async with app.run_test() as pilot:
        view = await _open_vault(app)
        await pilot.pause()
        panels = list(view.query(_CapturePanel))
        assert len(panels) == 2
        by_title = {p.border_title: p for p in panels}
        hs = next(p for t, p in by_title.items() if t.startswith("HANDSHAKE"))
        wep = next(p for t, p in by_title.items() if t.startswith("WEP KEY"))
        assert hs.query_one(".crack", Button) is not None
        assert not wep.query(".crack")


@pytest.mark.asyncio
@pytest.mark.usefixtures("no_usb_devices")
async def test_crack_modal_rejects_missing_wordlist(tmp_path):
    app = AirscopeApp()
    dismissed = []
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(CrackModal("h.hc22000", "Tool: hashcat", "", can_start=True),
                        dismissed.append)
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, CrackModal)
        modal.query_one("#crack-wordlist", Input).value = str(tmp_path / "nope.txt")
        modal.query_one("#crack-start", Button).press()
        await pilot.pause()
        assert dismissed == []                                    # still open
        assert modal.query_one("#crack-error", Label).content


@pytest.mark.asyncio
@pytest.mark.usefixtures("no_usb_devices")
async def test_full_crack_flow_saves_psk_to_vault(tmp_path, monkeypatch):
    _write(tmp_path, "HomeNet_aa-bb-cc-dd-ee-ff_1000_handshake.hc22000", _HS_LINE)
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("secret123\n", encoding="utf-8")

    async def _fake_run(cmd, tool, on_progress=None):
        return CrackRun(exit_code=0, output="")

    async def _fake_show(cmd):
        return 0, f"{_HS_LINE.strip()}:secret123"

    monkeypatch.setattr(vi.crack_ext, "detect_tools",
                        lambda: CrackTools(hashcat="/bin/hashcat"))
    monkeypatch.setattr(vi.crack_ext, "run_crack", _fake_run)
    monkeypatch.setattr(vi.crack_ext, "run_capture_output", _fake_show)

    app = AirscopeApp()
    async with app.run_test() as pilot:
        view = await _open_vault(app)
        await pilot.pause()
        view.query_one(_CapturePanel).query_one(".crack", Button).press()
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, CrackModal)
        modal.query_one("#crack-wordlist", Input).value = str(wordlist)
        modal.query_one("#crack-start", Button).press()
        for _ in range(60):
            await pilot.pause(0)
            if app.vault.has_cracked_psk("aa:bb:cc:dd:ee:ff"):
                break
        assert app.vault.known_psk(_ap()) == "secret123"
        for _ in range(20):                                       # CapturesChanged reload
            await pilot.pause(0)
            panels = list(view.query(_CapturePanel))
            if any(p.border_title.startswith("CRACKED PSK") for p in panels):
                break
        assert any(p.border_title.startswith("CRACKED PSK") for p in view.query(_CapturePanel))
        table = view.query_one("#vault-aps", DataTable)
        assert table.get_row_at(0)[2] == "1"                     # Keys column counts it


def test_count_keys_includes_cracked():
    from airscope.models import CaptureType, PersistedCapture
    from airscope.ui.screens.vault import _count_keys
    caps = [PersistedCapture(type=CaptureType.CRACKED, timestamp=1, path="c",
                             bssid="aa:bb:cc:dd:ee:ff", value="secret123")]
    assert _count_keys(caps) == 1


@pytest.mark.asyncio
@pytest.mark.usefixtures("no_usb_devices")
async def test_export_all_writes_four_formats(tmp_path, monkeypatch):
    from airscope.persist.config import Config
    caps = tmp_path / "captures"
    caps.mkdir()
    monkeypatch.setattr(Config, "captures_dir", str(caps))
    _write(caps, "HomeNet_aa-bb-cc-dd-ee-ff_1000_handshake.hc22000", _HS_LINE)
    app = AirscopeApp()
    async with app.run_test() as pilot:
        view = await _open_vault(app)
        await pilot.pause()
        view.action_export_all()
        await pilot.pause()
        outdir = caps.parent / "exports"
        assert {p.name for p in outdir.iterdir()} == \
            {"airscope.csv", "airscope.netxml", "cracked.txt", "report.html"}
