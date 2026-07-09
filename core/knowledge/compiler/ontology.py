"""
core/knowledge/compiler/ontology.py
======================================
Ontology Engine — operationalizes docs/nkc_architecture_blueprint.md Part 5
(previously markdown-only) as real code: a shallow, extensible taxonomy
classifying every ObjectType/finding-kind string into a family. Not a
formal OWL/RDF ontology — nothing downstream needs formal inference, only
consistent categorization for filtering/reporting, the same way
core.knowledge.enterprise.knowledge_layer.SourceType already classifies
document sources.
"""
from __future__ import annotations

from typing import Dict, Set

# object-type/finding-kind string -> family. Additive: a new object type
# gets one new entry here, never a restructuring of existing families.
FAMILY_OF_TYPE: Dict[str, str] = {
    "device": "Infrastructure",
    "inventory": "Infrastructure",
    "topology": "Infrastructure",
    "interface": "Object",
    "vrf": "Object",
    "vlan": "Object",
    "route": "Object",
    "neighbor": "Object",
    "tunnel": "Object",
    "flow": "Object",
    "protocol": "Protocol",
    "configuration": "Configuration",
    "timer": "Configuration",
    "policy": "Security",
    "acl": "Security",
    "security_rule": "Security",
    "qos": "Feature",
    "nat": "Feature",
    "cloud_resource": "Cloud",
    "service": "Application",
    "application": "Application",
    "telemetry": "OperationalState",
    "state": "OperationalState",
    "alarm": "Event",
    "event": "Event",
}

_DEFAULT_FAMILY = "Uncategorized"


def family_of(object_type: str) -> str:
    """The ontology family for a given ObjectType value / finding kind.
    Unknown types resolve to 'Uncategorized' rather than raising — the
    ontology is meant to classify what's known, not gate what's allowed
    (NormalizedObject.type accepts arbitrary strings by design)."""
    return FAMILY_OF_TYPE.get((object_type or "").lower(), _DEFAULT_FAMILY)


def families() -> Set[str]:
    return set(FAMILY_OF_TYPE.values()) | {_DEFAULT_FAMILY}
