"""
NRIE · Cognition · Relationship Engine
======================================
Discovers candidate relationships for a resource using the reusable ontology
(PR-001.1) and the ResourceContextBundle. It REPORTS relationships; it does not
mutate the platform Knowledge Graph (that is the Dependency layer's job, which
reuses the real graph). No allocation/planning.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from ..context.models import ResourceContextBundle
from ..knowledge import ontology, relationships


def discover(bundle: ResourceContextBundle) -> List[Dict[str, str]]:
    rtype = bundle.resource.resource_type
    edges: List[Tuple[str, str, str]] = ontology.relations_for(rtype)
    out: List[Dict[str, str]] = []
    for subj, rel, obj in edges:
        direction = "outgoing" if subj == rtype else "incoming"
        out.append({"subject": subj, "relationship": rel, "object": obj,
                    "direction": direction})
    return out


def dependency_kinds(bundle: ResourceContextBundle) -> List[Dict[str, str]]:
    rtype = bundle.resource.resource_type
    kinds = relationships.RESOURCE_DEPENDENCIES.get(rtype, [])
    return [{"kind": k, "relationship": relationships.relationship_of(k)} for k in kinds]
