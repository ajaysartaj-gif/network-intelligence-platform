"""
NRIE · API · Autonomy API (AI-native intent → site)
===================================================
Facade for the autonomous, AI-native IP Intelligence flow. Reuses the foundation
service + Site Designer. NRIE plans/allocates and inventories — it never deploys.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .service import get_nrie_service
from ..autonomy.site_designer import AutonomousSiteResult, SiteDesigner
from ..discovery.ip_scanner import IPScanner, ScannedIP
from ..discovery.ip_inventory import IPInventory


class NRIEAutonomyAPI:
    def __init__(self):
        self._svc = get_nrie_service()
        self._designer = SiteDesigner(self._svc)
        self._scanner = IPScanner()
        self._inventory = IPInventory()

    def design_site(self, intent_text: str, *, address_space: str = "10.40.0.0/16",
                    scan: bool = False,
                    scanned_override: Optional[List[ScannedIP]] = None) -> AutonomousSiteResult:
        return self._designer.design(intent_text, address_space=address_space,
                                     scan=scan, scanned_override=scanned_override)

    def scan_subnet(self, subnet_cidr: str, *, site: str = "") -> List[Dict[str, Any]]:
        out = []
        for sc in self._scanner.scan(subnet_cidr):
            out.append(self._inventory.record_scanned(sc, subnet=subnet_cidr, site=site).as_dict())
        return out

    def ip_inventory(self, subnet_cidr: str) -> List[Dict[str, Any]]:
        return [d.as_dict() for d in self._inventory.by_subnet(subnet_cidr)]


_AUTONOMY_API: Optional[NRIEAutonomyAPI] = None


def get_autonomy_api() -> NRIEAutonomyAPI:
    global _AUTONOMY_API
    if _AUTONOMY_API is None:
        _AUTONOMY_API = NRIEAutonomyAPI()
    return _AUTONOMY_API
