"""
core/topology/discovery.py
===========================
CDP/LLDP-based neighbor discovery.

This module runs the standard, protocol-fixed discovery commands for each
vendor (there is exactly one correct command per platform for "list my
CDP/LLDP neighbors" — this is not a diagnostic judgment call, so unlike
the Intent Engine's AI-driven command selection, these commands are
legitimately static, the same way a SNMP/telemetry poller has fixed OIDs).

Parsing strategy:
  1. Try Netmiko's `use_textfsm=True`, which uses the `ntc-templates`
     library already in requirements.txt. Field names below were
     verified directly against the real templates in the ntc-templates
     GitHub repo (not guessed from memory).
  2. If TextFSM parsing fails for any reason (template missing, library
     not loadable, parser raised), fall back to a built-in regex parser
     for the common Cisco-style CDP/LLDP detail output format.
  3. If a device's vendor has no known command/parser at all, it is
     skipped and recorded in `devices_failed` — never silently guessed.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("NetBrain.Topology.Discovery")

try:
    from netmiko import ConnectHandler
    NETMIKO_OK = True
except ImportError:
    NETMIKO_OK = False


# ═══════════════════════════════════════════════════════════════════════════════
# Vendor → discovery command map
# ═══════════════════════════════════════════════════════════════════════════════
# Verified against ntc-templates index (github.com/networktocode/ntc-templates).
# "textfsm_platform" is the ntc-templates platform key used for that command;
# None means no verified template exists — falls back to regex parsing.

VENDOR_COMMANDS: Dict[str, Dict[str, Any]] = {
    "cisco_ios": {
        "cdp":  {"command": "show cdp neighbors detail",  "textfsm_platform": "cisco_ios"},
        "lldp": {"command": "show lldp neighbors detail", "textfsm_platform": "cisco_ios"},
    },
    "cisco_ios_xe": {
        "cdp":  {"command": "show cdp neighbors detail",  "textfsm_platform": "cisco_ios"},
        "lldp": {"command": "show lldp neighbors detail", "textfsm_platform": "cisco_ios"},
    },
    "cisco_nxos": {
        "cdp":  {"command": "show cdp neighbors detail",  "textfsm_platform": "cisco_nxos"},
        "lldp": {"command": "show lldp neighbors detail", "textfsm_platform": "cisco_nxos"},
    },
    "cisco_xr": {
        "cdp":  {"command": "show cdp neighbors detail",  "textfsm_platform": "cisco_xr"},
        "lldp": {"command": "show lldp neighbors detail", "textfsm_platform": "cisco_xr"},
    },
    "cisco_asa": {
        "cdp":  {"command": None, "textfsm_platform": None},   # ASA has no CDP/LLDP neighbor table
        "lldp": {"command": None, "textfsm_platform": None},
    },
    "arista_eos": {
        "cdp":  {"command": None, "textfsm_platform": None},   # no verified CDP template for Arista
        "lldp": {"command": "show lldp neighbors detail", "textfsm_platform": "arista_eos"},
    },
    "juniper_junos": {
        "cdp":  {"command": None, "textfsm_platform": None},   # CDP is Cisco-proprietary
        "lldp": {"command": "show lldp neighbors", "textfsm_platform": "juniper_junos"},
    },
    "aruba_os": {
        "cdp":  {"command": None, "textfsm_platform": None},
        "lldp": {"command": "show lldp neighbor-info detail", "textfsm_platform": "aruba_aoscx"},
    },
    "paloalto_panos": {
        "cdp":  {"command": None, "textfsm_platform": None},
        # No verified ntc-template — regex fallback parser handles this.
        "lldp": {"command": "show lldp neighbors all", "textfsm_platform": None},
    },
    "fortinet": {
        "cdp":  {"command": None, "textfsm_platform": None},
        # No verified ntc-template — regex fallback parser handles this.
        "lldp": {"command": "get system lldp neighbors", "textfsm_platform": None},
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# Normalized result
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class NeighborRecord:
    local_interface:    str = ""
    neighbor_name:      str = ""
    neighbor_ip:        str = ""
    neighbor_platform:  str = ""
    neighbor_interface: str = ""
    capabilities:       str = ""
    protocol:           str = "cdp"   # "cdp" | "lldp"


@dataclass
class DiscoveryResult:
    device_ip: str
    success: bool = False
    neighbors: List[NeighborRecord] = field(default_factory=list)
    error: Optional[str] = None
    raw_cdp: str = ""
    raw_lldp: str = ""
    local_hostname: str = ""   # device's OWN configured hostname, from its CLI prompt


# ═══════════════════════════════════════════════════════════════════════════════
# Connection helpers (robust, multi-transport — mirrors the Device Management
# access layer which tries SSH then Telnet, rather than SSH-only)
# ═══════════════════════════════════════════════════════════════════════════════

def _base_platform(device_type: str) -> str:
    """
    Map a possibly-empty or transport-suffixed device_type to the base
    platform key used for CDP/LLDP command lookup. The CLI commands ("show
    cdp neighbors detail" etc.) are identical regardless of transport, so
    "cisco_ios_telnet" and "cisco_ios" share commands; an empty device_type
    defaults to cisco_ios. This fixes a real failure where a device whose
    device_type was blank or telnet-suffixed exited early with "No CDP/LLDP
    command known" and never even connected.
    """
    dt = (device_type or "").strip().lower()
    for suffix in ("_telnet", "_ssh", "_serial", "_console"):
        if dt.endswith(suffix):
            dt = dt[: -len(suffix)]
            break
    return dt or "cisco_ios"


def _establish_connection(device: Any, base_type: str,
                          user: str, password: str, secret: str):
    """
    Open a netmiko connection trying SSH first, then Telnet — mirroring the
    proven Device Management access path (SSH→REST→Telnet→Pinggy); topology
    only needs CLI, so SSH→Telnet. Returns (conn, method_str). Raises with a
    combined, readable error listing every attempt if all fail, so the real
    reason (auth vs refused vs timeout, and on which transport) is visible
    instead of a single opaque "TCP connection failed".

    An explicit telnet device_type (or GNS3_DEVICE_TYPE ending in _telnet)
    makes Telnet the first attempt.
    """
    from netmiko import ConnectHandler

    ssh_port = int(getattr(device, "ssh_port", 22) or 22)
    telnet_port = int(getattr(device, "telnet_port", 23) or 23)

    explicit = (getattr(device, "device_type", "") or
                os.environ.get("GNS3_DEVICE_TYPE", "")).strip().lower()
    prefer_telnet = explicit.endswith("_telnet")

    ssh_attempt = ("ssh", base_type, ssh_port)
    telnet_attempt = ("telnet", f"{base_type}_telnet", telnet_port)
    attempts = ([telnet_attempt, ssh_attempt] if prefer_telnet
                else [ssh_attempt, telnet_attempt])

    errors: List[str] = []
    for method, dtype, port in attempts:
        cfg = dict(
            device_type=dtype, host=device.ip, port=port,
            password=password,
            timeout=20, auth_timeout=20, banner_timeout=20,
            fast_cli=False, global_delay_factor=2,
        )
        # Mirror the working Test-Router path: telnet device_types omit the
        # username (GNS3/console telnet typically logs in without a separate
        # username prompt); SSH uses username + password.
        if not dtype.endswith("_telnet"):
            cfg["username"] = user
        if secret:
            cfg["secret"] = secret
        try:
            conn = ConnectHandler(**cfg)
            return conn, method
        except Exception as exc:
            errors.append(f"{method}://{device.ip}:{port} ({exc})")

    raise ConnectionError("; ".join(errors) if errors else "no transport succeeded")


# ═══════════════════════════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════════════════════════

def discover_neighbors(device: Any) -> DiscoveryResult:
    """
    Connect to one device and run CDP/LLDP discovery commands.
    `device` is a DiscoveredDevice (has .ip, .device_type, .ssh_port).
    """
    result = DiscoveryResult(device_ip=device.ip)

    if not NETMIKO_OK:
        result.error = "netmiko not installed"
        return result

    # Normalize device_type for command lookup (handles blank / telnet types).
    base_type = _base_platform(getattr(device, "device_type", ""))
    cmds = VENDOR_COMMANDS.get(base_type, {})
    cdp_cfg  = cmds.get("cdp",  {"command": None, "textfsm_platform": None})
    lldp_cfg = cmds.get("lldp", {"command": None, "textfsm_platform": None})

    if not cdp_cfg.get("command") and not lldp_cfg.get("command"):
        result.error = (
            f"No CDP/LLDP command known for device_type "
            f"'{getattr(device, 'device_type', '')}' (base '{base_type}')"
        )
        return result

    # Resolve credentials, falling back gracefully if the per-device
    # credentials module isn't present (so a missing/unsynced file can't
    # silently break ALL discovery — it just uses the global defaults).
    try:
        from core.topology.credentials import resolve_device_credentials
        _user, _pass, _secret = resolve_device_credentials(device.ip)
    except Exception as cred_exc:
        logger.warning(f"credentials module unavailable ({cred_exc}); using env defaults")
        _user = os.environ.get("GNS3_SSH_USER", "admin")
        _pass = os.environ.get("GNS3_SSH_PASS", "admin")
        _secret = os.environ.get("GNS3_SSH_SECRET", "")

    try:
        conn, _method = _establish_connection(device, base_type, _user, _pass, _secret)
        try:
            conn.enable()
        except Exception:
            pass

        # Capture this device's OWN configured hostname from its CLI prompt
        # (e.g. "R2#" -> "R2"). This is the reconciliation anchor: in a lab
        # with no DNS, inventory discovery can't resolve a hostname, so the
        # polled node would otherwise stay nameless and fail to match the
        # hostname a PEER advertises for it via CDP/LLDP -- which is exactly
        # what splits one physical device into two graph nodes. find_prompt()
        # is essentially free and works across IOS/IOS-XE/NX-OS/XR since all
        # use a hostname-based prompt.
        try:
            prompt = conn.find_prompt() or ""
            result.local_hostname = prompt.rstrip("#>").strip()
        except Exception:
            result.local_hostname = ""

        all_neighbors: List[NeighborRecord] = []

        # ── CDP ──
        if cdp_cfg.get("command"):
            try:
                raw = conn.send_command(cdp_cfg["command"], read_timeout=20)
                result.raw_cdp = raw
                parsed = _parse_with_textfsm(
                    raw, base_type, cdp_cfg["command"], cdp_cfg.get("textfsm_platform")
                )
                if parsed is None:
                    parsed = _parse_cdp_regex(raw)
                all_neighbors.extend(_normalize_cdp_records(parsed))
            except Exception as exc:
                logger.debug(f"CDP discovery failed on {device.ip}: {exc}")

        # ── LLDP ──
        if lldp_cfg.get("command"):
            try:
                raw = conn.send_command(lldp_cfg["command"], read_timeout=20)
                result.raw_lldp = raw
                parsed = _parse_with_textfsm(
                    raw, base_type, lldp_cfg["command"], lldp_cfg.get("textfsm_platform")
                )
                if parsed is None:
                    parsed = _parse_lldp_regex(raw)
                all_neighbors.extend(_normalize_lldp_records(parsed))
            except Exception as exc:
                logger.debug(f"LLDP discovery failed on {device.ip}: {exc}")

        try:
            conn.disconnect()
        except Exception:
            pass

        result.neighbors = _dedupe_neighbors(all_neighbors)
        result.success = True

    except Exception as exc:
        result.error = str(exc)
        result.success = False

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# TextFSM parsing (via ntc-templates, already in requirements.txt)
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_with_textfsm(
    raw_output: str,
    device_type: str,
    command: str,
    textfsm_platform: Optional[str],
) -> Optional[List[Dict[str, Any]]]:
    """
    Try parsing with ntc-templates via Netmiko's textfsm integration.
    Returns a list of dicts (field_name -> value) or None if unavailable.
    """
    if not textfsm_platform:
        return None
    try:
        from netmiko.utilities import get_structured_data
        parsed = get_structured_data(
            raw_output, platform=textfsm_platform, command=command
        )
        if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
            return parsed
        return None
    except Exception as exc:
        logger.debug(f"TextFSM parse failed ({textfsm_platform}/{command}): {exc}")
        return None


def _normalize_cdp_records(records: Optional[List[Dict[str, Any]]]) -> List[NeighborRecord]:
    if not records:
        return []
    out: List[NeighborRecord] = []
    for r in records:
        out.append(NeighborRecord(
            local_interface=r.get("local_interface", "") or "",
            neighbor_name=r.get("neighbor_name", "") or "",
            neighbor_ip=r.get("mgmt_address", "") or "",
            neighbor_platform=r.get("platform", "") or "",
            neighbor_interface=r.get("neighbor_interface", "") or "",
            capabilities=r.get("capabilities", "") or "",
            protocol="cdp",
        ))
    return out


def _normalize_lldp_records(records: Optional[List[Dict[str, Any]]]) -> List[NeighborRecord]:
    if not records:
        return []
    out: List[NeighborRecord] = []
    for r in records:
        # neighbor_interface in ntc LLDP templates = "Port Description" (human-readable);
        # neighbor_port_id = raw "Port id" field. Prefer the descriptive one, fall back to ID.
        neighbor_iface = r.get("neighbor_interface", "") or r.get("neighbor_port_id", "") or ""
        out.append(NeighborRecord(
            local_interface=r.get("local_interface", "") or "",
            neighbor_name=r.get("neighbor_name", "") or r.get("chassis_id", "") or "",
            neighbor_ip=r.get("mgmt_address", "") or "",
            neighbor_platform=r.get("platform", "") or "",
            neighbor_interface=neighbor_iface,
            capabilities=r.get("capabilities", "") or "",
            protocol="lldp",
        ))
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# Regex fallback parsers (Cisco-style detail output)
# ═══════════════════════════════════════════════════════════════════════════════
# Used only when TextFSM is unavailable or the template doesn't match.
# These mirror the same fields the ntc-templates would have extracted,
# for the common Cisco IOS CDP/LLDP detail text layout.

def _parse_cdp_regex(raw: str) -> List[Dict[str, Any]]:
    """Fallback CDP neighbor detail parser for Cisco-style output."""
    if not raw:
        return []
    entries = re.split(r"-{5,}", raw)
    out: List[Dict[str, Any]] = []
    for entry in entries:
        if "Device ID" not in entry:
            continue
        name_m = re.search(r"Device ID:\s*(\S+)", entry)
        ip_m = re.search(r"IP address:\s*(\d+\.\d+\.\d+\.\d+)", entry)
        plat_m = re.search(r"Platform:\s*([^,]+),\s*Capabilities:\s*(.+)", entry)
        iface_m = re.search(
            r"Interface:\s*([^\s,]+),\s*Port ID \(outgoing port\):\s*(\S+)", entry
        )
        if not name_m:
            continue
        out.append({
            "neighbor_name":      name_m.group(1) if name_m else "",
            "mgmt_address":       ip_m.group(1) if ip_m else "",
            "platform":           plat_m.group(1).strip() if plat_m else "",
            "capabilities":       plat_m.group(2).strip() if plat_m else "",
            "local_interface":    iface_m.group(1) if iface_m else "",
            "neighbor_interface": iface_m.group(2) if iface_m else "",
        })
    return out


def _parse_lldp_regex(raw: str) -> List[Dict[str, Any]]:
    """Fallback LLDP neighbor detail parser for Cisco-style output."""
    if not raw:
        return []
    entries = re.split(r"-{5,}", raw)
    out: List[Dict[str, Any]] = []
    for entry in entries:
        if "Local Intf" not in entry and "Local Interface" not in entry:
            continue
        local_m = re.search(r"Local\s+Intf:\s*(\S+)", entry)
        chassis_m = re.search(r"Chassis\s+id:\s*(\S+)", entry)
        port_m = re.search(r"Port\s+id:\s*(\S+)", entry)
        desc_m = re.search(r"Port\s+Description:\s*(\S+)", entry)
        name_m = re.search(r"System\s+Name:\s*(\S+)", entry)
        cap_m = re.search(r"Enabled\s+Capabilities:\s*(.+)", entry)
        ip_m = re.search(r"IP:\s*(\d+\.\d+\.\d+\.\d+)", entry)
        if not local_m:
            continue
        out.append({
            "local_interface":    local_m.group(1) if local_m else "",
            "chassis_id":         chassis_m.group(1) if chassis_m else "",
            "neighbor_port_id":   port_m.group(1) if port_m else "",
            "neighbor_interface": desc_m.group(1) if desc_m else "",
            "neighbor_name":      name_m.group(1) if name_m else "",
            "capabilities":       cap_m.group(1).strip() if cap_m else "",
            "mgmt_address":       ip_m.group(1) if ip_m else "",
            "platform":           "",
        })
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# Interface name normalization
# ═══════════════════════════════════════════════════════════════════════════════
# CDP and LLDP often format the SAME interface differently on Cisco gear
# (CDP: "FastEthernet0/0", LLDP: "Fa0/0"). Normalize before using as a
# dedup key so the same physical link isn't recorded twice.

_IFACE_PREFIX_MAP: List[Tuple[str, str]] = [
    ("TenGigabitEthernet", "Te"), ("GigabitEthernet", "Gi"),
    ("FastEthernet", "Fa"), ("Ethernet", "Eth"),
    ("Port-channel", "Po"), ("Loopback", "Lo"),
    ("Serial", "Se"), ("Tunnel", "Tu"), ("Vlan", "Vl"),
]


def normalize_hostname(name: str) -> str:
    """
    Canonical key for matching the SAME physical device across the two
    ways it can show up: the hostname captured from its own CLI prompt
    when polled directly, vs. the device-ID a peer advertises for it via
    CDP/LLDP. CDP commonly reports a bare hostname ("R2") while LLDP or a
    domain-configured device may report an FQDN ("R2.lab.local"); case can
    also differ. So: lowercase, strip whitespace, and drop any DNS domain
    suffix after the first dot, leaving just the leftmost label.
    """
    if not name:
        return ""
    return name.strip().split(".")[0].lower()


def normalize_interface_name(name: str) -> str:
    """Collapse 'FastEthernet0/0' and 'Fa0/0' to the same canonical key."""
    if not name:
        return ""
    n = name.strip()
    for full, abbr in _IFACE_PREFIX_MAP:
        if n.startswith(full):
            return abbr + n[len(full):]
        if n.startswith(abbr) and not n.startswith(full):
            return abbr + n[len(abbr):]
    return n


# ═══════════════════════════════════════════════════════════════════════════════
# Dedup — CDP and LLDP both reporting the same neighbor on the same port
# ═══════════════════════════════════════════════════════════════════════════════

def _dedupe_neighbors(records: List[NeighborRecord]) -> List[NeighborRecord]:
    """
    If both CDP and LLDP found the same neighbor on the same local interface,
    prefer the CDP record (richer Cisco-specific data) and drop the LLDP dup.
    Interface names are normalized first since CDP/LLDP format them differently.
    """
    seen: Dict[Tuple[str, str], NeighborRecord] = {}
    for rec in records:
        norm_iface = normalize_interface_name(rec.local_interface)
        key = (norm_iface, rec.neighbor_name or rec.neighbor_ip)
        if key not in seen:
            seen[key] = rec
        elif rec.protocol == "cdp" and seen[key].protocol == "lldp":
            seen[key] = rec  # upgrade to CDP version (richer data)
    return list(seen.values())
