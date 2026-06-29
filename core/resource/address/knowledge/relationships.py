"""
NRIE · Knowledge · Relationships
================================
Defines DEPENDENCY relationship kinds between resources, expressed using the
DOMAIN-NEUTRAL relationship vocabulary in ontology.py so they are reusable across
future Resource Domains. Read-only knowledge; resolution against live data is
performed by the EXISTING Knowledge Graph, not here.
"""
from __future__ import annotations
from typing import Dict, List

from .ontology import RELATIONSHIP_TYPES, is_known_relationship

# dependency-kind key -> (relationship_type, description)
DEPENDENCY_KINDS: Dict[str, Dict[str, str]] = {
    "requires_gateway": {"relationship": "depends_on", "desc": "a subnet depends on a reachable gateway"},
    "requires_vrf": {"relationship": "protected_by", "desc": "a vlan/subnet is isolated by its vrf"},
    "requires_dhcp": {"relationship": "uses", "desc": "an access subnet may use a dhcp pool"},
    "requires_dns": {"relationship": "uses", "desc": "a service may use a dns zone"},
    "summarized_by": {"relationship": "belongs_to", "desc": "a subnet belongs to a parent pool"},
    "carved_from": {"relationship": "allocated_from", "desc": "a subnet is allocated from a pool"},
    "owned_by_business": {"relationship": "owned_by", "desc": "a resource is owned by a business owner"},
    "operated_by": {"relationship": "managed_by", "desc": "a resource is managed by an operator/vrf"},
}

# resource_type -> dependency kinds it may declare (Address domain view)
RESOURCE_DEPENDENCIES: Dict[str, List[str]] = {
    "subnet": ["requires_gateway", "requires_vrf", "requires_dhcp", "requires_dns",
               "summarized_by", "carved_from", "owned_by_business"],
    "vlan": ["requires_vrf"],
    "dhcp_pool": ["requires_dns"],
    "address_pool": ["owned_by_business", "operated_by"],
}

# sanity: every dependency kind maps to a known, reusable relationship type
assert all(is_known_relationship(v["relationship"]) for v in DEPENDENCY_KINDS.values())


def relationship_of(dependency_kind: str) -> str:
    return DEPENDENCY_KINDS.get(dependency_kind, {}).get("relationship", "")
