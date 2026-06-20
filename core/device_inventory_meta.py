"""
core/device_inventory_meta.py
==============================
Site metadata reference data + OEM/device-type auto-detection.

Three responsibilities:
  1. REGION_COUNTRY_MAP — provides the Region → Country dropdown chain
     used in the Approve workflow (US / EMEA / APAC → countries).
  2. detect_oem_and_type() — connects via SSH/Telnet and inspects the
     login banner / prompt to identify vendor + platform reliably,
     instead of guessing from hostname keywords alone.
  3. is_recognized_network_vendor() — the allowlist gate used by broad
     enterprise range scans to include ONLY confirmed network gear
     (routers/switches/firewalls/APs) and exclude servers, CCTV,
     printers, and other non-networking devices that happen to share
     the same subnet.
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
#
# This list is necessarily best-effort, not exhaustive — there are
# hundreds of networking vendors worldwide. It's an ALLOWLIST: a device
# is only classified as "network equipment" if it positively matches
# one of these signatures. Anything that doesn't match (a Linux server,
# a CCTV camera's HTTP admin banner, a printer, etc.) is correctly
# treated as "not recognized" rather than guessed at. If a real device
# in your environment isn't being picked up, the fix is adding its
# signature here — tell me the banner text and I'll add it.
OEM_SIGNATURES: List[Tuple[str, str, List[str]]] = [
    ("Cisco",      "cisco_nxos",     ["nx-os", "nexus operating system"]),
    ("Cisco",      "cisco_xr",       ["ios xr software", "ios-xr"]),
    ("Cisco",      "cisco_asa",      ["adaptive security appliance"]),
    ("Cisco",      "cisco_ios_xe",   ["ios xe software", "ios-xe"]),
    ("Cisco",      "cisco_ios",      ["cisco ios software", "cisco internetwork operating system",
                                       "ssh-2.0-cisco", "ssh-1.99-cisco"]),
    ("Juniper",    "juniper_junos",  ["junos", "juniper networks"]),
    ("Arista",     "arista_eos",     ["arista networks eos", "arista networks", "arista eos"]),
    ("Palo Alto",  "paloalto_panos", ["pan-os", "palo alto networks"]),
    ("Fortinet",   "fortinet",       ["fortios", "fortigate", "fortinet"]),
    ("HPE Aruba",  "aruba_os",       ["arubaos-cx", "aruba operating system", "aos-cx"]),
    ("Huawei",     "huawei_vrpv8",   ["vrp (r) software", "huawei versatile routing platform"]),
    ("Check Point", "checkpoint_gaia", ["check point gaia", "checkpoint gaia"]),
    ("Extreme Networks", "extreme_exos", ["extremexos", "extreme networks"]),
    ("Brocade/Ruckus",   "brocade_fastiron", ["fastiron", "netiron", "brocade", "ruckus"]),
    ("Dell Networking",  "dell_os10", ["dell networking os", "dell emc networking", "force10"]),
    ("MikroTik",   "mikrotik_routeros", ["mikrotik", "routeros", "rosssh"]),
    ("Ubiquiti",   "ubiquiti_unifi", ["ubiquiti", "unifi", "edgeos"]),
    ("F5",         "f5_bigip",       ["big-ip", "f5 networks"]),
    ("SonicWall",  "sonicwall",      ["sonicwall", "sonicos"]),
    ("WatchGuard", "watchguard",     ["watchguard", "fireware"]),
    ("Citrix/NetScaler", "citrix_netscaler", ["netscaler", "citrix"]),

    # ── Added after a follow-up audit — verified via documentation search,
    #    not just training-data memory (see commit notes / chat for sources) ──
    ("H3C / HPE Comware", "h3c_comware", ["h3c comware", "hangzhou h3c", "comware platform software"]),
    ("HP ProCurve / ArubaOS-Switch", "hp_procurve", ["procurve", "arubaos-switch"]),

    # ── Standard SMB/enterprise vendors — these follow the same widespread
    #    industry convention of stamping the brand name into the CLI/show-version
    #    banner, but I have NOT individually live-tested each one this session
    #    the way I did for Cisco's raw SSH banner. If one of these doesn't
    #    actually match your gear, tell me the real banner text and I'll
    #    correct the entry rather than leave a guess in place. ──
    ("Netgear",    "netgear",        ["netgear"]),
    ("TP-Link",    "tplink_omada",   ["tp-link", "omada"]),
    ("Zyxel",      "zyxel",          ["zyxel"]),
    ("D-Link",     "dlink",          ["d-link", "dlink"]),
    ("Allied Telesis", "allied_telesis", ["allied telesis", "alliedware"]),
    ("Ruijie",     "ruijie",         ["ruijie"]),
    ("Alcatel-Lucent Enterprise/Nokia", "ale_omniswitch", ["omniswitch", "alcatel-lucent"]),
    ("A10 Networks", "a10_acos",     ["a10 networks"]),
    ("Sophos",     "sophos_xg",      ["sophos"]),
    ("Barracuda",  "barracuda",      ["barracuda networks", "barracuda firewall"]),
]

# ═══════════════════════════════════════════════════════════════════════════════
# Known, VERIFIED gaps — not oversights, structural limitations of
# unauthenticated SSH/Telnet banner-grab as a detection method
# ═══════════════════════════════════════════════════════════════════════════════
#
# Cisco Meraki (MS switches, MR APs, MX firewalls): confirmed via Meraki's
#   own documentation/community — these devices have NO local SSH/Telnet
#   CLI at all by design; they're entirely cloud-managed through the Meraki
#   Dashboard/API. A banner-grab approach will never positively identify
#   Meraki gear. Detecting it would require either the Meraki Dashboard API
#   (needs an API key) or fingerprinting the device's local HTTP status
#   page, neither of which this module currently does.
#
# pfSense / OPNsense (and FreeBSD-based appliances generally): pfSense's
#   SSH banner used to literally include "FreeBSD-<date>" in the version
#   string, which would have been a usable (if generic) signal — but this
#   was DELIBERATELY REMOVED in current versions (see pfSense bug #3840)
#   specifically so automated scanners couldn't fingerprint the underlying
#   OS this way. The signal that used to exist no longer reliably does;
#   adding it back as a signature would be unreliable by design, not a
#   simple oversight, so it's intentionally not included here.


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
        # No vendor match — still return the banner snippet so callers
        # can show WHY a device was excluded (e.g. "SSH-2.0-OpenSSH_8.9p1
        # Ubuntu" is clearly a Linux server, not network gear), rather
        # than just silently saying "Unknown" with no evidence.
        return "Unknown", "", banner[:300]

    return "Unknown", "", ""


def is_recognized_network_vendor(device_type: str) -> bool:
    """
    True if device_type is a known network-equipment classification
    (i.e. detect_oem_and_type positively matched a vendor signature),
    False for "Unknown" or empty. Small semantic wrapper used as the
    gate for "network equipment only" filtering during broad scans.
    """
    return bool(device_type) and device_type != "Unknown"


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
