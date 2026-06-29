"""
NRIE · Dependency · Dependency Intelligence (Layer 11)
======================================================
Discovers and classifies resource dependencies (upstream/downstream/business/
routing/security/cloud) from the ResourceContextBundle and the reusable ontology,
registering them into the platform Knowledge Graph (via NRIEDependencyGraph).
Enables future impact analysis. No allocation/planning.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..context.models import ResourceContextBundle
from ..events.domain_events import (
    DEPENDENCY_DISCOVERED, IntelligenceEvent, get_event_publisher,
)
from ..knowledge import ontology
from .dependency_graph import NRIEDependencyGraph

# map ontology relationship → dependency facet
_ROUTING = {"connected_to", "allocated_from", "belongs_to", "contains"}
_SECURITY = {"protected_by", "managed_by"}
_BUSINESS = {"owned_by", "supports"}


@dataclass
class DependencyAnalysis:
    resource_id: str
    upstream: List[str] = field(default_factory=list)
    downstream: List[str] = field(default_factory=list)
    business: List[str] = field(default_factory=list)
    routing: List[str] = field(default_factory=list)
    security: List[str] = field(default_factory=list)
    cloud: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, List[str]]:
        return {"upstream": self.upstream, "downstream": self.downstream,
                "business": self.business, "routing": self.routing,
                "security": self.security, "cloud": self.cloud}


class DependencyEngine:
    def __init__(self, graph: Optional[NRIEDependencyGraph] = None, publisher=None):
        self._g = graph or NRIEDependencyGraph()
        self._pub = publisher or get_event_publisher()

    def discover(self, bundle: ResourceContextBundle) -> DependencyAnalysis:
        rtype = bundle.resource.resource_type
        rid = bundle.resource.resource_id or rtype
        analysis = DependencyAnalysis(resource_id=rid)

        # register this resource node in the platform graph (reuse)
        self._g.register_node(rid, rtype, {"purpose": bundle.resource.purpose})

        for subj, rel, obj in ontology.relations_for(rtype):
            facet = self._facet(rel)
            counterpart = obj if subj == rtype else subj
            if subj == rtype:
                analysis.downstream.append(f"{rel}:{obj}")
            else:
                analysis.upstream.append(f"{rel}:{subj}")
            getattr(analysis, facet).append(counterpart) if facet in (
                "business", "routing", "security") else None
            # register edge in the platform graph
            self._g.register_node(counterpart, counterpart)
            self._g.register_edge(rid if subj == rtype else counterpart,
                                  obj if subj == rtype else rid, rel)

        # cloud dependencies: only if business context references cloud (none here → empty)
        if "cloud" in (bundle.business.business_service or "").lower():
            analysis.cloud.append(bundle.business.business_service)

        self._pub.publish(IntelligenceEvent(
            type=DEPENDENCY_DISCOVERED, resource_id=rid,
            payload={"downstream": len(analysis.downstream),
                     "upstream": len(analysis.upstream)}))
        return analysis

    @staticmethod
    def _facet(rel: str) -> str:
        if rel in _BUSINESS:
            return "business"
        if rel in _SECURITY:
            return "security"
        if rel in _ROUTING:
            return "routing"
        return "routing"
