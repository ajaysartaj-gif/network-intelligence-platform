"""
Telemetry engine for realistic dynamic network metrics generation.
"""

from __future__ import annotations
from dataclasses import asdict
from typing import Dict, List, Any, Optional
import random
from datetime import datetime, timedelta

from core.state_manager import StateManager, DeviceMetrics
from core.simulation_engine import SimulationEngine


class TelemetryEngine:
    """
    Generates realistic, event-driven network telemetry.
    Integrates with simulation engine and state manager.
    """

    def __init__(self, simulation: SimulationEngine, state_manager: StateManager):
        """Initialize telemetry engine."""
        self.simulation = simulation
        self.state = state_manager
        self.baseline_metrics: Dict[str, Dict[str, float]] = {}
        self.anomaly_correlation: Dict[str, List[str]] = {}
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
        """Collect telemetry from all simulated devices."""
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

    def _collect_device_telemetry(self, hostname: str, device) -> DeviceMetrics:
        """Collect device-level telemetry."""
        baseline = self.baseline_metrics.get(hostname, {})
        
        # Apply some random drift to simulate real metrics
        cpu = max(2, min(98, device.cpu + random.uniform(-2, 3)))
        memory = max(5, min(98, device.memory + random.uniform(-1, 2)))
        latency = baseline.get("latency_ms", 10) + random.uniform(-1, 5)
        packet_loss = baseline.get("packet_loss_pct", 0) + random.uniform(-0.1, 0.3)

        # Count BGP and OSPF state
        bgp_up = sum(1 for s in device.bgp_sessions if s.get("state") == "Established")
        bgp_down = len(device.bgp_sessions) - bgp_up

        # Count interface errors from anomalies
        iface_errors = sum(
            1 for a in self.simulation.anomalies
            if a.get("device") == hostname and a.get("type") == "interface_flap"
        )

        metrics = DeviceMetrics(
            hostname=hostname,
            cpu=cpu,
            memory=memory,
            latency_ms=max(0, latency),
            packet_loss_pct=max(0, min(100, packet_loss)),
            interface_errors=iface_errors,
            bgp_sessions_up=bgp_up,
            bgp_sessions_down=bgp_down,
            ospf_neighbors=len(device.ospf_neighbors),
            last_updated=datetime.utcnow().isoformat(),
        )

        return metrics

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
            # CPU anomalies
            if metrics.cpu >= 90:
                anomalies.append({
                    "type": "cpu_spike",
                    "severity": "critical",
                    "device": hostname,
                    "value": metrics.cpu,
                    "threshold": 90,
                })
            
            # Memory anomalies
            if metrics.memory >= 90:
                anomalies.append({
                    "type": "memory_exhaustion",
                    "severity": "critical",
                    "device": hostname,
                    "value": metrics.memory,
                    "threshold": 90,
                })
            
            # Latency anomalies
            if metrics.latency_ms > 100:
                anomalies.append({
                    "type": "latency_spike",
                    "severity": "high",
                    "device": hostname,
                    "value": metrics.latency_ms,
                    "threshold": 100,
                })
            
            # Packet loss anomalies
            if metrics.packet_loss_pct > 5:
                anomalies.append({
                    "type": "packet_loss",
                    "severity": "high",
                    "device": hostname,
                    "value": metrics.packet_loss_pct,
                    "threshold": 5,
                })
            
            # BGP instability
            if metrics.bgp_sessions_down > 0:
                anomalies.append({
                    "type": "bgp_instability",
                    "severity": "high",
                    "device": hostname,
                    "down_sessions": metrics.bgp_sessions_down,
                })

        return anomalies

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

        high_cpu = sum(1 for c in cpus if c > 80)
        high_memory = sum(1 for m in memories if m > 80)
        high_latency = sum(1 for l in latencies if l > 100)
        high_packet_loss = sum(1 for p in packet_losses if p > 3)
        bgp_down = sum(m.bgp_sessions_down for m in all_metrics.values())

        return {
            "cpu": {
                "average": sum(cpus) / len(cpus),
                "max": max(cpus),
                "min": min(cpus),
                "high_count": high_cpu,
            },
            "memory": {
                "average": sum(memories) / len(memories),
                "max": max(memories),
                "min": min(memories),
                "high_count": high_memory,
            },
            "latency_ms": {
                "average": sum(latencies) / len(latencies),
                "max": max(latencies),
                "min": min(latencies),
                "high_count": high_latency,
            },
            "packet_loss_pct": {
                "average": sum(packet_losses) / len(packet_losses),
                "max": max(packet_losses),
                "high_count": high_packet_loss,
            },
            "bgp_down_sessions": bgp_down,
            "critical_device_count": len(self.state.get_critical_devices()),
        }

    def get_device_health_score(self, hostname: str) -> Dict[str, Any]:
        """Calculate health score for a specific device."""
        metrics = self.state.get_device_metrics(hostname)
        
        if not metrics:
            return {"score": 0, "status": "unknown"}

        score = 100.0
        issues = []

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
