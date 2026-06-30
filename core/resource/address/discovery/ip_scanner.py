"""
NRIE · Discovery · IP Scanner
=============================
Scans a subnet for ACTIVE IPs by REUSING the platform's DeviceDiscoveryEngine
(ICMP ping + discovery pipeline). It does not re-implement scanning; it triggers
the engine and harvests hosts that fall inside the target subnet, plus anything
the platform already discovered (e.g. GNS3 routers). Injectable for tests.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass
class ScannedIP:
    ip: str
    active: bool = True
    hostname: str = ""
    vendor: str = ""
    mac: str = ""
    open_ports: List[int] = field(default_factory=list)
    rtt_ms: float = 0.0
    source: str = "ping"


class IPScanner:
    def __init__(self, engine: Optional[Any] = None):
        self._engine = engine or self._default_engine()

    @staticmethod
    def _default_engine():
        try:
            from core.device_discovery import get_discovery_engine
            return get_discovery_engine()
        except Exception:
            return None

    def scan(self, subnet_cidr: str, *, trigger: bool = True,
             max_hosts: int = 256) -> List[ScannedIP]:
        net = ipaddress.ip_network(subnet_cidr, strict=False)
        if trigger and self._engine is not None:
            try:
                prefix = ".".join(str(net.network_address).split(".")[:3])
                self._engine.scan_subnet(subnet_prefix=prefix)
            except Exception:
                pass
        found: List[ScannedIP] = []
        if self._engine is not None:
            try:
                for d in (self._engine.get_all() or [])[:max_hosts]:
                    try:
                        if ipaddress.ip_address(d.ip) in net:
                            found.append(ScannedIP(
                                ip=d.ip, active=True, hostname=getattr(d, "hostname", ""),
                                vendor=getattr(d, "vendor", ""), mac=getattr(d, "mac", ""),
                                open_ports=list(getattr(d, "open_ports", []) or []),
                                rtt_ms=getattr(d, "ping_rtt_ms", 0.0),
                                source=getattr(d, "source", "ping")))
                    except ValueError:
                        continue
            except Exception:
                pass
        return found
