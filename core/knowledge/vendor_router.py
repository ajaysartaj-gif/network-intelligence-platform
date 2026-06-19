"""
core/knowledge/vendor_router.py
===============================
Routes a vendor key to the correct VendorFetcher instance.

Adding a new vendor is just one line in `_FETCHERS` plus the fetcher file.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from core.knowledge.fetchers.base_fetcher import VendorFetcher
from core.knowledge.fetchers.cisco_fetcher import CiscoFetcher
from core.knowledge.fetchers.juniper_fetcher import JuniperFetcher
from core.knowledge.fetchers.arista_fetcher import AristaFetcher
from core.knowledge.fetchers.paloalto_fetcher import PaloAltoFetcher
from core.knowledge.fetchers.fortinet_fetcher import FortinetFetcher
from core.knowledge.fetchers.aruba_fetcher import ArubaFetcher

logger = logging.getLogger("NetBrain.Knowledge.VendorRouter")


# ── Single instance per vendor (fetchers are stateless, safe to share) ──────
_FETCHERS: Dict[str, VendorFetcher] = {
    "cisco":    CiscoFetcher(),
    "juniper":  JuniperFetcher(),
    "arista":   AristaFetcher(),
    "paloalto": PaloAltoFetcher(),
    "fortinet": FortinetFetcher(),
    "aruba":    ArubaFetcher(),
}


def get_fetcher(vendor: str) -> Optional[VendorFetcher]:
    """Return the right fetcher for a vendor, or None if not supported."""
    return _FETCHERS.get((vendor or "").lower().strip())


def supported_vendors() -> List[str]:
    """List all vendors that have a fetcher."""
    return list(_FETCHERS.keys())


def health_check_all() -> Dict[str, dict]:
    """Report status of every fetcher (used by admin UI)."""
    return {
        vendor: {
            "display_name": f.display_name,
            "trusted_domains": f.trusted_domains,
            "available": True,
        }
        for vendor, f in _FETCHERS.items()
    }
