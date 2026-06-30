"""
NRIE · Location · Enterprise Hierarchy Builder
==============================================
Builds the full Region > Country > State > City > Campus > Site > Building >
Floor chain by REUSING the NRIE foundation service (RegisterEnterpriseEntity).
Idempotent-ish: reuses an existing node with the same level+name+parent when
present. Returns the created chain and the leaf (floor) to host subnets.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..contracts.commands import RegisterEnterpriseEntity


@dataclass
class HierarchyChain:
    ids: Dict[str, str] = field(default_factory=dict)     # level -> entity id
    names: Dict[str, str] = field(default_factory=dict)   # level -> name
    leaf_id: str = ""                                     # floor (subnet parent)
    site_id: str = ""

    def ordered(self) -> List[Dict[str, str]]:
        order = ["region", "country", "state", "city", "campus", "site", "building", "floor"]
        return [{"level": lv, "name": self.names[lv], "id": self.ids[lv]}
                for lv in order if lv in self.ids]


class HierarchyBuilder:
    def __init__(self, service):
        self._svc = service

    def _existing(self, level: str, name: str, parent_id: Optional[str]) -> Optional[str]:
        for n in self._svc.enterprise_hierarchy():
            if n.level == level and n.name == name and (n.parent_id or None) == (parent_id or None):
                return n.id
        return None

    def _node(self, level: str, name: str, parent_id: Optional[str], owner: str = "") -> str:
        return self._existing(level, name, parent_id) or self._svc.register_enterprise_entity(
            RegisterEnterpriseEntity(level=level, name=name, parent_id=parent_id, owner=owner))

    def build(self, *, location, site_name: str, org_name: str = "Acme Corp",
              owner: str = "netops") -> HierarchyChain:
        chain = HierarchyChain()
        parent = None
        # optional org root for context
        org = self._node("organization", org_name, None, owner)
        chain.ids["organization"] = org; chain.names["organization"] = org_name
        parent = org

        steps = [("region", location.region or "APAC"),
                 ("country", location.country or "Unknown"),
                 ("state", location.state or location.city or "—"),
                 ("city", location.city or site_name),
                 ("campus", f"{location.city or site_name} Campus"),
                 ("site", site_name),
                 ("building", f"{site_name} - Bldg A"),
                 ("floor", f"{site_name} - Floor 1")]
        for level, name in steps:
            nid = self._node(level, name, parent, owner)
            chain.ids[level] = nid; chain.names[level] = name
            parent = nid
            if level == "site":
                chain.site_id = nid
        chain.leaf_id = chain.ids["floor"]
        return chain
