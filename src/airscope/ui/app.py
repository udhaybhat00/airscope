import atexit
import asyncio
import logging
import os
import signal
import subprocess
import sys
from textual import events, work
from textual.app import App
from textual.binding import Binding
from textual.widgets import Header
from textual.widgets._header import HeaderClock, HeaderIcon, HeaderTitle
from typing import Optional

from airscope import __version__
from airscope.chips import log_trace
from airscope.persist.config import Config, ConfigError
from airscope.persist.vault import Vault
from airscope.errors import AirscopeDeviceLostError, AirscopeFatalError
from airscope.device.manager import DeviceManager, Status
from airscope.device.watch import DeviceWatch
from airscope.wlan.array import WlanArray
from airscope.models import AccessPoint

from .screens.splash import SplashView
from .screens.scanner import ScannerView
from .screens.focus_v2 import FocusViewV2
from .screens.vault import VaultView
from .screens.error_modals import FatalErrorModal, RecoverableErrorModal
from .screens.new_device import NewDeviceDialog
from .pref import PreferencesModal
from .themes import register_app_themes

logger = logging.getLogger(__name__)

Header.ALLOW_SELECT = False
HeaderTitle.ALLOW_SELECT = False
HeaderIcon.ALLOW_SELECT = False
HeaderClock.ALLOW_SELECT = False


