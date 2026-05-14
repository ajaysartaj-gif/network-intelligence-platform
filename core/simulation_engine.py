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
        self.workflow_stage: int = 0  # Track the cascading workflow stage
        self.workflow_active: bool = True  # Continuous workflow flag
        self.last_stage_change: int = 0  # Track when we last changed stages
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
        self._initialize_protocol_sessions()

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

    def _initialize_protocol_sessions(self) -> None:
        """Create initial BGP and OSPF state across the simulated network."""
        routers = [d for d in self.devices.values() if d.device_type in {"router", "data_center_device", "wan_device"}]
        for router in routers:
            self._create_bgp_sessions(router)

        for device in self.devices.values():
            if device.device_type in {"switch", "firewall", "data_center_device"}:
                self._create_ospf_neighbors(device)

    def _create_bgp_sessions(self, device: SimulatedDevice) -> None:
        """Create BGP sessions with remote peers."""
        peers = [d for d in self.devices.values() if d.bgp_asn and d.hostname != device.hostname]
        selected = random.sample(peers, min(2, len(peers)))
        for peer in selected:
            session = {
                "peer_ip": f"10.{abs(hash(device.hostname)) % 254}.{abs(hash(peer.hostname)) % 254}.{random.randint(1, 254)}",
                "peer_asn": peer.bgp_asn,
                "state": "Established" if random.random() > 0.2 else "Idle",
                "prefixes": random.randint(100, 1200),
            }
            device.bgp_sessions.append(session)

    def _create_ospf_neighbors(self, device: SimulatedDevice) -> None:
        """Create OSPF neighbors for devices."""
        neighbors = [d for d in self.devices.values() if d.site == device.site and d.hostname != device.hostname]
        selected = random.sample(neighbors, min(2, len(neighbors)))
        for neighbor in selected:
            if neighbor.hostname not in device.ospf_neighbors:
                device.ospf_neighbors.append(neighbor.hostname)

    # ═══════════════════════════════════════════════════════════════
    # STATE UPDATES
    # ═══════════════════════════════════════════════════════════════

    def step(self) -> Dict[str, Any]:
        """Simulate one time step with cascading packet loss workflow."""
        self.time_step += 1
        changes = {
            "time_step": self.time_step,
            "updates": [],
            "anomalies": [],
        }

        # Continuous cascading workflow: Packet Loss → WAN Latency → BGP Instability → Voice Degradation → Critical Incident
        if self.workflow_active:
            self._advance_cascading_workflow(changes)

        # Update device metrics with normal drift
        for hostname, device in self.devices.items():
            old_state = {
                "cpu": device.cpu,
                "memory": device.memory,
                "status": device.status,
            }

            # Simulate metric drift
            device.cpu = max(5, min(98, device.cpu + random.uniform(-5, 8)))
            device.memory = max(10, min(95, device.memory + random.uniform(-3, 6)))

            # Simulate occasional interface flaps (reduced frequency)
            if random.random() < 0.005:  # Reduced from 0.02
                iface_idx = random.randint(0, len(device.interfaces) - 1)
                iface = device.interfaces[iface_idx]
                iface["status"] = "down" if iface["status"] == "up" else "up"
                changes["updates"].append({
                    "device": hostname,
                    "type": "interface_flap",
                    "interface": iface["name"],
                })

            # Simulate BGP flaps occasionally (reduced frequency)
            if device.bgp_sessions and random.random() < 0.003:  # Reduced from 0.01
                session_idx = random.randint(0, len(device.bgp_sessions) - 1)
                session = device.bgp_sessions[session_idx]
                session["state"] = "Established" if session["state"] == "Idle" else "Idle"
                changes["updates"].append({
                    "device": hostname,
                    "type": "bgp_state_change",
                    "session": session.get("peer_ip"),
                    "state": session["state"],
                })

        return changes

    def _advance_cascading_workflow(self, changes: Dict[str, Any]) -> None:
        """Advance the cascading packet loss workflow."""
        stages_elapsed = self.time_step - self.last_stage_change

        # Stage 0: Normal operation (5-10 cycles)
        if self.workflow_stage == 0:
            if stages_elapsed > random.randint(5, 10):
                self.workflow_stage = 1
                self.last_stage_change = self.time_step
                self._inject_packet_loss_anomaly(changes)

        # Stage 1: Packet Loss on WAN edge (3-5 cycles)
        elif self.workflow_stage == 1:
            if stages_elapsed > random.randint(3, 5):
                self.workflow_stage = 2
                self.last_stage_change = self.time_step
                self._inject_wan_latency_anomaly(changes)

        # Stage 2: WAN Latency Increase (2-4 cycles)
        elif self.workflow_stage == 2:
            if stages_elapsed > random.randint(2, 4):
                self.workflow_stage = 3
                self.last_stage_change = self.time_step
                self._inject_bgp_instability_anomaly(changes)

        # Stage 3: BGP Neighbor Instability (2-3 cycles)
        elif self.workflow_stage == 3:
            if stages_elapsed > random.randint(2, 3):
                self.workflow_stage = 4
                self.last_stage_change = self.time_step
                self._inject_voice_degradation_anomaly(changes)

        # Stage 4: Voice Traffic Degradation (1-2 cycles)
        elif self.workflow_stage == 4:
            if stages_elapsed > random.randint(1, 2):
                self.workflow_stage = 5
                self.last_stage_change = self.time_step
                self._inject_critical_incident_anomaly(changes)

        # Stage 5: Critical Incident Active (10-15 cycles, then reset)
        elif self.workflow_stage == 5:
            if stages_elapsed > random.randint(10, 15):
                self.workflow_stage = 0
                self.last_stage_change = self.time_step
                self._reset_workflow_anomalies()

    def _inject_packet_loss_anomaly(self, changes: Dict[str, Any]) -> None:
        """Inject packet loss on WAN edge device."""
        wan_device = self._find_device_by_type_and_site("wan_device", "delhi")
        if wan_device:
            # Increase packet loss on WAN device
            wan_device.status = "warning"
            wan_device.cpu = min(95.0, wan_device.cpu + 15.0)

            anomaly = {
                "type": "packet_loss",
                "device": wan_device.hostname,
                "loss_pct": 8.5,
                "severity": "high",
                "description": f"Packet loss detected on WAN edge {wan_device.hostname}",
            }
            changes["anomalies"].append(anomaly)
            self.anomalies.append(anomaly)

    def _inject_wan_latency_anomaly(self, changes: Dict[str, Any]) -> None:
        """Inject WAN latency increase."""
        wan_device = self._find_device_by_type_and_site("wan_device", "delhi")
        if wan_device:
            # Further increase latency
            wan_device.status = "critical"

            # Affect WAN links
            for link in self.links:
                if "wan-delhi" in {link.source, link.destination}:
                    link.current_latency_ms = min(link.max_latency_ms, link.current_latency_ms + 80.0)
                    link.status = "warning"

            anomaly = {
                "type": "latency_spike",
                "device": wan_device.hostname,
                "latency_ms": 120.0,
                "severity": "high",
                "description": f"WAN latency spike on {wan_device.hostname}",
            }
            changes["anomalies"].append(anomaly)
            self.anomalies.append(anomaly)

    def _inject_bgp_instability_anomaly(self, changes: Dict[str, Any]) -> None:
        """Inject BGP neighbor instability."""
        dc_device = self._find_device_by_type_and_site("data_center_device", "delhi")
        if dc_device and dc_device.bgp_sessions:
            # Set BGP sessions to Idle
            for session in dc_device.bgp_sessions:
                session["state"] = "Idle"

            dc_device.status = "critical"

            anomaly = {
                "type": "bgp_instability",
                "device": dc_device.hostname,
                "down_sessions": len(dc_device.bgp_sessions),
                "severity": "critical",
                "description": f"BGP neighbor instability on {dc_device.hostname}",
            }
            changes["anomalies"].append(anomaly)
            self.anomalies.append(anomaly)

    def _inject_voice_degradation_anomaly(self, changes: Dict[str, Any]) -> None:
        """Inject voice traffic degradation."""
        rtr_device = self._find_device_by_hostname("rtr-delhi")
        if rtr_device:
            # Voice services are impacted by routing instability
            rtr_device.status = "critical"

            anomaly = {
                "type": "voice_degradation",
                "device": rtr_device.hostname,
                "latency_ms": 180.0,
                "severity": "critical",
                "description": f"Voice traffic degradation due to routing instability on {rtr_device.hostname}",
            }
            changes["anomalies"].append(anomaly)
            self.anomalies.append(anomaly)

    def _inject_critical_incident_anomaly(self, changes: Dict[str, Any]) -> None:
        """Inject critical incident escalation."""
        # Multiple devices affected
        affected_devices = []
        for hostname in ["wan-delhi", "dc1-delhi", "rtr-delhi"]:
            device = self.devices.get(hostname)
            if device:
                device.status = "critical"
                affected_devices.append(device)

        anomaly = {
            "type": "critical_incident",
            "devices": [d.hostname for d in affected_devices],
            "severity": "critical",
            "description": "Critical incident: WAN outage affecting Delhi data center and voice services",
        }
        changes["anomalies"].append(anomaly)
        self.anomalies.append(anomaly)

    def _reset_workflow_anomalies(self) -> None:
        """Reset workflow anomalies to normal state."""
        for hostname, device in self.devices.items():
            if hostname in ["wan-delhi", "dc1-delhi", "rtr-delhi"]:
                device.status = "healthy"
                device.cpu = max(10, device.cpu - 20)
                device.memory = max(15, device.memory - 15)

                # Reset BGP sessions
                for session in device.bgp_sessions:
                    session["state"] = "Established"

        # Reset link statuses
        for link in self.links:
            if "wan-delhi" in {link.source, link.destination}:
                link.status = "up"
                link.current_latency_ms = link.max_latency_ms * 0.3  # Reset to normal

    def _find_device_by_type_and_site(self, device_type: str, site: str) -> Optional[SimulatedDevice]:
        """Find a device by type and site."""
        for device in self.devices.values():
            if device.device_type == device_type and device.site == site:
                return device
        return None

    def _find_device_by_hostname(self, hostname: str) -> Optional[SimulatedDevice]:
        """Find a device by hostname."""
        return self.devices.get(hostname)

    # ═══════════════════════════════════════════════════════════════
    # LEGACY ANOMALY SIMULATION (KEPT FOR COMPATIBILITY)
    # ═══════════════════════════════════════════════════════════════

    def _simulate_anomaly(self) -> Optional[Dict[str, Any]]:
        """Simulate a network anomaly (legacy method)."""
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
