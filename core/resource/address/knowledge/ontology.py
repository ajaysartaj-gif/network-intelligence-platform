"""
NRIE · Knowledge · Ontology
===========================
Defines resource RELATIONSHIPS — the allowed structural edges between resource
types. Declarative knowledge only; no behaviour, no allocation.
"""
from __future__ import annotations
from typing import Dict, List, Tuple

# (subject_type, relation, object_type)
RESOURCE_ONTOLOGY: List[Tuple[str, str, str]] = [
    ("address_space", "contains", "address_pool"),
    ("address_pool", "contains", "address_pool"),
    ("address_pool", "contains", "subnet"),
    ("subnet", "assigned_to", "vlan"),
    ("vlan", "member_of", "vrf"),
    ("subnet", "has", "gateway"),
    ("subnet", "serves", "dhcp_pool"),
    ("dns_zone", "resolves_for", "subnet"),
    ("loopback", "identifies", "vrf"),
    ("transit_network", "connects", "vrf"),
    ("tunnel", "carries", "overlay"),
    ("overlay", "spans", "transit_network"),
]


def relations_for(resource_type: str) -> List[Tuple[str, str, str]]:
    return [t for t in RESOURCE_ONTOLOGY if t[0] == resource_type or t[2] == resource_type]
