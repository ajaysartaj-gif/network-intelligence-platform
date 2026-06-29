"""
NRIE · Recommendation · Recommendation Engine
=============================================
Produces RANKED alternatives (never a single answer when several valid options
exist). Each carries confidence, risk, cost, complexity, growth suitability,
business impact and an explanation hook. Recommendations only — no execution.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from ..allocation.allocator import AddressDemand, IntelligentAllocator
from ..context.models import ResourceContextBundle
from ..events.domain_events import (
    RECOMMENDATION_GENERATED, IntelligenceEvent, get_event_publisher,
)


@dataclass
class Recommendation:
    label: str
    confidence: float
    risk: str
    cost: str
    complexity: str
    growth_suitability: str
    business_impact: str
    explanation: str
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__


class RecommendationEngine:
    def __init__(self, allocator=None, publisher=None):
        self._alloc = allocator or IntelligentAllocator()
        self._pub = publisher or get_event_publisher()

    def rank(self, *, bundle: ResourceContextBundle, plan, demands: List[AddressDemand],
             address_space: str = "10.40.0.0/16") -> List[Recommendation]:
        recs: List[Recommendation] = []
        crit = bundle.business.criticality in ("high", "critical")
        # Option A: the computed best-fit plan (growth-aware)
        recs.append(Recommendation(
            label="Growth-aware best-fit (recommended)",
            confidence=0.86 if plan.success else 0.4,
            risk="low" if plan.success else "high", cost="medium",
            complexity="low", growth_suitability="high",
            business_impact="aligned to declared growth + criticality headroom",
            explanation="Best-fit packing with growth/criticality headroom minimises "
                        "fragmentation while leaving room to expand.",
            detail={"subnets": len(plan.subnets), "headroom_pct": plan.growth_headroom_pct}))
        # Option B: compact (minimal headroom) — cheaper, less future-proof
        recs.append(Recommendation(
            label="Compact / minimal headroom",
            confidence=0.62, risk="medium" if crit else "low", cost="low",
            complexity="low", growth_suitability="low",
            business_impact="conserves space; may require earlier expansion",
            explanation="Sizes strictly to current demand. Lower cost now, higher "
                        "chance of re-addressing later.",
            detail={"note": "tighter prefixes, no growth shadow"}))
        # Option C: segmented per-zone VRF isolation — stronger security posture
        recs.append(Recommendation(
            label="Segmented per-zone isolation",
            confidence=0.71, risk="low", cost="high", complexity="medium",
            growth_suitability="high",
            business_impact="strong isolation for OT/secure zones; more VRFs to manage",
            explanation="Dedicated VRF/zone per purpose improves blast-radius control "
                        "for critical/secure services.",
            detail={"vrfs": plan.vrfs}))
        recs.sort(key=lambda r: r.confidence, reverse=True)
        self._pub.publish(IntelligenceEvent(
            type=RECOMMENDATION_GENERATED, resource_id=bundle.resource.resource_id,
            payload={"count": len(recs), "top": recs[0].label}))
        return recs
