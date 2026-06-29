"""
NRIE · Knowledge · Glossary
===========================
Canonical term definitions for the address/resource domain. Documentation-grade
knowledge consumed by UI and future explainability — no logic.
"""
from __future__ import annotations
from typing import Dict

GLOSSARY: Dict[str, str] = {
    "address_space": "A top-level routable space (e.g. an enterprise supernet).",
    "address_pool": "A hierarchical block carved from an address space for a purpose.",
    "subnet": "A routable network with a mask, gateway and purpose.",
    "vlan": "A layer-2 broadcast domain mapped to a subnet.",
    "vrf": "A routing/forwarding instance providing isolation.",
    "loopback": "A stable /32 (or /128) device identity address.",
    "transit_network": "A network interconnecting routing domains.",
    "overlay": "A virtual network layered over transit (e.g. VXLAN/SD-WAN).",
    "business_context": "Business meaning attached to a resource or hierarchy node.",
    "criticality": "Business importance class used to weigh change risk.",
}


def define(term: str) -> str:
    return GLOSSARY.get(term, "")
