"""
NRIE · Autonomy · Site Designer (AI-native orchestrator)
========================================================
The end-to-end autonomous flow:

  "deploy a 20 users site in Mumbai"
      → parse intent (AI + fallback)
      → resolve location (Mumbai → Maharashtra/India/APAC)
      → build Region>Country>State>City>Campus>Site>Building>Floor
      → derive demands from the site profile
      → plan + allocate subnets/VLANs/VRFs (reused PR-003 PlanningService)
      → record subnets under the Floor (Subnet level)
      → (optional) scan the subnet for active IPs + AI descriptions (IP level)

Everything is REUSED: foundation service, Context Builder, planning, allocation,
device discovery and the Groq client. NRIE plans/allocates only — no config/deploy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..contracts.commands import AttachBusinessContext, RecordResource
from ..context.models import ResourceContextBundle
from ..intent.intent_parser import SiteIntent, derive_demands, parse as parse_intent
from ..location.location_map import LocationChain, resolve as resolve_location
from ..location.hierarchy_builder import HierarchyBuilder, HierarchyChain
from ..planning.planning_service import PlanningOutcome, PlanningService
from ..discovery.ip_scanner import IPScanner, ScannedIP
from ..discovery.ip_inventory import IPDetail, IPInventory

_HIGH_CRIT = {"manufacturing", "datacenter"}


@dataclass
class AutonomousSiteResult:
    intent: SiteIntent
    location: LocationChain
    hierarchy: HierarchyChain
    plan: Optional[PlanningOutcome] = None
    subnet_resource_ids: List[str] = field(default_factory=list)
    scanned_ips: List[IPDetail] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def summary(self) -> Dict[str, Any]:
        return {
            "intent": self.intent.__dict__,
            "location": self.location.__dict__,
            "hierarchy": self.hierarchy.ordered(),
            "subnets": [s.__dict__ for s in (self.plan.plan.subnets if self.plan else [])],
            "active_ips": [d.as_dict() for d in self.scanned_ips],
            "notes": self.notes,
        }


class SiteDesigner:
    def __init__(self, service, planning: Optional[PlanningService] = None,
                 scanner: Optional[IPScanner] = None, inventory: Optional[IPInventory] = None):
        self._svc = service
        self._planning = planning or PlanningService()
        self._scanner = scanner or IPScanner()
        self._inventory = inventory or IPInventory()

    def design(self, text: str, *, address_space: str = "10.40.0.0/16",
               scan: bool = False,
               scanned_override: Optional[List[ScannedIP]] = None) -> AutonomousSiteResult:
        intent = parse_intent(text)
        location = resolve_location(intent.location or "")
        site_name = f"{intent.site_type.title()}-{location.city or 'Site'}"
        chain = HierarchyBuilder(self._svc).build(location=location, site_name=site_name)
        result = AutonomousSiteResult(intent=intent, location=location, hierarchy=chain)
        result.notes.append(f"intent parsed via {intent.source}; location via {location.source}")

        criticality = "high" if intent.site_type in _HIGH_CRIT else "normal"
        # business context on the site (why the resources exist)
        try:
            self._svc.attach_business_context(AttachBusinessContext(
                attached_to=chain.site_id, site_type=intent.site_type,
                business_function=intent.site_type, users=intent.users,
                criticality=criticality))
        except Exception as e:
            result.notes.append(f"business context skipped: {e}")

        # representative resource under the Floor → build the context bundle
        rep_id = self._svc.record_resource(RecordResource(
            resource_type="subnet", name=f"{site_name}-plan", purpose="user_lan",
            hierarchy_ref=chain.leaf_id, status="planned"))
        bundle: Optional[ResourceContextBundle] = self._svc.build_context_bundle(rep_id)
        if bundle is None:
            result.notes.append("could not assemble context bundle; aborting plan")
            return result

        demands = derive_demands(intent)
        outcome = self._planning.plan(bundle=bundle, intent=intent.raw,
                                      demands=demands, address_space=address_space)
        result.plan = outcome

        # record each planned subnet under the Floor (Subnet level of the hierarchy)
        for s in outcome.plan.subnets:
            rid = self._svc.record_resource(RecordResource(
                resource_type="subnet", name=f"{s.purpose}-{s.cidr}", purpose=s.purpose,
                hierarchy_ref=chain.leaf_id, status="planned",
                metadata={"cidr": s.cidr, "gateway": s.gateway, "vlan": s.vlan, "vrf": s.vrf}))
            result.subnet_resource_ids.append(rid)

        # optional: scan the first planned subnet → active IPs + AI descriptions
        if (scan or scanned_override is not None) and outcome.plan.subnets:
            first = outcome.plan.subnets[0].cidr
            scanned = scanned_override if scanned_override is not None \
                else self._scanner.scan(first)
            for sc in scanned:
                result.scanned_ips.append(self._inventory.record_scanned(
                    sc, subnet=first, site=site_name, hierarchy_ref=chain.leaf_id))
            result.notes.append(f"scanned {first}: {len(result.scanned_ips)} active IP(s)")
        return result
