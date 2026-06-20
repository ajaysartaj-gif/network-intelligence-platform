"""
core/discovery/network_ranges.py
=================================
RFC 1918 private address space definitions + CIDR utilities for
network discovery scanning.

Design notes:
  - iter_hosts() is a GENERATOR, never a materialized list — a /8 has
    16.7 million addresses; building that as a Python list would burn
    well over a gigabyte of RAM for no reason. Every consumer of this
    module must iterate lazily.
  - get_local_subnets() uses psutil (cross-platform, no text-parsing
    of `ifconfig`/`ip addr` output needed) to find which subnets the
    CURRENT machine is actually connected to — this is what lets the
    tool auto-discover devices without the operator needing to know
    or type the exact lab subnet.
"""
from __future__ import annotations

import ipaddress
import logging
import socket
from dataclasses import dataclass
from typing import Iterator, List, Optional, Tuple

logger = logging.getLogger("NetBrain.Discovery.Ranges")

try:
    import psutil
    PSUTIL_OK = True
except ImportError:
    PSUTIL_OK = False


# ═══════════════════════════════════════════════════════════════════════════════
# RFC 1918 private address space
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class RangePreset:
    label: str
    cidr: str
    host_count: int          # usable hosts (excludes network/broadcast)
    recommended: bool = True # False = "use with caution" (e.g. full /8)


RFC1918_RANGES: List[RangePreset] = [
    RangePreset("Class C Private — 192.168.0.0/16", "192.168.0.0/16", 65_534, recommended=True),
    RangePreset("Class B Private — 172.16.0.0/12",  "172.16.0.0/12", 1_048_574, recommended=True),
    RangePreset("Class A Private — 10.0.0.0/8",     "10.0.0.0/8", 16_777_214, recommended=False),
]


# ═══════════════════════════════════════════════════════════════════════════════
# CIDR helpers
# ═══════════════════════════════════════════════════════════════════════════════

def parse_cidr(cidr: str) -> Optional[ipaddress.IPv4Network]:
    """Validate and parse a CIDR string. Returns None if invalid."""
    try:
        return ipaddress.ip_network(cidr.strip(), strict=False)
    except (ValueError, AttributeError):
        return None


def host_count(cidr: str) -> int:
    """Number of usable host addresses in a CIDR block."""
    net = parse_cidr(cidr)
    if net is None:
        return 0
    return max(net.num_addresses - 2, 0) if net.num_addresses > 2 else net.num_addresses


def iter_hosts(cidr: str, exclude_cidrs: Optional[List[str]] = None) -> Iterator[str]:
    """
    Lazily yield every usable host IP in a CIDR block as a string.
    NEVER materializes the full range into memory — safe for /8 blocks.
    """
    net = parse_cidr(cidr)
    if net is None:
        return
    exclude_nets = []
    for ex in (exclude_cidrs or []):
        ex_net = parse_cidr(ex)
        if ex_net:
            exclude_nets.append(ex_net)

    for addr in net.hosts():
        if any(addr in ex for ex in exclude_nets):
            continue
        yield str(addr)


def estimate_scan_seconds(
    addresses: int,
    concurrency: int = 300,
    timeout_sec: float = 0.4,
) -> float:
    """
    Realistic time estimate for scanning N addresses with bounded
    concurrency. Assumes most addresses DON'T respond (worst case —
    they each consume close to the full timeout), since that's the
    dominant cost for sparse private ranges.
    """
    if addresses <= 0 or concurrency <= 0:
        return 0.0
    batches = addresses / concurrency
    return batches * timeout_sec


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"~{seconds:.0f} sec"
    if seconds < 600:
        return f"~{seconds / 60:.1f} min"
    if seconds < 3600:
        return f"~{seconds / 60:.0f} min"
    return f"~{seconds / 3600:.1f} hr"


# ═══════════════════════════════════════════════════════════════════════════════
# Local subnet auto-detection
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class LocalSubnet:
    interface: str
    ip: str
    cidr: str
    host_count: int


def get_local_subnets() -> List[LocalSubnet]:
    """
    Detect the subnets THIS machine is actually connected to, across
    all network interfaces (Wi-Fi, Ethernet, VM bridges, tunnels, etc).
    This is what lets discovery work without the operator needing to
    know/type their exact lab subnet — every interface's subnet,
    including GNS3 VM bridge adapters, gets included automatically.
    """
    if not PSUTIL_OK:
        logger.info("psutil not installed — local subnet auto-detection unavailable")
        return []

    out: List[LocalSubnet] = []
    try:
        addrs = psutil.net_if_addrs()
    except Exception as exc:
        logger.warning(f"psutil.net_if_addrs() failed: {exc}")
        return []

    for iface, addr_list in addrs.items():
        for a in addr_list:
            if a.family != socket.AF_INET:
                continue
            ip = a.address
            netmask = a.netmask
            if not ip or not netmask:
                continue
            # Skip loopback and link-local — not useful discovery targets
            try:
                ip_obj = ipaddress.ip_address(ip)
                if ip_obj.is_loopback or ip_obj.is_link_local:
                    continue
                network = ipaddress.ip_network(f"{ip}/{netmask}", strict=False)
            except (ValueError, TypeError):
                continue

            out.append(LocalSubnet(
                interface=iface,
                ip=ip,
                cidr=str(network),
                host_count=host_count(str(network)),
            ))

    return out
