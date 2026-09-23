"""Starter, stopper, and maintainer of the currently-active campaign."""
from __future__ import annotations

from typing import Optional

from airscope.campaigns.campaign import Campaign
from airscope.campaigns.wep import WepCampaign
from airscope.campaigns.eviltwin import EvilTwinCampaign, EvilTwinInput


class CampaignControls:
    def __init__(self) -> None:
        self._campaign: Optional[Campaign] = None   # current campaign

    @property
    def current(self) -> Optional[Campaign]:
        """Current active campaign, or None."""
        return self._campaign

    def start(self, campaign: type[Campaign], array, ap, *,
              log=None, evil_input: Optional[EvilTwinInput] = None,
              recovered: Optional[object] = None,
              existing_handshake_path=None) -> Optional[Campaign]:
        """Construct and run one campaign, None if another campaign is active.

        Constructors differ per campaign (intentionally not unified): wep takes
        ``log_callback``, EvilTwin takes its ``evil_input`` dataclass, the rest take ``log``.
        ``recovered`` is set on EvilTwin before it runs, so a live MIC win can toast immediately.
        """
        if Campaign.active is not None or self._campaign is not None:
            return None
        if campaign is WepCampaign:
            inst = campaign(array, ap, log_callback=log)
        elif campaign is EvilTwinCampaign:
            inst = campaign(array, ap, evil_input, log=log,
                            existing_handshake_path=existing_handshake_path)
            if recovered is not None:
                inst.on_recovered = recovered
        else:
            inst = campaign(array, ap, log=log)
        inst.run()
        self._campaign = inst
        return inst

    def request_stop(self) -> None:
        """Ask the running campaign to stop; keep it so ``reap()`` still logs its result."""
        if self._campaign is not None:
            self._campaign.request_stop()

    def stop(self) -> None:
        """Stop and forget immediately (leaving the screen); no result is reaped."""
        if self._campaign is not None:
            self._campaign.request_stop()
            self._campaign = None

    def reap(self) -> Optional[Campaign]:
        """The just-finished campaign (cleared), or None while it is still running."""
        camp = self._campaign
        if camp is not None and camp.done:
            self._campaign = None
            return camp
        return None