class AirscopeApp(App):
    """airscope TUI Main App."""

    TITLE = f"airscope v{__version__}"

    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [Binding("ctrl+p", "preferences", "Prefs")]

    CSS = """
    /* Midnight: single-line header, rounded panels, fixed log height */
    Header { height: 1 !important; background: $surface; color: $foreground; }
    Footer { background: $surface; color: $foreground; }
    #ascii-art {
        content-align: center middle;
        margin-bottom: 2;
    }
    #device-row {
        width: auto;
        height: auto;
        align: center middle;
        margin-top: 1;
    }
    #button-row {
        width: auto;
        height: auto;
        align: center middle;
        margin-top: 1;
    }
    #button-row Button:focus {
        text-style: bold reverse;
    }
    #start-btn {
        background: $accent;
        color: $background;
        text-style: bold;
    }
    #status-label {
        content-align: center middle;
        margin-bottom: 1;
    }
    #status-strip {
        height: 1;
        background: $surface;
        color: $foreground;
    }
    ListView, #device-select {
        width: 52;
        height: auto;
        max-height: 12;
        border: round $primary;
    }
    DataTable {
        width: 100%;
        height: 1fr;
        border: round $surface;
    }
    DataTable .datatable--header { color: $secondary; text-style: bold; }
    DataTable .datatable--cursor { background: $primary 20%; }
    RichLog, SelectableRichLog {
        height: 4;
        border: round $surface;
        border-top: solid $primary;
    }
    Button {
        margin-right: 1;
        min-width: 12;
    }
    Button:hover {
        background: $primary 18%;
        color: $foreground;
    }
    Button.-primary { background: $primary; color: $background; }
    Button.-primary:hover { background: $primary 80%; }
    Button.-warning { background: $warning; color: $background; }
    Button.-warning:hover { background: $warning 80%; }
    Button.-error { background: $error; color: $background; }
    Button.-error:hover { background: $error 80%; }
    EvilTwinInputModal #bssid-btns Button { min-width: 4; }
    """

    def __init__(self, cli_log_level=None):
        super().__init__()
        self._config_error: Optional[str] = None
        try:
            Config.load()
        except ConfigError as e:
            self._config_error = str(e)
        _configure_file_logging(cli_log_level)
        self.array: Optional[WlanArray] = None
        self.device_manager = DeviceManager(self)
        self.device_watch = DeviceWatch(device_manager=self.device_manager,
                                        on_change=self._on_devices_changed,
                                        on_fatal=self._on_usb_fatal)
        self.target_ap: Optional[AccessPoint] = None
        self.vault = Vault()
        self.pbc_enabled: bool = True
        self._quitting: bool = False  # guard against double-execution of action_quit()
        register_app_themes(self)
        self.theme = Config.theme
        _register_cleanup()

    def on_text_selected(self, event: events.TextSelected) -> None:
        selected = self.screen.get_selected_text()
        if not selected:
            return
        self.copy_to_clipboard(selected)
        chars = len(selected)
        noun = "char" if chars == 1 else "chars"
        self.notify(f"Copied {chars} {noun} to clipboard")

    def persist_config(self) -> None:
        try:
            Config.save()
        except ConfigError as e:
            self.notify(str(e), severity="error", title="Config")

    def on_mount(self) -> None:
        """Register screens, push the splash, and start the always-on device watch."""
        if self._config_error:
            self.notify(self._config_error, severity="error", title="Config")
        self.install_screen(SplashView(), name="splash")
        self.install_screen(ScannerView(), name="scanner")
        self.install_screen(FocusViewV2(), name="focus")
        self.install_screen(VaultView(), name="vault")
        self.push_screen("splash")
        self._device_timer = self.set_interval(0.5, self.device_watch.poll)
        self.call_after_refresh(self.device_watch.poll)

    def _on_devices_changed(self, current, arrived, departed) -> None:
        """DeviceWatch fired. On Splash, refresh the card list; mid-session, prompt to bring up
        each newly-plugged card."""
        if any(isinstance(s, SplashView) for s in self.screen_stack):
            self.get_screen("splash", SplashView).render_devices(current)
            return
        # Ignore already-attached devices
        fresh = [d for d in arrived if not (self.array and self.array.contains(d))]
        if fresh:
            if isinstance(self.screen, RecoverableErrorModal):
                self.screen.dismiss()
            self.device_watch.pause()     # pause synchronously so the next tick can't stack a prompt
            self._prompt_hotplug(fresh)

    @work(exclusive=True)
    async def _prompt_hotplug(self, arrived) -> None:
        """Mid-session: ask per new card, and bring up the ones the user confirms (only that card,
        and on Windows never a disruptive mid-session install)."""
        try:
            for dev in arrived:
                if await self.push_screen_wait(NewDeviceDialog(dev.description)):
                    res = await self.device_manager.bringup(
                        dev, bail_at_permissions=(sys.platform == "win32"))
                    if res.status is Status.FAILED:
                        self.notify(res.message, severity="error")
                    elif res.status is Status.READY:
                        self.notify(f"{dev.description} added", severity="information")
        finally:
            self.device_watch.resume()

    def _on_usb_fatal(self, err: AirscopeFatalError) -> None:
        """The bus scan hit an unrecoverable backend error: stop watching + show the Quit-only modal."""
        self._device_timer.stop()
        self.push_screen(FatalErrorModal(err))

    def notify_device_lost(self, exc: Exception, remaining: int) -> None:
        """A pooled card vanished mid-run (the array re-emits this with the surviving card count).

        Arrives on the event-loop thread via the RX reader's ``call_soon_threadsafe`` hop, which
        runs OUTSIDE Textual's message-pump context (``active_app`` unset), so a direct
        ``push_screen`` here crashes in the modal's compose (NoActiveAppError). Defer it onto the
        app's message queue via ``call_later``; that callback runs in-context."""
        self.call_later(self._show_device_lost, exc, remaining)

    def _show_device_lost(self, exc: Exception, remaining: int) -> None:
        # Survivors remain: keep running, just toast how many are left.
        if remaining > 0:
            self.notify(f"A wireless card was lost. {remaining} still active.",
                        title="Card unplugged", severity="warning")
            return
        # Last card gone: fall back to the recoverable modal → splash.
        if isinstance(self.screen, (FatalErrorModal, RecoverableErrorModal)):
            return
        self.push_screen(RecoverableErrorModal(AirscopeDeviceLostError("the wireless adapter")))

    async def recover_to_splash(self) -> None:
        """Return to the splash screen after the last card was lost."""
        array = self.array
        # Unwind to the base default screen (kept by `> 1`), then re-push splash onto it.
        while len(self.screen_stack) > 1:
            await self.pop_screen()
        await self.push_screen("splash")
        # The installed splash only resumes (on_mount won't re-run), so reset its state explicitly.
        self.get_screen("splash", SplashView).reset_for_reentry()
        # Close the dead pool only once scanner/focus are gone, so their teardown can't read a
        # half-closed interface.
        if array is not None:
            try:
                await array.close()
            except Exception:
                logger.debug("Closing the lost pool failed (already gone)", exc_info=True)
        self.array = None
        self.target_ap = None

    def action_preferences(self) -> None:
        self.push_screen(PreferencesModal())

    def on_key(self, event: events.Key) -> None:
        """Direct key handler — bypasses Textual binding dispatch.

        The binding system (Screen BINDINGS) was not reliably dispatching
        'q' → action_quit on the Pi (Textual 8.2.8). This handler catches
        the key at the App level as a fallback.

        Note: Screens like splash.py and scanner.py also have their own
        Binding("q", "quit") which dispatches to action_quit() via Textual's
        binding system. That means BOTH paths can fire for one keypress, scheduling
        action_quit twice. The _quitting guard in action_quit() prevents the second
        invocation from running redundant cleanup or calling self.exit() again.
        """
        if event.key == "q":
            event.stop()
            event.prevent_default()
            print("[airscope] on_key: caught 'q', calling action_quit", flush=True)
            self.run_worker(self.action_quit, exclusive=True, group="quit")

    async def action_quit(self):
        """Quit: persist config, close adapters, release cards, exit.

        Guard against double-invocation: when a Screen has its own Binding("q",
        "quit") AND this App-level on_key handler both fire for the same keypress,
        Textual schedules two concurrent action_quit() tasks. The _quitting flag
        ensures only the first one runs full cleanup; subsequent calls return immediately.

        Every cleanup step is wrapped in timeouts so that a hung adapter close
        or a slow modprobe cycle can never prevent self.exit() from being
        called.  self.exit() is in a finally block — it ALWAYS runs.
        """
        if self._quitting:
            logger.info("action_quit: already quitting, ignoring duplicate call")
            return
        self._quitting = True
        print("\n[airscope] action_quit: shutting down...", flush=True)
        try:
            self.notify("Shutting down…", severity="information", timeout=8)
        except Exception:
            pass  # notify failure must not block exit
        try:
            self.persist_config()
        except Exception as exc:
            logger.warning("action_quit: persist_config failed: %s", exc)
        try:
            # 1) Close the WlanArray (stops driver loops, releases USB).
            if self.array:
                try:
                    await asyncio.wait_for(self.array.close(), timeout=15)
                except asyncio.TimeoutError:
                    logger.warning("action_quit: array.close() timed out after 15s")
                except Exception as exc:
                    logger.warning("action_quit: array.close() failed: %s", exc)
            # 2) Release modprobe blacklists / udev rules.
            from airscope.setup.linux import release_all
            await asyncio.wait_for(asyncio.to_thread(release_all), timeout=30)
        except asyncio.TimeoutError:
            logger.warning("action_quit: cleanup timed out; forcing exit")
        except Exception as exc:
            logger.warning("action_quit: cleanup failed: %s", exc)
        finally:
            # 3) Restore interfaces (best-effort, in thread to avoid blocking).
            try:
                await asyncio.wait_for(asyncio.to_thread(_restore_wireless_interfaces), timeout=10)
            except Exception:
                pass
            # 4) ALWAYS exit.
            print("[airscope] action_quit: exiting", flush=True)
            self.exit()


