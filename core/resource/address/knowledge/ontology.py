"""
NRIE · Knowledge · Ontology
===========================
Defines resource RELATIONSHIPS. PR-001.1 adds a richer, DOMAIN-NEUTRAL
relationship vocabulary that is reusable across future Resource Domains
(Device/Cloud/Connectivity/Identity) — not just Address. Declarative knowledge
only; no behaviour, no allocation.
"""
from __future__ import annotations
from typing import List, Tuple

# ── reusable, domain-neutral relationship vocabulary (PR-001.1) ──────────────
# These relationship *types* are intended to be shared by every Resource Domain.
RELATIONSHIP_TYPES: Tuple[str, ...] = (
    "belongs_to",
    "contains",
    "supports",
    "depends_on",
    "connected_to",
    "protected_by",
    "owned_by",
    "uses",
    "allocated_from",
    "managed_by",
)


def is_known_relationship(rel: str) -> bool:
    return rel in RELATIONSHIP_TYPES


# (subject_type, relation, object_type) — Address-domain ontology.
# Existing edges are preserved for backward compatibility; new edges use the
# richer vocabulary above.
RESOURCE_ONTOLOGY: List[Tuple[str, str, str]] = [
    # ── preserved from PR-001 ──
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
    # ── PR-001.1: richer, reusable relationships ──
    ("subnet", "belongs_to", "address_pool"),
    ("subnet", "allocated_from", "address_pool"),
    ("address_pool", "owned_by", "business_owner"),
    ("subnet", "supports", "business_service"),
    ("subnet", "depends_on", "gateway"),
    ("vlan", "connected_to", "transit_network"),
    ("subnet", "protected_by", "vrf"),
    ("address_pool", "managed_by", "vrf"),
    ("dhcp_pool", "uses", "dns_zone"),
]


def relations_for(resource_type: str) -> List[Tuple[str, str, str]]:
    return [t for t in RESOURCE_ONTOLOGY if t[0] == resource_type or t[2] == resource_type]


def edges_by_relationship(relationship: str) -> List[Tuple[str, str, str]]:
    return [t for t in RESOURCE_ONTOLOGY if t[1] == relationship]
