"""
NRIE · Allocation · Intelligent Allocator (Layer: allocation)
============================================================
Selects pools and addresses intelligently — context-aware sizing (growth +
criticality headroom), best-fit placement (NOT first-available), conflict and
capacity checks, duplicate prevention. Works THROUGH the Pool aggregate and
references Business Context, standards, previous decisions, utilization and
growth. It computes addresses (real CIDR math) but generates NO configuration
and performs NO deployment.
"""
from __future__ import annotations

import ipaddress
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..context.models import ResourceContextBundle
from ..events.domain_events import (
    ALLOCATION_FAILED, RESOURCE_ALLOCATED, IntelligenceEvent, get_event_publisher,
)
from .conflict_detector import detect


@dataclass(frozen=True)
class AddressDemand:
    purpose: str
    host_count: int
    vrf: str = ""
    vlan: Optional[int] = None


@dataclass
class Allocation:
    purpose: str
    cidr: str = ""
    gateway: str = ""
    prefixlen: int = 0
    usable_hosts: int = 0
    vrf: str = ""
    vlan: Optional[int] = None
    rationale: str = ""
    conflicts: List[str] = field(default_factory=list)
    success: bool = True


class IntelligentAllocator:
    def __init__(self, publisher=None):
        self._pub = publisher or get_event_publisher()

    # ── sizing: never undersize; add growth + criticality headroom ───────────
    def size_prefix(self, host_count: int, bundle: ResourceContextBundle,
                    family: int = 4) -> int:
        growth = float(bundle.business.growth_expectation.get("expected_pct", 0)
                       if isinstance(bundle.business.growth_expectation, dict) else 0) or 0.0
        headroom = 1.0 + growth / 100.0
        if bundle.business.criticality in ("high", "critical"):
            headroom += 0.25                      # extra headroom for critical services
        needed = max(1, math.ceil(max(1, host_count) * headroom))
        bits = 32 if family == 4 else 128
        # +2 for network/broadcast on IPv4
        host_bits = max(1, math.ceil(math.log2(needed + (2 if family == 4 else 0))))
        return bits - host_bits

    # ── best-fit placement: pack tightly, do NOT take the first block ────────
    def _best_fit(self, pool_cidr: str, prefixlen: int,
                  taken: List[str]) -> Optional[ipaddress._BaseNetwork]:
        pool = ipaddress.ip_network(pool_cidr, strict=False)
        if prefixlen < pool.prefixlen:
            return None
        taken_nets = []
        for t in taken:
            try:
                taken_nets.append(ipaddress.ip_network(t, strict=False))
            except ValueError:
                continue
        candidates = [c for c in pool.subnets(new_prefix=prefixlen)
                      if not any(c.overlaps(tn) for tn in taken_nets)]
        if not candidates:
            return None
        if not taken_nets:
            return candidates[0]
        # best-fit = the free block closest to existing allocations (minimise
        # fragmentation) rather than the first available block.
        def proximity(c):
            return min(abs(int(c.network_address) - int(tn.network_address))
                       for tn in taken_nets)
        return min(candidates, key=proximity)

    def allocate(self, *, bundle: ResourceContextBundle, demand: AddressDemand,
                 pool_id: str, pool_cidr: str,
                 existing_cidrs: Optional[List[str]] = None,
                 family: int = 4) -> Allocation:
        existing = list(existing_cidrs or [])
        prefixlen = self.size_prefix(demand.host_count, bundle, family)
        chosen = self._best_fit(pool_cidr, prefixlen, existing)
        if chosen is None:
            self._pub.publish(IntelligenceEvent(
                type=ALLOCATION_FAILED, resource_id=bundle.resource.resource_id,
                payload={"purpose": demand.purpose, "reason": "no capacity"}))
            return Allocation(purpose=demand.purpose, success=False,
                              rationale="No capacity for required prefix in pool.",
                              prefixlen=prefixlen)
        conflicts = [f"{c.kind}:{c.existing}" for c in detect(str(chosen), existing)]
        if conflicts:
            self._pub.publish(IntelligenceEvent(
                type=ALLOCATION_FAILED, resource_id=bundle.resource.resource_id,
                payload={"purpose": demand.purpose, "conflicts": conflicts}))
            return Allocation(purpose=demand.purpose, success=False, cidr=str(chosen),
                              conflicts=conflicts, rationale="Conflict detected.")
        hosts = chosen.num_addresses - (2 if family == 4 and chosen.prefixlen < 31 else 0)
        gw = str(next(chosen.hosts())) if chosen.prefixlen < 31 else str(chosen.network_address)
        alloc = Allocation(
            purpose=demand.purpose, cidr=str(chosen), gateway=gw,
            prefixlen=chosen.prefixlen, usable_hosts=hosts, vrf=demand.vrf,
            vlan=demand.vlan, success=True,
            rationale=(f"Best-fit {chosen.prefixlen}-bit block for {demand.host_count} hosts "
                       f"+ growth/criticality headroom; packed to minimise fragmentation."))
        self._pub.publish(IntelligenceEvent(
            type=RESOURCE_ALLOCATED, resource_id=bundle.resource.resource_id,
            payload={"purpose": demand.purpose, "cidr": alloc.cidr}))
        return alloc
