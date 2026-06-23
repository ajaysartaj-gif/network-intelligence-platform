"""
core/topology/topology_models.py
=================================
Data model for site network topology.

TopologyNode  — one device (router/switch/AP/firewall) in the diagram
TopologyLink  — one physical connection between two devices, with the
                exact local/remote port (interface) on each side
TopologyGraph — the full site topology: nodes + links + metadata
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Tuple


class DeviceRole(str, Enum):
    ROUTER       = "router"
    SWITCH       = "switch"
    ACCESS_POINT = "access_point"
    FIREWALL     = "firewall"
    PHONE        = "phone"
    UNKNOWN      = "unknown"

    @property
    def icon(self) -> str:
        return {
            "router":       "🌐",
            "switch":       "🔀",
            "access_point": "📶",
            "firewall":     "🛡️",
            "phone":        "☎️",
            "unknown":      "❓",
        }[self.value]

    @property
    def color(self) -> str:
        return {
            "router":       "#3b82f6",
            "switch":       "#22c55e",
            "access_point": "#a855f7",
            "firewall":     "#ef4444",
            "phone":        "#f59e0b",
            "unknown":      "#6b7280",
        }[self.value]

    @property
    def layer(self) -> int:
        """Vertical layer for hierarchical layout — lower number = higher up."""
        return {
            "firewall":     0,
            "router":       1,
            "switch":       2,
            "access_point": 3,
            "phone":        3,
            "unknown":      2,
        }[self.value]


@dataclass
class TopologyNode:
    ip: str
    hostname: str = ""
    vendor: str = ""
    device_type: str = ""
    role: DeviceRole = DeviceRole.UNKNOWN
    platform_string: str = ""     # raw platform string from CDP/LLDP, e.g. "cisco WS-C3560-24TS"
    site_name: str = ""
    city: str = ""
    country: str = ""
    region: str = ""
    x: float = 0.0
    y: float = 0.0
    discovered_only: bool = False  # True if found via CDP/LLDP but not in our approved inventory
    interface_subnets: Dict[str, str] = field(default_factory=dict)
    # normalized interface name -> subnet CIDR, e.g. {"Fa0/0": "192.168.96.0/24"}.
    # Populated by L3 discovery (show ip route connected), separate from the
    # CDP/LLDP physical discovery above -- empty for devices/vendors where L3
    # discovery hasn't run or isn't supported yet, which is a valid state,
    # not an error (renders as "L3 status unknown" rather than "mismatched").

    def label(self) -> str:
        return self.hostname or self.ip


@dataclass
class TopologyLink:
    device_a_ip: str
    device_a_port: str
    device_b_ip: str
    device_b_port: str
    protocol: str = "cdp"     # "cdp" | "lldp"
    discovered_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def edge_key(self) -> Tuple[str, str]:
        """Order-independent key so A→B and B→A reports dedupe to one edge."""
        return tuple(sorted([self.device_a_ip, self.device_b_ip]))


@dataclass
class TopologyGraph:
    site_name: str = ""
    city: str = ""
    country: str = ""
    region: str = ""
    nodes: Dict[str, TopologyNode] = field(default_factory=dict)   # ip -> node
    links: List[TopologyLink] = field(default_factory=list)
    built_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    devices_polled: int = 0
    devices_failed: List[str] = field(default_factory=list)
    unapproved_neighbors: List[str] = field(default_factory=list)  # CDP/LLDP neighbors not in approved inventory (approved_only mode)

    def add_node(self, node: TopologyNode) -> None:
        self.nodes[node.ip] = node

    def add_link(self, link: TopologyLink) -> None:
        """Add a link, de-duplicating CDP+LLDP reports of the same physical link."""
        for existing in self.links:
            if existing.edge_key() == link.edge_key():
                same_ports = (
                    {existing.device_a_port, existing.device_b_port}
                    == {link.device_a_port, link.device_b_port}
                )
                if same_ports:
                    return  # already recorded — skip duplicate
        self.links.append(link)

    def node_count(self) -> int:
        return len(self.nodes)

    def link_count(self) -> int:
        return len(self.links)

    def neighbors_of(self, ip: str) -> List[TopologyLink]:
        return [l for l in self.links if ip in (l.device_a_ip, l.device_b_ip)]

    def to_dict(self) -> dict:
        return {
            "site_name": self.site_name,
            "city": self.city,
            "country": self.country,
            "region": self.region,
            "nodes": {ip: {**n.__dict__, "role": n.role.value} for ip, n in self.nodes.items()},
            "links": [l.__dict__ for l in self.links],
            "built_at": self.built_at,
            "devices_polled": self.devices_polled,
            "devices_failed": self.devices_failed,
            "unapproved_neighbors": self.unapproved_neighbors,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TopologyGraph":
        g = cls(
            site_name=data.get("site_name", ""),
            city=data.get("city", ""),
            country=data.get("country", ""),
            region=data.get("region", ""),
            built_at=data.get("built_at", ""),
            devices_polled=data.get("devices_polled", 0),
            devices_failed=data.get("devices_failed", []),
            unapproved_neighbors=data.get("unapproved_neighbors", []),
        )
        for ip, n in data.get("nodes", {}).items():
            n = dict(n)
            n["role"] = DeviceRole(n.get("role", "unknown"))
            g.nodes[ip] = TopologyNode(**n)
        for l in data.get("links", []):
            g.links.append(TopologyLink(**l))
        return g

    def to_ai_context(self) -> str:
        """Serialize the graph as plain text for feeding to AI chat."""
        lines = [f"SITE: {self.site_name} ({self.city}, {self.country}, {self.region})"]
        lines.append(f"Built at: {self.built_at}")
        lines.append("")
        lines.append("DEVICES:")
        for n in self.nodes.values():
            lines.append(
                f"  - {n.label()} ({n.ip}) — role={n.role.value}, "
                f"vendor={n.vendor or 'unknown'}, platform={n.platform_string or n.device_type}"
            )
        lines.append("")
        lines.append("LINKS:")
        for l in self.links:
            a_name = self.nodes[l.device_a_ip].label() if l.device_a_ip in self.nodes else l.device_a_ip
            b_name = self.nodes[l.device_b_ip].label() if l.device_b_ip in self.nodes else l.device_b_ip
            lines.append(
                f"  - {a_name} [{l.device_a_port}] ←→ [{l.device_b_port}] {b_name}  (via {l.protocol})"
            )
        if self.devices_failed:
            lines.append("")
            lines.append(f"DEVICES THAT FAILED DISCOVERY: {', '.join(self.devices_failed)}")
        return "\n".join(lines)
