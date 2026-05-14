"""
Telemetry engine for realistic dynamic network metrics generation.
"""

from __future__ import annotations
from dataclasses import asdict
from typing import Dict, List, Any, Optional
import json
import os
import random
import re
from datetime import datetime, timedelta

from core.state_manager import StateManager, DeviceMetrics
from core.simulation_engine import SimulationEngine

try:
    from netmiko import ConnectHandler
    NETMIKO_AVAILABLE = True
except Exception:
    NETMIKO_AVAILABLE = False


class TelemetryEngine:
    """
    Collects telemetry from live routers when available and falls back to simulated devices.
    """

    def __init__(
        self,
        simulation: SimulationEngine,
        state_manager: StateManager,
        device_catalog: Optional[List[Dict[str, Any]]] = None,
        poll_interval: int = 10,
    ):
        """Initialize telemetry engine."""
        self.simulation = simulation
        self.state = state_manager
        self.device_catalog = device_catalog or []
        self.poll_interval = poll_interval
        self.live_mode = bool(self.device_catalog and NETMIKO_AVAILABLE)
        self.baseline_metrics: Dict[str, Dict[str, float]] = {}
        self.anomaly_correlation: Dict[str, List[str]] = {}
        self.current_interface_inventory: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self.previous_interface_inventory: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self.interface_history: Dict[str, List[Dict[str, Any]]] = {}
        self.device_reachability: Dict[str, bool] = {}
        self._initialize_baselines()

    def _initialize_baselines(self) -> None:
        """Initialize baseline metrics for all devices."""
        for hostname, device in self.simulation.devices.items():
            self.baseline_metrics[hostname] = {
                "cpu": device.cpu,
                "memory": device.memory,
                "latency_ms": 10 + random.uniform(-2, 2),
                "packet_loss_pct": random.uniform(0, 0.2),
            }

    # ═══════════════════════════════════════════════════════════════
    # TELEMETRY COLLECTION
    # ═══════════════════════════════════════════════════════════════

    def collect_all_telemetry(self) -> Dict[str, Any]:
        """Collect telemetry from live routers or simulation fallback."""
        if self.live_mode:
            return self._collect_live_telemetry()
        return self._collect_simulation_telemetry()

    def _collect_live_telemetry(self) -> Dict[str, Any]:
        telemetry = {
            "timestamp": datetime.utcnow().isoformat(),
            "device_metrics": {},
            "interface_metrics": {},
            "protocol_metrics": {},
            "reachability": {},
        }

        for device in self.device_catalog:
            device_name = self._normalize_device_name(device)
            metrics, interfaces, protocol_metrics = self._collect_live_device_telemetry(device)
            telemetry["device_metrics"][device_name] = metrics
            telemetry["protocol_metrics"][device_name] = protocol_metrics
            telemetry["reachability"][device_name] = metrics.reachable
            self.state.update_device_metrics(device_name, metrics)
            self._update_interface_inventory(device_name, interfaces)

            for interface in interfaces:
                iface_key = f"{device_name}:{interface['name']}"
                telemetry["interface_metrics"][iface_key] = interface

        return telemetry

    def _collect_simulation_telemetry(self) -> Dict[str, Any]:
        telemetry = {
            "timestamp": datetime.utcnow().isoformat(),
            "device_metrics": {},
            "interface_metrics": {},
            "link_metrics": {},
            "protocol_metrics": {},
        }

        # Collect device metrics
        for hostname, device in self.simulation.devices.items():
            metrics = self._collect_device_telemetry(hostname, device)
            telemetry["device_metrics"][hostname] = metrics
            self.state.update_device_metrics(hostname, metrics)

        # Collect interface metrics
        for iface_key, interface in self.simulation.interfaces.items():
            telemetry["interface_metrics"][iface_key] = self._collect_interface_telemetry(interface)

        # Collect link metrics
        for link in self.simulation.links:
            link_key = f"{link.source}→{link.destination}"
            telemetry["link_metrics"][link_key] = self._collect_link_telemetry(link)

        # Collect protocol metrics
        telemetry["protocol_metrics"] = self._collect_protocol_metrics()

        return telemetry

    def _normalize_device_name(self, device: Dict[str, Any]) -> str:
        return str(
            device.get("hostname")
            or device.get("name")
            or device.get("host")
            or device.get("ip_address")
            or device.get("device_id")
        )

    def _collect_live_device_telemetry(self, device: Dict[str, Any]) -> tuple[DeviceMetrics, List[Dict[str, Any]], Dict[str, Any]]:
        device_name = self._normalize_device_name(device)
        now = datetime.utcnow().isoformat()
        device_metrics = DeviceMetrics(hostname=device_name, last_updated=now)
        interfaces: List[Dict[str, Any]] = []
        protocol_metrics: Dict[str, Any] = {
            "bgp_summary": {},
            "route_summary": {},
        }

        if not NETMIKO_AVAILABLE:
            device_metrics.reachable = False
            return device_metrics, interfaces, protocol_metrics

        try:
            conn = ConnectHandler(**device)
            if device.get("secret"):
                conn.enable()

            interface_output = conn.send_command("show ip interface brief", use_textfsm=False)
            interfaces = self._parse_ip_interface_brief(interface_output)

            bgp_output = conn.send_command("show ip bgp summary", use_textfsm=False)
            protocol_metrics["bgp_summary"] = self._parse_bgp_summary(bgp_output, device_name)

            cpu_output = conn.send_command("show processes cpu | include CPU", use_textfsm=False)
            device_metrics.cpu = self._parse_cpu_utilization(cpu_output)

            memory_output = conn.send_command("show processes memory | include Processor|show version | include bytes of memory", use_textfsm=False)
            device_metrics.memory = self._parse_memory_usage(memory_output)

            route_output = conn.send_command("show ip route summary", use_textfsm=False)
            protocol_metrics["route_summary"] = self._parse_route_summary(route_output)

            conn.disconnect()
            device_metrics.reachable = True
            self.device_reachability[device_name] = True

            interface_down = sum(1 for iface in interfaces if iface["status"] != "up")
            if interface_down > 0:
                device_metrics.packet_loss_pct = min(100.0, 2.0 + interface_down * 1.5)
            else:
                device_metrics.packet_loss_pct = max(0.0, device_metrics.packet_loss_pct)

            device_metrics.latency_ms = 10.0 + interface_down * 5.0
            device_metrics.bgp_sessions_up = protocol_metrics["bgp_summary"].get("established", 0)
            device_metrics.bgp_sessions_down = protocol_metrics["bgp_summary"].get("down", 0)
            device_metrics.interface_errors = sum(iface.get("errors", 0) for iface in interfaces)

        except Exception:
            device_metrics.reachable = False
            device_metrics.cpu = 0.0
            device_metrics.memory = 0.0
            device_metrics.latency_ms = 999.0
            device_metrics.packet_loss_pct = 100.0
            device_metrics.bgp_sessions_up = 0
            device_metrics.bgp_sessions_down = 0
            device_metrics.interface_errors = 0
            self.device_reachability[device_name] = False
            interfaces = []

        return device_metrics, interfaces, protocol_metrics

    def _parse_ip_interface_brief(self, output: str) -> List[Dict[str, Any]]:
        interfaces: List[Dict[str, Any]] = []
        for line in output.splitlines():
            line = line.strip()
            if not line or line.lower().startswith("interface"):
                continue
            m = re.match(r"^(?P<intf>\S+)\s+(?P<ip>\S+)\s+\S+\s+\S+\s+(?P<status>\S+)\s+(?P<protocol>\S+)$", line)
            if not m:
                continue
            interfaces.append({
                "name": m.group("intf"),
                "ip_address": m.group("ip") if m.group("ip") != "unassigned" else "",
                "status": m.group("status").lower(),
                "protocol": m.group("protocol").lower(),
                "errors": 0,
                "drops": 0,
                "last_updated": datetime.utcnow().isoformat(),
            })
        return interfaces

    def _parse_bgp_summary(self, output: str, device_name: str) -> Dict[str, Any]:
        summary = {
            "local_device": device_name,
            "total_neighbors": 0,
            "established": 0,
            "down": 0,
            "peers": [],
        }
        for line in output.splitlines():
            if line.strip().startswith("Neighbor") or line.strip().startswith("BGP router identifier"):
                continue
            parts = re.split(r"\s+", line.strip())
            if len(parts) < 9:
                continue
            peer_ip = parts[0]
            state = parts[-1]
            status = "down" if state.lower() not in {"established", "up"} else "up"
            summary["total_neighbors"] += 1
            summary["established"] += 1 if status == "up" else 0
            summary["down"] += 1 if status == "down" else 0
            summary["peers"].append({"peer_ip": peer_ip, "state": state, "session_status": status})
        return summary

    def _parse_cpu_utilization(self, output: str) -> float:
        m = re.search(r"five seconds: (\d+)%", output)
        if m:
            return float(m.group(1))
        m = re.search(r"CPU utilization for five seconds: (\d+)%", output)
        if m:
            return float(m.group(1))
        m = re.search(r"(\d+)%\s*\/$", output)
        return float(m.group(1)) if m else 0.0

    def _parse_memory_usage(self, output: str) -> float:
        total = None
        used = None
        total_match = re.search(r"Processor Pool Total:\s*(\d+)K", output)
        used_match = re.search(r"Processor Pool Used:\s*(\d+)K", output)
        if total_match and used_match:
            total = float(total_match.group(1))
            used = float(used_match.group(1))
        else:
            total_match = re.search(r"(\d+) bytes of memory", output)
            if total_match:
                total = float(total_match.group(1)) / 1024.0
            if total:
                used = total * 0.4
        if total and used:
            return min(100.0, max(0.0, used / total * 100.0))
        return 0.0

    def _parse_route_summary(self, output: str) -> Dict[str, Any]:
        routes = 0
        for line in output.splitlines():
            if "routes" in line.lower() and "," in line:
                nums = re.findall(r"(\d+)\s+routes", line)
                if nums:
                    routes = int(nums[0])
                    break
        return {"route_count": routes}

    def _update_interface_inventory(self, device_name: str, interfaces: List[Dict[str, Any]]) -> None:
        previous = self.current_interface_inventory.get(device_name, {})
        current = {iface["name"]: iface for iface in interfaces}
        self.previous_interface_inventory[device_name] = previous
        self.current_interface_inventory[device_name] = current

        if device_name not in self.interface_history:
            self.interface_history[device_name] = []

        for iface in interfaces:
            self.interface_history[device_name].append(iface)
            if len(self.interface_history[device_name]) > 1000:
                self.interface_history[device_name] = self.interface_history[device_name][-1000:]

    def _collect_interface_telemetry(self, interface) -> Dict[str, Any]:
        """Collect interface-level telemetry."""
        utilization = interface.utilization_pct + random.uniform(-5, 8)
        errors = interface.errors + (1 if random.random() < 0.05 else 0)
        drops = interface.drops + (random.randint(0, 10) if random.random() < 0.05 else 0)

        return {
            "device": interface.device,
            "interface": interface.name,
            "status": interface.status,
            "utilization_pct": max(0, min(100, utilization)),
            "errors": errors,
            "drops": drops,
            "latency_ms": interface.latency_ms,
            "packet_loss_pct": interface.packet_loss_pct,
            "bandwidth_mbps": interface.bandwidth_mbps,
        }

    def _collect_link_telemetry(self, link) -> Dict[str, Any]:
        """Collect link-level telemetry."""
        latency = link.current_latency_ms + random.uniform(-5, 10)
        
        return {
            "source": link.source,
            "destination": link.destination,
            "type": link.link_type,
            "status": link.status,
            "bandwidth_mbps": link.bandwidth_mbps,
            "latency_ms": max(0, latency),
            "utilization_pct": random.uniform(5, 60),
        }

    def _collect_protocol_metrics(self) -> Dict[str, Any]:
        """Collect BGP, OSPF, and other protocol metrics."""
        metrics = {
            "bgp_summary": {
                "total_sessions": 0,
                "established": 0,
                "idle": 0,
                "prefixes_advertised": 0,
            },
            "ospf_summary": {
                "total_neighbors": 0,
                "full_state": 0,
            },
        }

        for device in self.simulation.devices.values():
            metrics["bgp_summary"]["total_sessions"] += len(device.bgp_sessions)
            metrics["bgp_summary"]["established"] += sum(
                1 for s in device.bgp_sessions if s.get("state") == "Established"
            )
            metrics["bgp_summary"]["idle"] += sum(
                1 for s in device.bgp_sessions if s.get("state") == "Idle"
            )
            metrics["ospf_summary"]["total_neighbors"] += len(device.ospf_neighbors)

        return metrics

    # ═══════════════════════════════════════════════════════════════
    # ANOMALY DETECTION & CORRELATION
    # ═══════════════════════════════════════════════════════════════

    def detect_anomalies(self) -> List[Dict[str, Any]]:
        """Detect anomalies from current telemetry."""
        anomalies = []

        for hostname, metrics in self.state.get_all_device_metrics().items():
            if not getattr(metrics, "reachable", True):
                anomalies.append({
                    "type": "device_unreachable",
                    "severity": "critical",
                    "device": hostname,
                    "description": "Device is unreachable over Netmiko.",
                })
                continue

            if metrics.cpu >= 90:
                anomalies.append({
                    "type": "cpu_spike",
                    "severity": "critical",
                    "device": hostname,
                    "value": metrics.cpu,
                    "threshold": 90,
                })

            if metrics.memory >= 90:
                anomalies.append({
                    "type": "memory_exhaustion",
                    "severity": "critical",
                    "device": hostname,
                    "value": metrics.memory,
                    "threshold": 90,
                })

            if metrics.latency_ms > 100:
                anomalies.append({
                    "type": "latency_spike",
                    "severity": "high",
                    "device": hostname,
                    "value": metrics.latency_ms,
                    "threshold": 100,
                })

            if metrics.packet_loss_pct > 5:
                anomalies.append({
                    "type": "packet_loss",
                    "severity": "high",
                    "device": hostname,
                    "value": metrics.packet_loss_pct,
                    "threshold": 5,
                })

            if metrics.bgp_sessions_down > 0:
                anomalies.append({
                    "type": "bgp_instability",
                    "severity": "high",
                    "device": hostname,
                    "down_sessions": metrics.bgp_sessions_down,
                })

            if self._has_interface_down_transition(hostname):
                anomalies.append({
                    "type": "interface_down",
                    "severity": "critical",
                    "device": hostname,
                    "description": "Interface transitioned from up to down.",
                })

        for anomaly in self.simulation.anomalies[-10:]:
            if anomaly.get("type") == "voice_degradation" and anomaly.get("device"):
                anomalies.append({
                    "type": "voice_degradation",
                    "severity": "critical",
                    "device": anomaly.get("device"),
                    "latency_ms": anomaly.get("latency_ms", 180),
                    "description": "Voice traffic experiencing jitter and degraded MOS scores",
                })
            elif anomaly.get("type") == "critical_incident" and anomaly.get("device"):
                anomalies.append({
                    "type": "critical_incident",
                    "severity": "critical",
                    "device": anomaly.get("device"),
                    "description": "Part of critical incident affecting multiple services",
                })

        return anomalies

    def _has_interface_down_transition(self, hostname: str) -> bool:
        current = self.current_interface_inventory.get(hostname, {})
        previous = self.previous_interface_inventory.get(hostname, {})
        for iface_name, iface in current.items():
            prev = previous.get(iface_name)
            if prev and prev.get("status") == "up" and iface.get("status") == "down":
                return True
        return False

    def correlate_anomalies(self, anomalies: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        """Correlate related anomalies."""
        correlation = {}
        
        # Group anomalies by severity and type
        for anomaly in anomalies:
            key = f"{anomaly['severity']}:{anomaly['type']}"
            if key not in correlation:
                correlation[key] = []
            correlation[key].append(anomaly.get("device", "unknown"))

        self.anomaly_correlation = correlation
        return correlation

    # ═══════════════════════════════════════════════════════════════
    # TELEMETRY ANALYTICS
    # ═══════════════════════════════════════════════════════════════

    def get_health_metrics(self) -> Dict[str, Any]:
        """Get overall health metrics."""
        all_metrics = self.state.get_all_device_metrics()
        
        if not all_metrics:
            return {"status": "no_data"}

        cpus = [m.cpu for m in all_metrics.values()]
        memories = [m.memory for m in all_metrics.values()]
        latencies = [m.latency_ms for m in all_metrics.values()]
        packet_losses = [m.packet_loss_pct for m in all_metrics.values()]
        unreachable_count = sum(1 for m in all_metrics.values() if getattr(m, "reachable", True) is False)

        return {
            "cpu": {
                "average": sum(cpus) / len(cpus),
                "max": max(cpus),
                "min": min(cpus),
                "high_count": sum(1 for c in cpus if c > 80),
            },
            "memory": {
                "average": sum(memories) / len(memories),
                "max": max(memories),
                "min": min(memories),
                "high_count": sum(1 for m in memories if m > 80),
            },
            "latency_ms": {
                "average": sum(latencies) / len(latencies),
                "max": max(latencies),
                "min": min(latencies),
                "high_count": sum(1 for l in latencies if l > 100),
            },
            "packet_loss_pct": {
                "average": sum(packet_losses) / len(packet_losses),
                "max": max(packet_losses),
                "high_count": sum(1 for p in packet_losses if p > 3),
            },
            "bgp_down_sessions": sum(m.bgp_sessions_down for m in all_metrics.values()),
            "unreachable_devices": unreachable_count,
            "critical_device_count": len(self.state.get_critical_devices()),
        }

    def get_device_health_score(self, hostname: str) -> Dict[str, Any]:
        """Calculate health score for a specific device."""
        metrics = self.state.get_device_metrics(hostname)
        
        if not metrics:
            return {"score": 0, "status": "unknown"}

        score = 100.0
        issues = []

        if not getattr(metrics, "reachable", True):
            score -= 50
            issues.append("Device unreachable")

        if metrics.cpu > 85:
            score -= 20
            issues.append(f"High CPU: {metrics.cpu:.1f}%")
        elif metrics.cpu > 70:
            score -= 10

        if metrics.memory > 85:
            score -= 20
            issues.append(f"High Memory: {metrics.memory:.1f}%")
        elif metrics.memory > 70:
            score -= 10

        if metrics.latency_ms > 100:
            score -= 15
            issues.append(f"High Latency: {metrics.latency_ms:.1f}ms")

        if metrics.packet_loss_pct > 5:
            score -= 15
            issues.append(f"Packet Loss: {metrics.packet_loss_pct:.2f}%")

        if metrics.bgp_sessions_down > 0:
            score -= 10
            issues.append(f"BGP Down: {metrics.bgp_sessions_down} sessions")

        status = (
            "critical" if score < 30
            else "warning" if score < 70
            else "healthy"
        )

        return {
            "device": hostname,
            "score": max(0, score),
            "status": status,
            "issues": issues,
        }

    # ═══════════════════════════════════════════════════════════════
    # TIMELINE & TRENDING
    # ═══════════════════════════════════════════════════════════════

    def get_device_timeline(self, hostname: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get telemetry timeline for a device."""
        history = self.state.get_telemetry_history(hostname, limit)
        return [
            {
                "timestamp": item.get("last_updated"),
                "cpu": item.get("cpu"),
                "memory": item.get("memory"),
                "latency_ms": item.get("latency_ms"),
                "packet_loss_pct": item.get("packet_loss_pct"),
            }
            for item in history
        ]

    def export_telemetry_state(self) -> Dict[str, Any]:
        """Export complete telemetry state."""
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "health_metrics": self.get_health_metrics(),
            "anomalies": self.detect_anomalies(),
            "anomaly_correlation": self.anomaly_correlation,
            "critical_devices": [
                d for d in self.state.get_all_device_metrics().keys()
                if self.get_device_health_score(d)["status"] == "critical"
            ],
        }
