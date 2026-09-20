"""WEP attack suite (fake-auth, ARP replay, ChopChop, PTW crack).

The orchestrator ``WepCampaign`` lives in ``campaign.py``; it is re-exported here
so callers use ``from airscope.campaigns.wep import WepCampaign``.
"""
from airscope.campaigns.wep.campaign import WepCampaign

__all__ = ["WepCampaign"]
