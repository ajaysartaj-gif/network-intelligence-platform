"""
core/knowledge/cache/ttl_policy.py
==================================
Per-vendor TTL (time-to-live) policies for cached knowledge.

Different vendors update docs at different cadences — Cisco IOS classic
rarely changes, while Palo Alto PAN-OS evolves quickly. TTL controls when
we re-fetch from the source.
"""
from typing import Dict


# TTL in days per vendor.  Defaults are conservative — change if needed.
VENDOR_TTL_DAYS: Dict[str, int] = {
    "cisco":     90,   # IOS/IOS-XE — relatively stable
    "juniper":   90,
    "arista":    90,
    "paloalto":  60,   # PAN-OS updates frequently
    "fortinet":  60,
    "huawei":    90,
    "aruba":     90,
    "checkpoint":90,
    "rfc":       365,  # IETF RFCs rarely change
    "unknown":   30,   # Be safe — refresh often if vendor unknown
}


def get_ttl(vendor: str) -> int:
    """Return TTL in days for a given vendor."""
    return VENDOR_TTL_DAYS.get((vendor or "").lower(), 30)