# ---------------------------------------------------------------------------
# Wireless card cleanup safety net
# ---------------------------------------------------------------------------
#
# Textual's _on_exit_app is an INTERNAL method that does NOT call user-defined
# on_exit_app overrides. So a plain ``async def on_exit_app`` in AirscopeApp was
# dead code — it never fired when airscope exited via Ctrl+C, SIGTERM, or any
# path other than the 'q' keybinding.
#
# Instead we register a synchronous atexit handler + signal handlers that call
# _restore_wireless_interfaces(). This runs even on abnormal exit paths and is
# idempotent (release_all checks for conf files; interface restore skips
# non-monitor interfaces).

_CLEANUP_REGISTERED = False


def _restore_wireless_interfaces() -> None:
    """Best-effort: release blacklisted cards AND restore any monitor-mode
    interfaces back to managed mode so they are immediately usable after airscope exits.

    Called from action_quit (via the 'q' keybinding) and also registered as an
    atexit + signal handler. Idempotent: release_all() is a no-op when no
    airscope conf files exist, and interface restoration skips any iface that
    isn't in monitor mode.
    """
    # 1) Remove modprobe blacklists / udev rules installed by airscope setup.
    try:
        from airscope.setup.linux import release_all
        release_all()
    except Exception as exc:  # never let cleanup prevent exit
        logger.warning("_restore_wireless_interfaces: release_all failed: %s", exc)

    # 2) Restore any monitor-mode interface back to managed mode.
    try:
        result = subprocess.run(
            ["iw", "dev"], capture_output=True, text=True,
            timeout=5, check=False)
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith("Interface ") and len(stripped.split()) >= 2:
                iface_name = stripped.split()[1]
                info = subprocess.run(
                    ["iw", "dev", iface_name, "info"],
                    capture_output=True, text=True,
                    timeout=3, check=False)
                if "type monitor" in info.stdout:
                    logger.info("Restoring %s from monitor to managed mode.",
                                  iface_name)
                    subprocess.run(
                        f"ip link set {iface_name} down && iw dev {iface_name} \
set type managed && ip link set {iface_name} up",
                        shell=True, timeout=5, check=False)
    except Exception as exc:
        logger.warning("_restore_wireless_interfaces: interface restore failed: %s",
                      exc)


