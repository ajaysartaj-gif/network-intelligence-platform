"""
NRIE · Discovery · IP Inventory (Subnet > IP leaf)
==================================================
Persists per-IP details with a human/AI description of what each IP is and where
it is engaged. REUSES the Memory Platform (MemoryStore) and the AI assistant
(reused Groq). This is the leaf of Region>…>Floor>Subnet>IP.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.intelligence.memory.store import MemoryStore
from ..ai.assistant import describe_ip


@dataclass
class IPDetail:
    ip: str
    subnet: str = ""
    status: str = "active"
    description: str = ""
    engaged_as: str = ""
    hostname: str = ""
    vendor: str = ""
    mac: str = ""
    open_ports: List[int] = field(default_factory=list)
    site: str = ""
    hierarchy_ref: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return self.__dict__


class _IPStore(MemoryStore):
    table = "nrie_ip_inventory"
    semantic = False
    columns = (("subnet", "TEXT"), ("ip", "TEXT"), ("status", "TEXT"))


class IPInventory:
    def __init__(self, store: Optional[_IPStore] = None):
        self._s = store or _IPStore()

    def record_scanned(self, scanned, *, subnet: str, site: str = "",
                       hierarchy_ref: str = "") -> IPDetail:
        role = _role_hint(scanned)
        desc = describe_ip(scanned.ip, hostname=scanned.hostname, vendor=scanned.vendor,
                           open_ports=scanned.open_ports, role_hint=role)
        d = IPDetail(ip=scanned.ip, subnet=subnet, status="active", description=desc,
                     engaged_as=role, hostname=scanned.hostname, vendor=scanned.vendor,
                     mac=scanned.mac, open_ports=list(scanned.open_ports), site=site,
                     hierarchy_ref=hierarchy_ref)
        self._persist(d)
        return d

    def _persist(self, d: IPDetail) -> None:
        self._s.learn(f"{d.subnet}|{d.ip}", d.description[:60],
                      extra={"record": d.as_dict()}, subnet=d.subnet, ip=d.ip, status=d.status)

    def by_subnet(self, subnet: str) -> List[IPDetail]:
        rows = self._s._be.query(f"SELECT * FROM {self._s.table} WHERE subnet=?", (subnet,))
        return [_to_detail(r) for r in rows]

    def all(self) -> List[IPDetail]:
        return [_to_detail(r) for r in self._s._be.query(f"SELECT * FROM {self._s.table}")]


def _role_hint(scanned) -> str:
    ports = set(scanned.open_ports or [])
    if {179} & ports:
        return "Router / BGP"
    if scanned.source == "gns3" or "ios" in (scanned.hostname or "").lower():
        return "Network device (GNS3/router)"
    if {554, 37777} & ports:
        return "CCTV / camera"
    if {80, 443} & ports:
        return "Web/app server"
    if {22, 23} & ports:
        return "Managed host"
    return "Active host"


def _to_detail(row: Dict[str, Any]) -> IPDetail:
    rec = json.loads(row.get("extra") or "{}").get("record", {})
    return IPDetail(**rec) if rec else IPDetail(ip=row.get("ip", ""), subnet=row.get("subnet", ""))
