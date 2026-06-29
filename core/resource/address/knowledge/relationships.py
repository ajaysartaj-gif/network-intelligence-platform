"""
NRIE · Knowledge · Relationships
================================
Defines DEPENDENCY relationship kinds between resources (read-only knowledge).
These describe how resources depend on one another; resolution against live data
is performed elsewhere (reusing the platform Knowledge Graph), not here.
"""
from __future__ import annotations
from typing import Dict, List

DEPENDENCY_KINDS: Dict[str, str] = {
    "requires_gateway": "a subnet depends on a reachable gateway",
    "requires_vrf": "a vlan depends on its vrf binding",
    "requires_dhcp": "an access subnet may depend on a dhcp pool",
    "requires_dns": "a service subnet may depend on a dns zone",
    "summarized_by": "a subnet may be aggregated by a parent pool",
}

# resource_type -> dependency kinds it may declare
RESOURCE_DEPENDENCIES: Dict[str, List[str]] = {
    "subnet": ["requires_gateway", "requires_vrf", "requires_dhcp", "requires_dns", "summarized_by"],
    "vlan": ["requires_vrf"],
    "dhcp_pool": ["requires_dns"],
}
