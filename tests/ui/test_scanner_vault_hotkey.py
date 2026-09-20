"""Scanner's 'v' hotkey opens the VAULT screen."""
from unittest.mock import Mock

import pytest

from airscope.ui.app import AirscopeApp
from airscope.ui.screens.scanner import ScannerView


@pytest.mark.asyncio
@pytest.mark.usefixtures("no_usb_devices")
async def test_open_vault_pushes_the_vault_screen():
    app = AirscopeApp()
    async with app.run_test() as pilot:
        app.push_screen("scanner")
        await pilot.pause(0)
        scanner = app.screen
        assert isinstance(scanner, ScannerView)
        app.push_screen = Mock()
        scanner.action_open_vault()
        app.push_screen.assert_called_once_with("vault")
