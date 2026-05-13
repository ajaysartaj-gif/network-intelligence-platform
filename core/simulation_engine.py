"""
Network simulation engine for realistic enterprise topology and state simulation.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import random
from datetime import datetime


@dataclass
class SimulatedDevice:
    """Enterprise network device simulation."""
    hostname: str
    vendor: str
    model: str
    device_type: str  # router, switch, firewall, wan_device, data_center_device
    site: str
    role: str
    os_version: str
    status: str = "healthy"
    cpu: float = random.uniform(10, 40)
    memory: float = random.uniform(15, 45)
    uptime_days: int = field(default_factory=lambda: random.randint(30, 365))
    interfaces: List[Dict[str, Any]] = field(default_factory=list)
    bgp_asn: Optional[int] = None
    bgp_sessions: List[Dict[str, Any]] = field(default_factory=list)
    ospf_neighbors: List[str] = field(default_factory=list)
    vlans: List[int] = field(default_factory=list)
    vrfs: List[str] = field(default_factory=list)


@dataclass
class SimulatedInterface:
    """Network interface simulation."""
    name: str
    device: str
    status: str = "up"
    type: str = "eth"  # eth, gt, port-channel
    bandwidth_mbps: float = 1000
    mtu: int = 1500
    utilization_pct: float = field(default_factory=lambda: random.uniform(5, 40))
    errors: int = 0
    drops: int = 0
    latency_ms: float = field(default_factory=lambda: random.uniform(1, 15))
    packet_loss_pct: float = field(default_factory=lambda: random.uniform(0, 0.5))


@dataclass
class SimulatedLink:
    """Network link between devices."""
    source: str
    source_interface: str
    destination: str
    dest_interface: str
    link_type: str  # direct, bgp, ospf, mpls
    status: str = "up"
    bandwidth_mbps: float = 10000
    max_latency_ms: float = field(default_factory=lambda: random.uniform(5, 50))
    current_latency_ms: float = field(default_factory=lambda: random.uniform(5, 30))


class SimulationEngine:
    """
    Realistic enterprise network simulation engine.
    Simulates topology, protocols, failures, and interdependencies.
    """

    def __init__(self):
        """Initialize simulation engine."""
        self.devices: Dict[str, SimulatedDevice] = {}
        self.interfaces: Dict[str, SimulatedInterface] = {}
        self.links: List[SimulatedLink] = []
        self.time_step: int = 0
        self.anomalies: List[Dict[str, Any]] = []
        self._initialize_enterprise_topology()

    # ═══════════════════════════════════════════════════════════════
    # TOPOLOGY INITIALIZATION
    # ═══════════════════════════════════════════════════════════════

    def _initialize_enterprise_topology(self) -> None:
        """Initialize realistic enterprise multi-site topology."""
        sites = ["delhi", "mumbai", "bangalore", "us-east", "us-west", "eu-west"]
        
        # Data Center Devices (2 per site)
        for site in sites:
            for i in range(2):
                hostname = f"dc{i+1}-{site}"
                device = SimulatedDevice(
                    hostname=hostname,
                    vendor="Cisco",
                    model="ASR 9000",
                    device_type="data_center_device",
                    site=site,
                    role="core_router",
                    os_version="IOS-XR 7.9",
                    bgp_asn=64500 + hash(site) % 100,
                )
                self.devices[hostname] = device
                self._create_interfaces(hostname, 16)

        # Regional Routers (1 per site)
        for site in sites:
            hostname = f"rtr-{site}"
            device = SimulatedDevice(
                hostname=hostname,
                vendor="Juniper",
                model="MX960",
                device_type="router",
                site=site,
                role="regional_router",
                os_version="Junos 20.4",
                bgp_asn=65000 + hash(site) % 100,
            )
            self.devices[hostname] = device
            self._create_interfaces(hostname, 12)

        # Access Switches (2 per site)
        for site in sites:
            for i in range(2):
                hostname = f"sw{i+1}-{site}"
                device = SimulatedDevice(
                    hostname=hostname,
                    vendor="Arista",
                    model="DCS 7060",
                    device_type="switch",
                    site=site,
                    role="access_switch",
                    os_version="EOS 4.25",
                )
                self.devices[hostname] = device
                self._create_interfaces(hostname, 48)

        # Firewalls (1 per site)
        for site in sites:
            hostname = f"fw-{site}"
            device = SimulatedDevice(
                hostname=hostname,
                vendor="Palo Alto",
                model="PA-5420",
                device_type="firewall",
                site=site,
                role="security_gateway",
                os_version="PAN-OS 10.2",
            )
            self.devices[hostname] = device
            self._create_interfaces(hostname, 4)

        # WAN Devices
        for site in sites[:3]:  # Main WAN hubs
            hostname = f"wan-{site}"
            device = SimulatedDevice(
                hostname=hostname,
                vendor="Cisco",
                model="ISR 4451",
                device_type="wan_device",
                site=site,
                role="wan_hub",
                os_version="IOS 15.9",
            )
            self.devices[hostname] = device
            self._create_interfaces(hostname, 6)

        # Create inter-site links (full mesh of core devices)
        self._create_intersite_links()

    def _create_interfaces(self, hostname: str, count: int) -> None:
        """Create interfaces for a device."""
        device = self.devices[hostname]
        for i in range(count):
            iface = SimulatedInterface(
                name=f"Eth{i}/0" if device.vendor == "Arista" else f"Gi{i}/0",
                device=hostname,
                status="up" if random.random() > 0.05 else "down",
                bandwidth_mbps=10000 if i < 4 else 1000,
            )
            iface_key = f"{hostname}:{iface.name}"
            self.interfaces[iface_key] = iface
            device.interfaces.append({"name": iface.name, "status": iface.status})

    def _create_intersite_links(self) -> None:
        """Create inter-site links."""
        # Connect data center routers in a mesh
        dc_routers = [h for h in self.devices.keys() if h.startswith("dc")]
        for i, src in enumerate(dc_routers):
            for dest in dc_routers[i+1:]:
                src_site = self.devices[src].site
                dest_site = self.devices[dest].site
                if src_site != dest_site:
                    link = SimulatedLink(
                        source=src,
                        source_interface=f"Gi0/0",
                        destination=dest,
                        dest_interface=f"Gi0/0",
                        link_type="bgp",
                        bandwidth_mbps=100000,
                    )
                    self.links.append(link)

    # ═══════════════════════════════════════════════════════════════
    # STATE UPDATES
    # ═══════════════════════════════════════════════════════════════

    def step(self) -> Dict[str, Any]:
        """Simulate one time step and return changes."""
        self.time_step += 1
        changes = {
            "time_step": self.time_step,
            "updates": [],
            "anomalies": [],
        }

        # Update device metrics
        for hostname, device in self.devices.items():
            old_state = {
                "cpu": device.cpu,
                "memory": device.memory,
                "status": device.status,
            }

            # Simulate metric drift
            device.cpu = max(5, min(98, device.cpu + random.uniform(-5, 8)))
            device.memory = max(10, min(95, device.memory + random.uniform(-3, 6)))

            # Simulate occasional interface flaps
            if random.random() < 0.02:
                iface_idx = random.randint(0, len(device.interfaces) - 1)
                iface = device.interfaces[iface_idx]
                iface["status"] = "down" if iface["status"] == "up" else "up"
                changes["updates"].append({
                    "device": hostname,
                    "type": "interface_flap",
                    "interface": iface["name"],
                })

            # Simulate BGP flaps occasionally
            if device.bgp_sessions and random.random() < 0.01:
                session_idx = random.randint(0, len(device.bgp_sessions) - 1)
                session = device.bgp_sessions[session_idx]
                session["state"] = "Established" if session["state"] == "Idle" else "Idle"
                changes["updates"].append({
                    "device": hostname,
                    "type": "bgp_state_change",
                    "session": session.get("peer_ip"),
                    "state": session["state"],
                })

        # Simulate anomalies
        if random.random() < 0.03:  # 3% chance of anomaly per step
            anomaly = self._simulate_anomaly()
            if anomaly:
                changes["anomalies"].append(anomaly)
                self.anomalies.append(anomaly)

        return changes

    def _simulate_anomaly(self) -> Optional[Dict[str, Any]]:
        """Simulate a network anomaly."""
        anomaly_types = [
            "cpu_spike",
            "memory_exhaustion",
            "interface_flap",
            "packet_loss",
            "latency_spike",
            "bgp_instability",
            "wan_degradation",
        ]
        
        anomaly_type = random.choice(anomaly_types)
        device = random.choice(list(self.devices.values()))
        
        if anomaly_type == "cpu_spike":
            device.cpu = min(98, device.cpu + random.uniform(20, 40))
            return {
                "type": "cpu_spike",
                "device": device.hostname,
                "value": device.cpu,
                "severity": "high" if device.cpu > 85 else "medium",
            }
        
        elif anomaly_type == "memory_exhaustion":
            device.memory = min(98, device.memory + random.uniform(15, 35))
            return {
                "type": "memory_exhaustion",
                "device": device.hostname,
                "value": device.memory,
                "severity": "high" if device.memory > 85 else "medium",
            }
        
        elif anomaly_type == "interface_flap":
            if device.interfaces:
                iface = random.choice(device.interfaces)
                iface["status"] = "down"
                return {
                    "type": "interface_flap",
                    "device": device.hostname,
                    "interface": iface["name"],
                    "severity": "high",
                }
        
        elif anomaly_type == "packet_loss":
            if device.interfaces:
                iface = random.choice(device.interfaces)
                loss = random.uniform(1, 10)
                return {
                    "type": "packet_loss",
                    "device": device.hostname,
                    "interface": iface["name"],
                    "loss_pct": loss,
                    "severity": "high" if loss > 5 else "medium",
                }
        
        elif anomaly_type == "latency_spike":
            latency = random.uniform(50, 200)
            return {
                "type": "latency_spike",
                "device": device.hostname,
                "latency_ms": latency,
                "severity": "medium" if latency < 100 else "high",
            }
        
        elif anomaly_type == "bgp_instability":
            if device.bgp_sessions:
                session = random.choice(device.bgp_sessions)
                session["state"] = "Idle"
                return {
                    "type": "bgp_instability",
                    "device": device.hostname,
                    "peer": session.get("peer_ip"),
                    "severity": "high",
                }
        
        elif anomaly_type == "wan_degradation":
            wan_link = next(
                (l for l in self.links if "wan" in l.source.lower() or "wan" in l.destination.lower()),
                None,
            )
            if wan_link:
                wan_link.current_latency_ms = min(wan_link.max_latency_ms, wan_link.current_latency_ms + 100)
                return {
                    "type": "wan_degradation",
                    "link": f"{wan_link.source}→{wan_link.destination}",
                    "latency_ms": wan_link.current_latency_ms,
                    "severity": "high",
                }
        
        return None

    # ═══════════════════════════════════════════════════════════════
    # TOPOLOGY QUERIES
    # ═══════════════════════════════════════════════════════════════

    def get_topology_summary(self) -> Dict[str, Any]:
        """Get topology summary."""
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
        """Count devices by attribute."""
        counts: Dict[str, int] = {}
        for device in self.devices.values():
            key = getattr(device, attr)
            counts[key] = counts.get(key, 0) + 1
        return counts

    def get_device(self, hostname: str) -> Optional[SimulatedDevice]:
        """Get device by hostname."""
        return self.devices.get(hostname)

    def get_devices_by_site(self, site: str) -> List[SimulatedDevice]:
        """Get all devices at a site."""
        return [d for d in self.devices.values() if d.site == site]

    def get_devices_by_type(self, device_type: str) -> List[SimulatedDevice]:
        """Get devices by type."""
        return [d for d in self.devices.values() if d.device_type == device_type]

    def get_critical_devices(self) -> List[SimulatedDevice]:
        """Get devices with critical metrics."""
        return [
            d for d in self.devices.values()
            if d.cpu >= 90 or d.memory >= 90 or d.status == "down"
        ]

    def export_state(self) -> Dict[str, Any]:
        """Export complete simulation state."""
        return {
            "time_step": self.time_step,
            "devices": {h: {
                "cpu": d.cpu,
                "memory": d.memory,
                "status": d.status,
                "interfaces": d.interfaces,
            } for h, d in self.devices.items()},
            "topology_summary": self.get_topology_summary(),
            "anomalies": self.anomalies[-10:],  # Last 10 anomalies
        }
