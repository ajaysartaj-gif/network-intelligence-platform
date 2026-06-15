from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class DeviceState:
    hostname: str
    vendor: str
    model: str
    os_version: str
    status: str = "healthy"
    cpu: float = 0.0
    memory: float = 0.0
    interfaces: List[Dict[str, object]] = field(default_factory=list)


@dataclass
class TopologyLink:
    source: str
    destination: str
    link_type: str
    status: str = "up"
    bandwidth_mbps: float = 1000.0


class DigitalTwinEngine:
    """Digital twin engine for simulated device state and topology impact."""

    def __init__(self) -> None:
        self.devices: Dict[str, DeviceState] = {}
        self.links: List[TopologyLink] = []

    def add_device(self, device: DeviceState) -> None:
        self.devices[device.hostname] = device

    def add_link(self, link: TopologyLink) -> None:
        self.links.append(link)

    def get_topology(self) -> Dict[str, object]:
        return {
            "devices": list(self.devices.keys()),
            "links": [link.__dict__ for link in self.links],
        }

    def simulate_impact(self, hostname: str, change: str) -> Dict[str, object]:
        if hostname not in self.devices:
            return {"error": "device not found", "device": hostname}

        impacted = [hostname]
        for link in self.links:
            if link.source == hostname and link.destination in self.devices:
                impacted.append(link.destination)
            if link.destination == hostname and link.source in self.devices:
                impacted.append(link.source)

        return {
            "device": hostname,
            "change": change,
            "impact_scope": list(dict.fromkeys(impacted)),
            "estimated_risk": "medium" if len(impacted) > 2 else "low",
        }

    def simulate_change(self, hostname: str, action: str) -> Dict[str, object]:
        if hostname not in self.devices:
            return {"error": "device not found", "device": hostname}

        device = self.devices[hostname]
        device.status = "updating"
        if "upgrade" in action.lower() or "patch" in action.lower():
            device.cpu = min(100.0, device.cpu + 12.0)
            device.memory = min(100.0, device.memory + 8.0)
            device.status = "provisioning"
        elif "rollback" in action.lower():
            device.status = "healthy"
            device.cpu = max(0.0, device.cpu - 10.0)
            device.memory = max(0.0, device.memory - 8.0)
        return {
            "device": hostname,
            "action": action,
            "status": device.status,
            "cpu": device.cpu,
            "memory": device.memory,
        }

    def topology_summary(self) -> Dict[str, int]:
        return {
            "device_count": len(self.devices),
            "link_count": len(self.links),
            "healthy_devices": sum(1 for device in self.devices.values() if device.status == "healthy"),
        }
