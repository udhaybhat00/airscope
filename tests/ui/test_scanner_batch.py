"""Scanner batch queue: Space marks rows, B attacks the marked set."""
from typing import List, Optional

import pytest
from textual.app import App
from textual.widgets import DataTable, Label

from airscope.models import AccessPoint
from airscope.persist.config import Config
from airscope.persist.vault import Vault
from airscope.ui.screens.scanner import ScannerView


@pytest.fixture(autouse=True)
def _zero_sort_delay(monkeypatch):
    monkeypatch.setattr(Config, "scanner_sort_delay", 0.0)


def _make_ap(bssid, ssid=None, signal=-60, akms=None):
    ap = AccessPoint(bssid=bssid, ssid=ssid, akms=akms or [])
    ap.signal_by_card = {"card0": signal}
    if akms:
        ap.akm_suites = [2]
    return ap


class _FakeArray:
    def __init__(self, aps, supported):
        self.access_points = {ap.bssid: ap for ap in aps}
        self.clients = {}
        self.forged_macs = set()
        self.supported_channels = supported
        self.members = []

    def get_access_points(self, include_eviltwin=True):
        return list(self.access_points.values())

    async def start_hopping(self, channels=None, interval=0.25):
        pass

    async def stop_hopping(self):
        pass


class _ScannerHost(App):
    def __init__(self, array):
        super().__init__()
        self.array = array
        self.pbc_enabled = True
        self.vault = Vault()
        self.toasts = []

    def persist_config(self):
        pass

    def notify(self, *args, **kwargs):
        self.toasts.append((args, kwargs))

    def on_mount(self):
        self.push_screen(ScannerView())


def _cell_text(table, row, col):
    val = table.get_row_at(row)[col]
    return val.plain if hasattr(val, "plain") else str(val)


@pytest.mark.asyncio
async def test_space_marks_and_unmarks_cursor_row():
    aps = [_make_ap("aa:bb:cc:00:00:01", ssid="A", signal=-50, akms=["PSK"]),
           _make_ap("aa:bb:cc:00:00:02", ssid="B", signal=-60, akms=["PSK"])]
    app = _ScannerHost(_FakeArray(aps, [1, 6, 11]))
    async with app.run_test() as pilot:
        await pilot.pause(0)
        scanner = app.screen
        scanner.refresh_table()
        await pilot.pause(0)
        table = scanner.query_one("#ap-table", DataTable)
        table.move_cursor(row=1, animate=False)
        await pilot.pause(0)

        scanner.action_toggle_mark()
        assert "aa:bb:cc:00:00:02" in scanner._marked
        assert _cell_text(table, 1, 1).startswith("✓ ")
        strip = scanner.query_one("#scan-status", Label)
        assert "1 marked" in strip.content

        scanner.action_toggle_mark()
        assert scanner._marked == set()
        assert not _cell_text(table, 1, 1).startswith("✓ ")


@pytest.mark.asyncio
async def test_batch_with_nothing_marked_warns():
    app = _ScannerHost(_FakeArray([], []))
    async with app.run_test() as pilot:
        await pilot.pause(0)
        app.screen.action_batch_marked()
        await pilot.pause(0)
        assert app.toasts and "Space marks targets" in str(app.toasts[-1])


@pytest.mark.asyncio
async def test_batch_runs_plan_and_clears_running(monkeypatch):
    aps = [_make_ap("aa:bb:cc:dd:ee:01", ssid="A", signal=-50, akms=["PSK"])]
    app = _ScannerHost(_FakeArray(aps, [1, 6, 11]))

    from airscope.campaigns.batch import BatchSummary, StepResult
    calls = {}

    class _Runner:
        def __init__(self, array, vault, log=None, timeouts=None, session=None):
            calls["made"] = True

        async def run(self, steps, targets):
            calls["steps"] = [(s.bssid, s.kind) for s in steps]
            return BatchSummary(results=[StepResult("aa:bb:cc:dd:ee:01", "A", "pmkid",
                                                   "timeout", "t", 1.0)])

    monkeypatch.setattr("airscope.campaigns.batch.BatchRunner", _Runner)
    async with app.run_test() as pilot:
        await pilot.pause(0)
        scanner = app.screen
        scanner.refresh_table()
        await pilot.pause(0)
        scanner._marked.add("aa:bb:cc:dd:ee:01")
        scanner.action_batch_marked()
        for _ in range(60):
            await pilot.pause(0)
            if not scanner._batch_running and calls.get("steps"):
                break
        kinds = [k for _, k in calls["steps"]]
        assert "pmkid" in kinds and "handshake" in kinds
        assert scanner._batch_running is False
        assert any("Batch done" in str(t) for t in app.toasts)


@pytest.mark.asyncio
async def test_batch_stop_requests_stop_on_runner():
    app = _ScannerHost(_FakeArray([], []))
    async with app.run_test() as pilot:
        await pilot.pause(0)
        scanner = app.screen
        stopped = []

        class _R:
            def request_stop(self):
                stopped.append(True)

        scanner._batch_runner = _R()
        scanner.action_batch_stop()
        assert stopped == [True]
