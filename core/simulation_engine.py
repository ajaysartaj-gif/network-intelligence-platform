"""
Live-only network state container.

This module used to generate a fabricated multi-site enterprise topology
(fake devices, fake BGP/OSPF sessions, a scripted cascading-anomaly demo
workflow) for when no real GNS3/device connection was available. That
generation has been permanently removed — this tool only ever reports on
real GNS3-backed or real physical equipment, never invented data. The
class shape is kept (SimulationEngine.devices/.interfaces/.links stay
real, structurally-typed containers, just never populated by this
module) because core.orchestration_engine.OperationsOrchestrator and
core.telemetry_engine.TelemetryEngine still hold a reference to one and
read attributes off it; removing the class itself would require
refactoring both of those modules' many call sites for no behavioral
benefit, since every one of those reads already degrades cleanly to
"nothing" once these containers are permanently empty.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class SimulatedDevice:
    """Enterprise network device — retained as a type shape only; never
    instantiated by this module anymore."""
    hostname: str
    vendor: str
    model: str
    device_type: str  # router, switch, firewall, wan_device, data_center_device
    site: str
    role: str
    os_version: str
    status: str = "healthy"
    cpu: float = 0.0
    memory: float = 0.0
    uptime_days: int = 0
    interfaces: List[Dict[str, Any]] = field(default_factory=list)
    bgp_asn: Optional[int] = None
    bgp_sessions: List[Dict[str, Any]] = field(default_factory=list)
    ospf_neighbors: List[str] = field(default_factory=list)
    vlans: List[int] = field(default_factory=list)
    vrfs: List[str] = field(default_factory=list)


@dataclass
class SimulatedInterface:
    """Network interface — retained as a type shape only; never
    instantiated by this module anymore."""
    name: str
    device: str
    status: str = "up"
    type: str = "eth"  # eth, gt, port-channel
    bandwidth_mbps: float = 1000
    mtu: int = 1500
    utilization_pct: float = 0.0
    errors: int = 0
    drops: int = 0
    latency_ms: float = 0.0
    packet_loss_pct: float = 0.0


@dataclass
class SimulatedLink:
    """Network link between devices — retained as a type shape only; never
    instantiated by this module anymore."""
    source: str
    source_interface: str
    destination: str
    dest_interface: str
    link_type: str  # direct, bgp, ospf, mpls
    status: str = "up"
    bandwidth_mbps: float = 10000
    max_latency_ms: float = 0.0
    current_latency_ms: float = 0.0


class SimulationEngine:
    """
    Live-only network state container. Holds no data of its own — real
    device/topology state lives in core.state_manager.StateManager,
    populated from real GNS3/SSH discovery. This class exists only so
    OperationsOrchestrator/TelemetryEngine's existing structure (which
    reference .devices/.interfaces/.links/.get_topology_summary()/.step())
    keeps working without a larger refactor; every method here always
    reflects empty state.
    """

    def __init__(self):
        self.devices: Dict[str, SimulatedDevice] = {}
        self.interfaces: Dict[str, SimulatedInterface] = {}
        self.links: List[SimulatedLink] = []
        self.time_step: int = 0
        self.anomalies: List[Dict[str, Any]] = []

    # ═══════════════════════════════════════════════════════════════
    # STATE UPDATES
    # ═══════════════════════════════════════════════════════════════

    def step(self) -> Dict[str, Any]:
        """No-op: real network state is polled via real telemetry/discovery,
        never advanced by a synthetic clock."""
        self.time_step += 1
        return {"time_step": self.time_step, "updates": [], "anomalies": []}

    # ═══════════════════════════════════════════════════════════════
    # TOPOLOGY QUERIES (always reflect real, possibly-empty state)
    # ═══════════════════════════════════════════════════════════════

    def get_topology_summary(self) -> Dict[str, Any]:
        return {
            "total_devices": len(self.devices),
            "total_interfaces": len(self.interfaces),
            "total_links": len(self.links),
            "device_types": self._count_by_type("device_type"),
            "vendors": self._count_by_type("vendor"),
            "sites": self._count_by_type("site"),
            "healthy_devices": sum(1 for d in self.devices.values() if d.status == "healthy"),
        }

    def _count_by_type(self, attr: str) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for device in self.devices.values():
            key = getattr(device, attr)
            counts[key] = counts.get(key, 0) + 1
        return counts

    def get_device(self, hostname: str) -> Optional[SimulatedDevice]:
        return self.devices.get(hostname)

    def get_devices_by_site(self, site: str) -> List[SimulatedDevice]:
        return [d for d in self.devices.values() if d.site == site]

    def get_devices_by_type(self, device_type: str) -> List[SimulatedDevice]:
        return [d for d in self.devices.values() if d.device_type == device_type]

    def get_critical_devices(self) -> List[SimulatedDevice]:
        return [
            d for d in self.devices.values()
            if d.cpu >= 90 or d.memory >= 90 or d.status == "down"
        ]

    def export_state(self) -> Dict[str, Any]:
        return {
            "time_step": self.time_step,
            "devices": {h: {
                "cpu": d.cpu,
                "memory": d.memory,
                "status": d.status,
                "interfaces": d.interfaces,
            } for h, d in self.devices.items()},
            "topology_summary": self.get_topology_summary(),
            "anomalies": self.anomalies[-10:],
        }
