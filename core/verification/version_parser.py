"""
core/verification/version_parser.py
===================================
Parse `show version` output across vendors to extract:
  - vendor family (cisco / juniper / arista / paloalto / fortinet / huawei)
  - platform     (ios / ios-xe / nx-os / junos / eos / panos / fortios / vrp)
  - release      (e.g. '17.9.1a', '20.4R3', '4.30.1F', '11.0.5')
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("NetBrain.Verification.VersionParser")


@dataclass
class DeviceVersion:
    """Parsed version info from `show version`."""
    vendor:   str = "unknown"      # canonical vendor key
    platform: str = "unknown"      # canonical platform key
    release:  str = ""             # e.g. '17.9.1a'
    raw:      str = ""             # snippet that matched

    def as_string(self) -> str:
        if self.release:
            return f"{self.platform} {self.release}"
        return self.platform


# ═══════════════════════════════════════════════════════════════════════════════
# Per-vendor regex patterns
# ═══════════════════════════════════════════════════════════════════════════════

CISCO_IOS_XE_PATTERN = re.compile(
    r"Cisco\s+IOS\s+XE\s+(?:Software,\s+)?(?:Version\s+)?(\d+\.\d+\.\d+[a-z]?)",
    re.IGNORECASE,
)

CISCO_IOS_PATTERN = re.compile(
    r"Cisco\s+IOS\s+Software.*?Version\s+(\d+\.\d+(?:\(\d+[A-Z]?\))?)",
    re.IGNORECASE | re.DOTALL,
)

CISCO_NX_OS_PATTERN = re.compile(
    r"(?:NX-OS|Nexus\s+Operating\s+System).*?Version\s+(\d+\.\d+(?:\(\d+\))?[a-zA-Z]?)",
    re.IGNORECASE | re.DOTALL,
)

CISCO_ASA_PATTERN = re.compile(
    r"Cisco\s+Adaptive\s+Security\s+Appliance\s+Software\s+Version\s+(\d+\.\d+(?:\(\d+\))?)",
    re.IGNORECASE,
)

CISCO_XR_PATTERN = re.compile(
    r"Cisco\s+IOS\s+XR\s+Software.*?Version\s+(\d+\.\d+\.\d+)",
    re.IGNORECASE | re.DOTALL,
)

JUNIPER_PATTERN = re.compile(
    r"Junos(?:\s*OS)?[:\s]+(?:Release\s+|version\s+)?(\d+\.\d+R\d+(?:[-.][A-Z\d.]+)?)",
    re.IGNORECASE,
)

ARISTA_PATTERN = re.compile(
    r"EOS\s+(?:version[:\s]+|version\s+)?(\d+\.\d+(?:\.\d+[A-Z]?)?)",
    re.IGNORECASE,
)

PALO_ALTO_PATTERN = re.compile(
    r"PAN-OS\s+(?:version\s+)?(\d+\.\d+(?:\.\d+)?(?:-h\d+)?)",
    re.IGNORECASE,
)

FORTINET_PATTERN = re.compile(
    r"FortiGate.*?v(\d+\.\d+\.\d+),build",
    re.IGNORECASE | re.DOTALL,
)

HUAWEI_PATTERN = re.compile(
    r"VRP\s+\(R\)\s+software.*?Version\s+(\d+\.\d+(?:\(\w+\))?)",
    re.IGNORECASE | re.DOTALL,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Main parser
# ═══════════════════════════════════════════════════════════════════════════════

def parse_show_version(output: str) -> DeviceVersion:
    """
    Parse `show version` text and return a DeviceVersion.
    Returns DeviceVersion(vendor='unknown', platform='unknown') if no match.
    """
    if not output:
        return DeviceVersion()

    # ── Order matters: try most specific patterns first ──
    candidates = [
        ("cisco", "ios-xe", CISCO_IOS_XE_PATTERN),
        ("cisco", "nx-os",  CISCO_NX_OS_PATTERN),
        ("cisco", "asa",    CISCO_ASA_PATTERN),
        ("cisco", "ios-xr", CISCO_XR_PATTERN),
        ("cisco", "ios",    CISCO_IOS_PATTERN),
        ("juniper", "junos", JUNIPER_PATTERN),
        ("arista", "eos",   ARISTA_PATTERN),
        ("paloalto", "panos", PALO_ALTO_PATTERN),
        ("fortinet", "fortios", FORTINET_PATTERN),
        ("huawei", "vrp",   HUAWEI_PATTERN),
    ]

    for vendor, platform, pattern in candidates:
        m = pattern.search(output)
        if m:
            return DeviceVersion(
                vendor=vendor,
                platform=platform,
                release=m.group(1),
                raw=m.group(0),
            )

    return DeviceVersion()


def compare_versions(version_a: str, version_b: str) -> int:
    """
    Compare two release strings semver-style.
    Returns -1 if a<b, 0 if equal, 1 if a>b.
    Handles 'IOS XE 17.9.1a', 'Junos 20.4R3', etc.
    """
    def normalize(v: str) -> list:
        # Extract numeric components, keep order
        parts = re.findall(r"\d+", v or "")
        return [int(p) for p in parts]

    a = normalize(version_a)
    b = normalize(version_b)

    # Pad shorter list with zeros
    while len(a) < len(b):
        a.append(0)
    while len(b) < len(a):
        b.append(0)

    if a < b:
        return -1
    if a > b:
        return 1
    return 0
