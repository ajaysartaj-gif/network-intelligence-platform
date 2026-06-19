"""
core/topology/role_classifier.py
=================================
Classifies a device's role (router / switch / access point / firewall)
for diagram icon + color selection.

This is data classification based on real, observable vendor strings
(CDP capability codes, platform model names) — not a diagnostic
judgment call, so unlike command selection in the Intent Engine, fixed
substring matching here is appropriate and reliable.
"""
from __future__ import annotations

from typing import Optional

from core.topology.topology_models import DeviceRole


# Known firewall platform substrings (vendor product naming, not commands)
_FIREWALL_PLATFORM_HINTS = [
    "asa", "firepower", "ftd", "pa-", "pa220", "pa400", "pa800", "pa3",
    "pa5", "pa7", "fortigate", "srx",  # SRX can be router OR firewall; see note below
    "checkpoint", "palo alto",
]

_ACCESS_POINT_PLATFORM_HINTS = [
    "air-ap", "air-cap", "air-lap", "c9130", "c9120", "c9105", "c9115",
    "ap-", "aironet", "meraki mr", "instant ap", "iap-",
]

_PHONE_PLATFORM_HINTS = [
    "cp-", "ip phone", "cisco ip phone",
]


def classify_role(
    vendor: str = "",
    device_type: str = "",
    platform_string: str = "",
    capabilities: str = "",
) -> DeviceRole:
    """
    Determine DeviceRole from the best available evidence, in priority order:
      1. Known firewall vendor/device_type (from our own approved inventory metadata)
      2. Platform string hints (model names seen in CDP/LLDP output)
      3. CDP/LLDP capability codes ("Router", "Switch", "Phone", etc.)
      4. Fallback: UNKNOWN
    """
    dt = (device_type or "").lower()
    plat = (platform_string or "").lower()
    caps = (capabilities or "").lower()
    vnd = (vendor or "").lower()

    # ── 1. Inventory-level vendor/device_type signals (most reliable) ──
    if dt in ("paloalto_panos", "fortinet", "cisco_asa", "checkpoint_gaia"):
        return DeviceRole.FIREWALL
    if "firewall" in vnd or "palo alto" in vnd or "fortinet" in vnd or "check point" in vnd:
        return DeviceRole.FIREWALL

    # ── 2. Platform string hints (from CDP/LLDP neighbor data) ──
    if any(h in plat for h in _FIREWALL_PLATFORM_HINTS):
        return DeviceRole.FIREWALL
    if any(h in plat for h in _ACCESS_POINT_PLATFORM_HINTS):
        return DeviceRole.ACCESS_POINT
    if any(h in plat for h in _PHONE_PLATFORM_HINTS):
        return DeviceRole.PHONE

    # ── 3. CDP/LLDP capability codes ──
    # Cisco CDP capabilities commonly appear as words: "Router", "Switch",
    # "Trans-Bridge", "IGMP", "Phone", "Host", etc. A device can report
    # multiple; prefer the most specific physical role.
    if "phone" in caps:
        return DeviceRole.PHONE
    if "router" in caps and "switch" not in caps:
        return DeviceRole.ROUTER
    if "switch" in caps and "router" not in caps:
        return DeviceRole.SWITCH
    if "router" in caps and "switch" in caps:
        # L3 switch / multilayer device reporting both — default to switch
        # since that's the more common physical form factor in CDP output.
        return DeviceRole.SWITCH
    if "host" in caps and "ap" in plat:
        return DeviceRole.ACCESS_POINT

    # ── 4. device_type fallback (our own inventory classification) ──
    if "nxos" in dt or "switch" in dt:
        return DeviceRole.SWITCH
    if "ios" in dt or "junos" in dt or "eos" in dt:
        return DeviceRole.ROUTER

    return DeviceRole.UNKNOWN
