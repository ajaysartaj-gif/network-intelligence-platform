"""
NRIE · Planning · Resource Planner (Layer: planning)
====================================================
Turns business intent + the ResourceContextBundle into an Enterprise Resource
Plan (pools, subnets, VLANs, VRFs, DHCP pools, DNS zones, growth headroom,
hierarchy, business mapping). It computes addressing via the Intelligent
Allocator. It generates NO configuration and performs NO deployment.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..allocation.allocator import AddressDemand, Allocation, IntelligentAllocator
from ..context.models import ResourceContextBundle
from ..events.domain_events import (
    RESOURCE_PLANNED, IntelligenceEvent, get_event_publisher,
)

# access purposes get DHCP; service purposes get DNS (knowledge, not config)
_ACCESS = {"user_lan", "voice", "guest", "iot"}
_SERVICE = {"mgmt", "ot", "cctv"}


@dataclass
class PlannedSubnet:
    purpose: str
    cidr: str
    gateway: str
    vlan: int
    vrf: str
    usable_hosts: int
    rationale: str


@dataclass
class ResourcePlan:
    intent: str = ""
    address_space: str = ""
    pools: List[str] = field(default_factory=list)
    subnets: List[PlannedSubnet] = field(default_factory=list)
    vlans: List[int] = field(default_factory=list)
    vrfs: List[str] = field(default_factory=list)
    dhcp_pools: List[str] = field(default_factory=list)
    dns_zones: List[str] = field(default_factory=list)
    growth_headroom_pct: float = 0.0
    hierarchy: Dict[str, Any] = field(default_factory=dict)
    business_mapping: Dict[str, Any] = field(default_factory=dict)
    success: bool = True
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent, "address_space": self.address_space,
            "pools": self.pools, "vlans": self.vlans, "vrfs": self.vrfs,
            "dhcp_pools": self.dhcp_pools, "dns_zones": self.dns_zones,
            "growth_headroom_pct": self.growth_headroom_pct,
            "subnets": [s.__dict__ for s in self.subnets],
            "hierarchy": self.hierarchy, "business_mapping": self.business_mapping,
            "success": self.success, "notes": self.notes,
        }


class ResourcePlanner:
    def __init__(self, allocator: Optional[IntelligentAllocator] = None, publisher=None):
        self._alloc = allocator or IntelligentAllocator()
        self._pub = publisher or get_event_publisher()

    def plan(self, *, bundle: ResourceContextBundle, intent: str,
             demands: List[AddressDemand], address_space: str = "10.40.0.0/16",
             vlan_base: int = 100) -> ResourcePlan:
        plan = ResourcePlan(intent=intent, address_space=address_space)
        growth = bundle.business.growth_expectation
        plan.growth_headroom_pct = float(growth.get("expected_pct", 0)
                                         if isinstance(growth, dict) else 0) or 0.0
        taken: List[str] = []
        vlan_id = vlan_base
        for d in demands:
            vrf = d.vrf or self._vrf_for(d.purpose)
            vlan = d.vlan or vlan_id
            vlan_id += 10
            a: Allocation = self._alloc.allocate(
                bundle=bundle, demand=AddressDemand(d.purpose, d.host_count, vrf, vlan),
                pool_id=f"pool:{vrf}", pool_cidr=address_space, existing_cidrs=taken)
            if not a.success:
                plan.success = False
                plan.notes.append(f"{d.purpose}: {a.rationale}")
                continue
            taken.append(a.cidr)
            plan.subnets.append(PlannedSubnet(
                purpose=d.purpose, cidr=a.cidr, gateway=a.gateway, vlan=vlan, vrf=vrf,
                usable_hosts=a.usable_hosts, rationale=a.rationale))
            if vlan not in plan.vlans:
                plan.vlans.append(vlan)
            if vrf not in plan.vrfs:
                plan.vrfs.append(vrf)
                plan.pools.append(f"pool:{vrf}")
            if d.purpose in _ACCESS:
                plan.dhcp_pools.append(f"dhcp:{d.purpose}:{a.cidr}")
            if d.purpose in _SERVICE:
                plan.dns_zones.append(f"{d.purpose}.{(bundle.enterprise.name or 'corp').lower()}.local")
        plan.hierarchy = {"enterprise": bundle.enterprise.name,
                          "ancestors": bundle.enterprise.ancestors}
        plan.business_mapping = {"capability": bundle.business.business_capability,
                                 "service": bundle.business.business_service,
                                 "criticality": bundle.business.criticality}
        self._pub.publish(IntelligenceEvent(
            type=RESOURCE_PLANNED, resource_id=bundle.resource.resource_id,
            payload={"subnets": len(plan.subnets), "success": plan.success}))
        return plan

    @staticmethod
    def _vrf_for(purpose: str) -> str:
        return {"user_lan": "corp", "voice": "voice", "guest": "guest", "iot": "iot",
                "ot": "ot", "cctv": "physec", "mgmt": "mgmt"}.get(purpose, "corp")
