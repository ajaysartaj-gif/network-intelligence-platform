from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List


@dataclass
class MetricSample:
    device: str
    metric: str
    value: float
    unit: str
    status: str


class ObservabilityEngine:
    """Enterprise observability engine for network metrics and alerting."""

    CPU_WARNING = 70.0
    CPU_CRITICAL = 90.0
    MEMORY_WARNING = 65.0
    MEMORY_CRITICAL = 90.0
    INTERFACE_UTILIZATION_WARNING = 70.0
    INTERFACE_UTILIZATION_CRITICAL = 90.0

    def collect_cpu_metrics(self, device_states: List[Dict[str, object]]) -> List[MetricSample]:
        samples: List[MetricSample] = []
        for device in device_states:
            cpu = float(device.get("cpu", 0.0))
            if cpu >= self.CPU_CRITICAL:
                status = "critical"
            elif cpu >= self.CPU_WARNING:
                status = "warning"
            else:
                status = "healthy"
            samples.append(MetricSample(device=device.get("hostname", "unknown"), metric="cpu", value=cpu, unit="%", status=status))
        return samples

    def collect_memory_metrics(self, device_states: List[Dict[str, object]]) -> List[MetricSample]:
        samples: List[MetricSample] = []
        for device in device_states:
            memory = float(device.get("memory", 0.0))
            if memory >= self.MEMORY_CRITICAL:
                status = "critical"
            elif memory >= self.MEMORY_WARNING:
                status = "warning"
            else:
                status = "healthy"
            samples.append(MetricSample(device=device.get("hostname", "unknown"), metric="memory", value=memory, unit="%", status=status))
        return samples

    def collect_interface_metrics(self, interfaces: List[Dict[str, object]]) -> List[MetricSample]:
        samples: List[MetricSample] = []
        for interface in interfaces:
            utilization = float(interface.get("utilization", 0.0))
            if utilization >= self.INTERFACE_UTILIZATION_CRITICAL:
                status = "critical"
            elif utilization >= self.INTERFACE_UTILIZATION_WARNING:
                status = "warning"
            else:
                status = "healthy"
            samples.append(
                MetricSample(
                    device=interface.get("device", "unknown"),
                    metric=f"interface:{interface.get('interface_name', 'unknown')}",
                    value=utilization,
                    unit="%",
                    status=status,
                )
            )
        return samples

    def collect_bgp_state(self, peers: List[Dict[str, object]]) -> List[Dict[str, object]]:
        states: List[Dict[str, object]] = []
        for peer in peers:
            state = peer.get("state", "unknown").lower()
            session_status = "unknown"
            if state in {"established", "up", "active"}:
                session_status = "up"
            elif state in {"idle", "down", "inactive", "failed"}:
                session_status = "down"
            else:
                session_status = "warning"
            states.append(
                {
                    "local_device": peer.get("local_device", "unknown"),
                    "peer_ip": peer.get("peer_ip", "unknown"),
                    "state": state,
                    "session_status": session_status,
                    "prefixes_received": peer.get("prefixes_received", 0),
                }
            )
        return states

    def generate_alerts(
        self,
        cpu_metrics: List[MetricSample],
        memory_metrics: List[MetricSample],
        interface_metrics: List[MetricSample],
        bgp_sessions: List[Dict[str, object]],
    ) -> List[Dict[str, object]]:
        alerts: List[Dict[str, object]] = []
        for metric in cpu_metrics + memory_metrics + interface_metrics:
            if metric.status in {"warning", "critical"}:
                alerts.append(
                    {
                        "device": metric.device,
                        "alert_type": metric.metric,
                        "severity": metric.status,
                        "message": f"{metric.metric.upper()} is {metric.value}{metric.unit} on {metric.device}",
                    }
                )
        for session in bgp_sessions:
            if session["session_status"] == "down":
                alerts.append(
                    {
                        "device": session["local_device"],
                        "alert_type": "bgp",
                        "severity": "critical",
                        "message": f"BGP session to {session['peer_ip']} is {session['state']}",
                    }
                )
        return alerts

    def summarize_observability(self, device_states: List[Dict[str, object]], bgp_peers: List[Dict[str, object]]) -> Dict[str, object]:
        return {
            "cpu": self.collect_cpu_metrics(device_states),
            "memory": self.collect_memory_metrics(device_states),
            "interfaces": self.collect_interface_metrics(device_states),
            "bgp": self.collect_bgp_state(bgp_peers),
        }
