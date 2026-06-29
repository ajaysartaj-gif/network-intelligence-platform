"""
NRIE · Knowledge · Taxonomy
===========================
Defines resource CLASSIFICATION — categories and purpose groupings. Declarative.
"""
from __future__ import annotations
from typing import Dict, List

RESOURCE_CATEGORIES: Dict[str, List[str]] = {
    "addressing": ["address_space", "address_pool", "subnet", "loopback"],
    "segmentation": ["vlan", "vrf", "overlay"],
    "services": ["dhcp_pool", "dns_zone", "gateway"],
    "connectivity": ["transit_network", "tunnel"],
}

PURPOSE_TAXONOMY: Dict[str, List[str]] = {
    "access": ["user_lan", "voice", "guest", "iot"],
    "secure": ["ot", "cctv", "firewall_ha", "mgmt"],
    "transport": ["wan_p2p", "transit", "loopback"],
}

SITE_TYPES: List[str] = ["headquarters", "campus", "branch", "manufacturing",
                         "datacenter", "retail", "remote"]


def category_of(resource_type: str) -> str:
    for cat, members in RESOURCE_CATEGORIES.items():
        if resource_type in members:
            return cat
    return "uncategorized"
