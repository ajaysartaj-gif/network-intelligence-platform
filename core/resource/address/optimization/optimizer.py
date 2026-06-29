"""
NRIE · Optimization · Optimization Intelligence (Layer 13)
==========================================================
Continuous optimization producing RECOMMENDATIONS ONLY (no automatic changes):
address-space optimization, pool balancing, fragmentation detection, route
summarization opportunities, capacity optimization, reclamation, allocation
efficiency, growth optimization. Consumes the bundle; reuses fragmentation +
summarization analysers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from ..context.models import ResourceContextBundle
from ..events.domain_events import (
    OPTIMIZATION_SUGGESTED, IntelligenceEvent, get_event_publisher,
)
from . import fragmentation, summarization


@dataclass
class OptimizationSuggestion:
    kind: str
    severity: str
    detail: str
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__


class Optimizer:
    def __init__(self, publisher=None):
        self._pub = publisher or get_event_publisher()

    def analyze(self, *, bundle: ResourceContextBundle, address_space: str,
                allocated_cidrs: List[str],
                utilization_pct: float = 0.0) -> List[OptimizationSuggestion]:
        out: List[OptimizationSuggestion] = []

        frag = fragmentation.analyze(address_space, allocated_cidrs)
        if frag.notes:
            out.append(OptimizationSuggestion(
                "fragmentation", "medium", "; ".join(frag.notes), frag.__dict__))

        props = summarization.propose(allocated_cidrs)
        for p in props:
            out.append(OptimizationSuggestion(
                "route_summarization", "low",
                f"Aggregate {len(p.members)} subnets into {p.aggregate} "
                f"({p.routes_saved} routes saved).", p.__dict__))

        # capacity / reclamation / growth heuristics (recommendations only)
        if utilization_pct and utilization_pct < 25:
            out.append(OptimizationSuggestion(
                "reclamation", "low",
                f"Utilization {utilization_pct:.0f}% is low — consider shrinking or reclaiming.",
                {"utilization_pct": utilization_pct}))
        if utilization_pct and utilization_pct > 85:
            out.append(OptimizationSuggestion(
                "capacity", "high",
                f"Utilization {utilization_pct:.0f}% is high — plan expansion.",
                {"utilization_pct": utilization_pct}))
        if bundle.business.criticality in ("high", "critical"):
            out.append(OptimizationSuggestion(
                "growth", "low",
                "Business-critical: keep growth headroom reserved for this space.",
                {"criticality": bundle.business.criticality}))

        if out:
            self._pub.publish(IntelligenceEvent(
                type=OPTIMIZATION_SUGGESTED, resource_id=bundle.resource.resource_id,
                payload={"suggestions": len(out)}))
        return out
