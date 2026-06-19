"""
core/device_inventory_meta.py
==============================
Site metadata reference data + OEM/device-type auto-detection.

Two responsibilities:
  1. REGION_COUNTRY_MAP — provides the Region → Country dropdown chain
     used in the Approve workflow (US / EMEA / APAC → countries).
  2. detect_oem_and_type() — connects via SSH/Telnet and inspects the
     login banner / prompt to identify vendor + platform reliably,
     instead of guessing from hostname keywords alone.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("NetBrain.InventoryMeta")


# ═══════════════════════════════════════════════════════════════════════════════
# Region → Country reference data
# ═══════════════════════════════════════════════════════════════════════════════

REGION_COUNTRY_MAP: Dict[str, List[str]] = {
    "US": [
        "United States", "Canada", "Mexico",
    ],
    "EMEA": [
        "United Kingdom", "Germany", "France", "Netherlands", "Spain",
        "Italy", "Switzerland", "Sweden", "Poland", "United Arab Emirates",
        "Saudi Arabia", "South Africa", "Ireland", "Belgium",
    ],
    "APAC": [
        "India", "China", "Japan", "Singapore", "Australia",
        "South Korea", "Indonesia", "Malaysia", "Thailand",
        "Hong Kong", "New Zealand", "Philippines", "Vietnam",
    ],
}

REGIONS: List[str] = list(REGION_COUNTRY_MAP.keys())


def countries_for_region(region: str) -> List[str]:
    """Return the country list for a given region (empty list if unknown)."""
    return REGION_COUNTRY_MAP.get(region, [])


# ═══════════════════════════════════════════════════════════════════════════════
# OEM / device-type detection via live banner grab
# ═══════════════════════════════════════════════════════════════════════════════
#
# Hostname-keyword guessing (e.g. "if 'router' in hostname") is unreliable —
# most production devices aren't named that helpfully. The reliable signal
# is the actual login banner / version string the device presents over
# SSH or Telnet. This module connects briefly, reads the banner/prompt,
# and matches known vendor signatures.

# (vendor_display, device_type_key, [signature substrings to match, case-insensitive])
OEM_SIGNATURES: List[Tuple[str, str, List[str]]] = [
    ("Cisco",      "cisco_nxos",     ["nx-os", "nexus operating system"]),
    ("Cisco",      "cisco_xr",       ["ios xr software", "ios-xr"]),
    ("Cisco",      "cisco_asa",      ["adaptive security appliance"]),
    ("Cisco",      "cisco_ios_xe",   ["ios xe software", "ios-xe"]),
    ("Cisco",      "cisco_ios",      ["cisco ios software", "cisco internetwork operating system"]),
    ("Juniper",    "juniper_junos",  ["junos", "juniper networks"]),
    ("Arista",     "arista_eos",     ["arista networks eos", "arista networks", "arista eos"]),
    ("Palo Alto",  "paloalto_panos", ["pan-os", "palo alto networks"]),
    ("Fortinet",   "fortinet",       ["fortios", "fortigate", "fortinet"]),
    ("HPE Aruba",  "aruba_os",       ["arubaos-cx", "aruba operating system", "aos-cx"]),
    ("Huawei",     "huawei_vrpv8",   ["vrp (r) software", "huawei versatile routing platform"]),
    ("Check Point",   "checkpoint_gaia", ["check point gaia", "checkpoint gaia"]),
]


def match_oem_signature(banner_text: str) -> Tuple[str, str]:
    """
    Match a banner/version string against known OEM signatures.
    Returns (vendor_display, device_type_key) or ("Unknown", "") if no match.
    """
    if not banner_text:
        return "Unknown", ""
    text_lower = banner_text.lower()
    for vendor, dtype, sigs in OEM_SIGNATURES:
        if any(sig in text_lower for sig in sigs):
            return vendor, dtype
    return "Unknown", ""


def detect_oem_and_type(
    ip: str,
    ssh_port: int = 22,
    telnet_port: int = 23,
    username: str = "",
    password: str = "",
    timeout: int = 8,
) -> Tuple[str, str, str]:
    """
    Attempt a brief connection to fingerprint the device.
    Returns (vendor_display, device_type_key, raw_banner_snippet).

    Strategy:
      1. Try SSH with a generic/autodetect Netmiko driver and read the
         banner/`show version` if login succeeds.
      2. If SSH fails, try a raw Telnet banner grab (no login needed —
         many devices show a banner before the login prompt).
      3. If both fail, return ("Unknown", "", "") — caller falls back to
         hostname-keyword guessing.
    """
    # ── Attempt 1: SSH with autodetect ──
    try:
        from netmiko import ConnectHandler
        from netmiko.ssh_autodetect import SSHDetect

        if username and password:
            guesser = SSHDetect(
                device_type="autodetect",
                host=ip, port=ssh_port,
                username=username, password=password,
                timeout=timeout,
            )
            best_match = guesser.autodetect()
            if best_match:
                # Netmiko's own driver name often encodes the vendor
                vendor, dtype = _netmiko_driver_to_vendor(best_match)
                if dtype:
                    return vendor, dtype, f"netmiko_autodetect:{best_match}"
    except Exception as exc:
        logger.debug(f"SSH autodetect failed for {ip}: {exc}")

    # ── Attempt 2: raw Telnet/SSH banner grab (no login) ──
    banner = _grab_raw_banner(ip, ssh_port) or _grab_raw_banner(ip, telnet_port)
    if banner:
        vendor, dtype = match_oem_signature(banner)
        if dtype:
            return vendor, dtype, banner[:300]

    return "Unknown", "", ""


def _netmiko_driver_to_vendor(driver_name: str) -> Tuple[str, str]:
    """Map a Netmiko autodetected driver string to (vendor, device_type)."""
    driver_lower = driver_name.lower()
    mapping = {
        "cisco_ios":      ("Cisco", "cisco_ios"),
        "cisco_xe":       ("Cisco", "cisco_ios_xe"),
        "cisco_nxos":     ("Cisco", "cisco_nxos"),
        "cisco_asa":      ("Cisco", "cisco_asa"),
        "cisco_xr":       ("Cisco", "cisco_xr"),
        "juniper_junos":  ("Juniper", "juniper_junos"),
        "arista_eos":     ("Arista", "arista_eos"),
        "paloalto_panos": ("Palo Alto", "paloalto_panos"),
        "fortinet":       ("Fortinet", "fortinet"),
        "huawei":         ("Huawei", "huawei_vrpv8"),
    }
    for key, val in mapping.items():
        if key in driver_lower:
            return val
    return "Unknown", ""


def _grab_raw_banner(ip: str, port: int, timeout: float = 5.0) -> Optional[str]:
    """Open a raw TCP socket and read whatever banner the device sends first."""
    import socket
    try:
        with socket.create_connection((ip, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            data = sock.recv(2048)
            return data.decode(errors="ignore")
    except Exception as exc:
        logger.debug(f"Banner grab failed for {ip}:{port}: {exc}")
        return None
