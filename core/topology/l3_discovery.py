"""
core/topology/l3_discovery.py
===============================
IP subnet discovery — what subnet is directly connected to each
interface, per device. This is the data the LOGICAL (Layer 3) topology
view is built from, as distinct from discovery.py's CDP/LLDP PHYSICAL
adjacency discovery: physical topology answers "what's cabled to
what"; this answers "do the two ends of that cable actually agree on
an IP subnet" — which is exactly the kind of thing CDP/LLDP can't see
(a cable can be physically connected and CDP-visible while the IP
addressing on either end is broken or simply not yet configured).

Command/parsing strategy mirrors discovery.py exactly:
  1. Try Netmiko's `use_textfsm=True` (ntc-templates), the same library
     already in requirements.txt.
  2. If TextFSM parsing fails, fall back to a regex parser. This isn't
     just defensive boilerplate here -- it was confirmed NECESSARY
     during development: the real cisco_xr ntc-template throws a hard
     parse error on route-table line formats it doesn't model (e.g. a
     static default route with no trailing interface field), so a
     single malformed/unmodeled line elsewhere in the routing table
     would otherwise take down subnet discovery for the whole device.
  3. Only "show ip route" connected/local routes are used -- we are
     not trying to model the full routing table, just "what subnet is
     configured on each interface", which is a much narrower and more
     robust thing to parse than the entire RIB.

Vendor coverage: verified (via direct TextFSM testing against sourced,
real command output) for cisco_ios, cisco_ios_xe, cisco_nxos, cisco_xr.
Other vendors in discovery.py's CDP/LLDP map (Arista, Juniper, Aruba,
PAN-OS, Fortinet) are NOT yet covered here -- "show ip route" syntax
and connected-route formatting differs enough per platform that
shipping unverified parsing for them would violate the same
verify-before-shipping standard the rest of this codebase holds to.
Devices on unsupported vendors simply get no interface_subnets data,
which the Logical view renders as "L3 status unknown" rather than
"mismatched" -- a correctly honest state, not an error.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from ipaddress import ip_network
from typing import Any, Dict, List, Optional

from core.topology.discovery import normalize_interface_name

logger = logging.getLogger("NetBrain.Topology.L3Discovery")

try:
    from netmiko import ConnectHandler
    NETMIKO_OK = True
except ImportError:
    NETMIKO_OK = False


# ═══════════════════════════════════════════════════════════════════════════════
# Vendor → command map (verified subset -- see module docstring)
# ═══════════════════════════════════════════════════════════════════════════════

VENDOR_L3_COMMANDS: Dict[str, Dict[str, Any]] = {
    "cisco_ios":    {"command": "show ip route", "textfsm_platform": "cisco_ios"},
    "cisco_ios_xe": {"command": "show ip route", "textfsm_platform": "cisco_ios"},
    "cisco_nxos":   {"command": "show ip route", "textfsm_platform": "cisco_nxos"},
    "cisco_xr":     {"command": "show ip route", "textfsm_platform": "cisco_xr"},
}

# Each vendor's TextFSM output uses different field names/values to mark a
# "directly connected" route -- verified directly against each real
# ntc-template's actual parsed output, not assumed to be consistent across
# vendors. Field names are lowercase because get_structured_data() (via
# netmiko's clitable_to_dict) lowercases every key from the template's
# UPPERCASE Value declarations -- confirmed by testing actual parsed
# output, not by reading the template source alone, since that's an easy
# mismatch to miss (the template file itself declares e.g. "Value PROTOCOL").
#   cisco_ios / cisco_ios_xe : protocol == "C",      interface field = nexthop_if
#   cisco_nxos                : protocol == "direct", interface field = nexthop_if
#   cisco_xr                  : protocol == "C" and type == "directly", interface field = interface
_CONNECTED_MATCHERS: Dict[str, Any] = {
    "cisco_ios":    lambda r: r.get("protocol") == "C",
    "cisco_ios_xe": lambda r: r.get("protocol") == "C",
    "cisco_nxos":   lambda r: r.get("protocol") == "direct",
    "cisco_xr":     lambda r: r.get("protocol") == "C" and r.get("type") == "directly",
}
_INTERFACE_FIELD: Dict[str, str] = {
    "cisco_ios": "nexthop_if", "cisco_ios_xe": "nexthop_if",
    "cisco_nxos": "nexthop_if", "cisco_xr": "interface",
}


@dataclass
class InterfaceSubnetRecord:
    interface: str = ""     # normalized, e.g. "Fa0/0"
    subnet: str = ""        # e.g. "192.168.96.0/24"


@dataclass
class L3DiscoveryResult:
    device_ip: str = ""
    success: bool = False
    subnets: List[InterfaceSubnetRecord] = field(default_factory=list)
    error: Optional[str] = None
    raw_output: str = ""


def discover_ip_subnets(device: Any) -> L3DiscoveryResult:
    """
    Connect to one device and determine which subnet is directly
    connected on each of its interfaces, via "show ip route".
    `device` is a DiscoveredDevice (has .ip, .device_type, .ssh_port).
    Separate SSH session from discovery.py's CDP/LLDP poll -- kept
    modular and independently testable; topology_engine.py calls both.
    """
    result = L3DiscoveryResult(device_ip=device.ip)

    if not NETMIKO_OK:
        result.error = "netmiko not installed"
        return result

    cmd_cfg = VENDOR_L3_COMMANDS.get(device.device_type)
    if not cmd_cfg:
        result.error = f"L3 discovery not supported for device_type '{device.device_type}'"
        return result

    cfg = dict(
        device_type=device.device_type or "cisco_ios",
        host=device.ip,
        port=int(getattr(device, "ssh_port", 22) or 22),
        username=os.environ.get("GNS3_SSH_USER", "admin"),
        password=os.environ.get("GNS3_SSH_PASS", "admin"),
        timeout=25, auth_timeout=25,
        fast_cli=False, global_delay_factor=2,
    )
    secret = os.environ.get("GNS3_SSH_SECRET", "")
    if secret:
        cfg["secret"] = secret

    try:
        conn = ConnectHandler(**cfg)
        try:
            conn.enable()
        except Exception:
            pass

        raw = conn.send_command(cmd_cfg["command"], read_timeout=20)
        result.raw_output = raw

        try:
            conn.disconnect()
        except Exception:
            pass

        parsed = _parse_with_textfsm(raw, device.device_type, cmd_cfg["command"], cmd_cfg["textfsm_platform"])
        if parsed is not None:
            result.subnets = _extract_connected_subnets(parsed, device.device_type)
        else:
            # Regex fallback is intentionally vendor-agnostic (see its
            # docstring) and already filters down to only connected
            # routes -- it must NOT be re-passed through the vendor-
            # specific PROTOCOL matcher in _extract_connected_subnets,
            # since that matcher expects each vendor's own PROTOCOL
            # value (e.g. NX-OS's "direct") and the regex path doesn't
            # replicate that per-vendor distinction.
            result.subnets = _parse_connected_regex(raw)
            logger.debug(f"L3 discovery on {device.ip} used regex fallback")

        result.success = True

    except Exception as exc:
        result.error = str(exc)
        result.success = False

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# TextFSM parsing
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_with_textfsm(
    raw_output: str, device_type: str, command: str, textfsm_platform: Optional[str],
) -> Optional[List[Dict[str, Any]]]:
    if not textfsm_platform:
        return None
    try:
        from netmiko.utilities import get_structured_data
        parsed = get_structured_data(raw_output, platform=textfsm_platform, command=command)
        if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
            return parsed
        return None
    except Exception as exc:
        # Confirmed via testing this is a REAL failure mode, not just a
        # defensive hypothetical -- the cisco_xr template throws a hard
        # TextFSMError on route lines it doesn't model (e.g. a static
        # default route with no trailing interface field), so any
        # unmodeled line elsewhere in a real device's routing table
        # would otherwise take down subnet discovery entirely.
        logger.debug(f"TextFSM parse failed ({textfsm_platform}/{command}): {exc}")
        return None


def _extract_connected_subnets(
    records: Optional[List[Dict[str, Any]]], device_type: str,
) -> List[InterfaceSubnetRecord]:
    if not records:
        return []
    is_connected = _CONNECTED_MATCHERS.get(device_type)
    iface_field = _INTERFACE_FIELD.get(device_type, "NEXTHOP_IF")
    if not is_connected:
        return []

    out: List[InterfaceSubnetRecord] = []
    seen: set = set()
    for r in records:
        try:
            if not is_connected(r):
                continue
            network = r.get("network", "")
            prefix = r.get("prefix_length", "")
            iface = r.get(iface_field, "")
            if not network or not prefix or not iface:
                continue
            # /32 (or /31, /30 point-to-point host-style) "local" routes
            # aren't useful subnet boundaries for L3-match comparison --
            # only real connected-route prefixes are. cisco_ios/ios_xe/xr
            # surface BOTH "C" (subnet) and "L" (host /32) routes per
            # interface; NX-OS surfaces "direct" (subnet) and "local"
            # (host) similarly. The matcher above already filters to only
            # the subnet-level connected routes, so no extra check needed
            # here beyond a sanity floor on prefix length.
            prefix_int = int(prefix)
            if prefix_int >= 31:
                continue
            cidr = f"{network}/{prefix}"
            subnet = str(ip_network(cidr, strict=False))
            norm_iface = normalize_interface_name(iface)
            key = (norm_iface, subnet)
            if key in seen:
                continue
            seen.add(key)
            out.append(InterfaceSubnetRecord(interface=norm_iface, subnet=subnet))
        except (ValueError, TypeError) as exc:
            logger.debug(f"Skipping malformed L3 route record {r}: {exc}")
            continue
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# Regex fallback — only needs to find "X is directly connected, Y" lines
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_connected_regex(raw: str) -> List[InterfaceSubnetRecord]:
    """
    Minimal fallback: find connected-route lines and extract subnet +
    interface, handling the two structurally different shapes
    separately rather than with one generic pattern (a single
    right-anchored regex was tried first and found, via testing, to
    misfire on the NX-OS two-line shape -- it would walk past the real
    interface and capture the trailing "direct"/"local" keyword
    instead, since that keyword is itself a valid-looking identifier
    token sitting closer to the end of the merged line).

    Two shapes handled:
      - Single-line (IOS/XR): "C  net/pfx is directly connected, [uptime,] Iface"
      - Two-line (NX-OS):      "net/pfx, ubest/mbest: n/n, attached"
                                "    *via ip, Iface, [dist/metric], uptime, direct"
    """
    if not raw:
        return []
    out: List[InterfaceSubnetRecord] = []
    seen: set = set()
    lines = raw.splitlines()

    def _add(network: str, prefix: str, iface_raw: str) -> None:
        try:
            prefix_int = int(prefix)
            if prefix_int >= 31:
                return
            subnet = str(ip_network(f"{network}/{prefix}", strict=False))
        except (ValueError, TypeError):
            return
        norm_iface = normalize_interface_name(iface_raw)
        key = (norm_iface, subnet)
        if key in seen:
            return
        seen.add(key)
        out.append(InterfaceSubnetRecord(interface=norm_iface, subnet=subnet))

    for i, line in enumerate(lines):
        net_m = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})/(\d{1,2})", line)
        if not net_m:
            continue

        # Shape 1: single-line "is directly connected" (IOS/XR)
        if "is directly connected" in line:
            iface_m = re.search(r",\s*([A-Za-z][\w\-\./]+)\s*$", line.strip())
            if iface_m:
                _add(net_m.group(1), net_m.group(2), iface_m.group(1))
            continue

        # Shape 2: two-line NX-OS "ubest/mbest" + following "*via" line.
        # Interface sits specifically between the next-hop and the next
        # comma -- captured with an explicit boundary on both sides
        # rather than scanning from the end of the line, which is what
        # broke on the trailing "direct"/"local" keyword previously.
        if "ubest/mbest" in line and i + 1 < len(lines):
            next_line = lines[i + 1]
            if "direct" not in next_line:
                continue  # "local"-only or routed (non-connected) entry
            via_m = re.search(r"\*via\s+\S+,\s*([A-Za-z][\w\-\./]*?)\s*,", next_line)
            if via_m:
                _add(net_m.group(1), net_m.group(2), via_m.group(1))

    return out