def _register_cleanup() -> None:
    """Register the wireless-card cleanup handler with atexit and signal handlers.

    SIGINT is intentionally NOT installed here. In Textual 8.x (app.py line 463),
    Ctrl+C is bound to ``action_help_quit`` which shows a notification telling the
    user to press 'q'. Calling ``sys.exit(0)`` from our own SIGINT handler fires
    *during* Textual's event-loop processing and raises SystemExit mid-message-pump,
    corrupting the queue so that pressing 'q' afterward does nothing — exactly the
    "can't exit airscope" symptom reported in production.

    Instead: let Textual handle Ctrl+C via its own key binding → user presses 'q'
    → ``action_quit()`` runs (``_restore_wireless_interfaces()`` + ``self.exit()``).
    The atexit handler below covers abnormal exits as a safety net. SIGTERM/SIGHUP
    (non-interactive kills) still get cleanup but without sys.exit, so the event loop
    stays in control.
    """
    global _CLEANUP_REGISTERED
    if _CLEANUP_REGISTERED:
        return
    _CLEANUP_REGISTERED = True
    atexit.register(_restore_wireless_interfaces)

    def _handle_termination(signum, frame):
        """Run cleanup for non-interactive signals (SIGTERM/SIGHUP).

        Does NOT call sys.exit — Textual's event loop must remain in control so that
        graceful shutdown via action_quit can complete normally.
        """
        _restore_wireless_interfaces()

    # SIGINT excluded: see docstring above. Only SIGTERM + SIGHUP here.
    for sig in (signal.SIGTERM, signal.SIGHUP):
        try:
            signal.signal(sig, _handle_termination)
        except (ValueError, OSError):
            pass  # not in main thread or signal unsupported

_FILE_LOGGING_CONFIGURED = False  # Avoid duplicate loggers


def _get_log_level(cli_log_level: Optional[str]) -> Optional[int]:
    """Level from ``AIRSCOPE_LOG`` or ``Config.log_level``, trace/debug/info/quiet."""
    env = os.environ.get("AIRSCOPE_LOG", cli_log_level)
    if env is None:
        env = Config.log_level
    env = env.strip().lower()
    if env == "trace":
        return log_trace.TRACE
    if env == "debug":
        return logging.DEBUG
    if env == "info":
        return logging.INFO
    return None  # any other value ("quiet") skips logging

def _configure_file_logging(cli_log_level: Optional[str]) -> None:
    """Files logged to ``airscope.log`` in ``~/.airscope/``."""
    global _FILE_LOGGING_CONFIGURED
    if _FILE_LOGGING_CONFIGURED:
        return

    level = _get_log_level(cli_log_level)
    if level is None:
        return

    from pathlib import Path
    log_dir = Path.home() / ".airscope"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_dir / "airscope.log", mode="w", encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s.%(msecs)03d %(levelname)-5s %(name)s: %(message)s",
        datefmt="%H:%M:%S"
    ))
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    _FILE_LOGGING_CONFIGURED = True
    logger.info(f"Logging enabled (level={logging.getLevelName(level)})")

