from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from core.compliance_engine import ComplianceEngine
from core.digital_twin_engine import DigitalTwinEngine, DeviceState, TopologyLink
from core.incident_engine import IncidentEngine
from core.knowledge_graph import KnowledgeGraph
from core.nlp_engine import NLPEngine
from core.observability_engine import ObservabilityEngine
from core.rag_engine import KnowledgeDocument, RAGEngine
from core.self_healing_engine import RemediationAction, SelfHealingEngine


@dataclass
class QueryRecord:
    query: str
    response: str
    source: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


class OperationsOrchestrator:
    """Orchestrates network operations engines for diagnostics, impact analysis, and AI workflows."""

    def __init__(self, documents: Optional[List[Dict[str, str]]] = None) -> None:
        self.nlp = NLPEngine()
        self.rag = RAGEngine(documents or [])
        self.obs = ObservabilityEngine()
        self.incident = IncidentEngine()
        self.twin = DigitalTwinEngine()
        self.comp = ComplianceEngine()
        self.kg = KnowledgeGraph()
        self.self_heal = SelfHealingEngine()
        self.query_history: List[QueryRecord] = []
        self._seed_default_documents()
        self._seed_knowledge_graph()

    def _seed_default_documents(self) -> None:
        self.rag.seed_documents([
            {
                "id": "bgp-flap-1",
                "title": "BGP flap troubleshooting",
                "vendor": "Cisco",
                "protocol": "BGP",
                "content": "Use show bgp summary, inspect neighbor state, validate TCP reachability, and check policy filters.",
            },
            {
                "id": "cpu-pressure",
                "title": "High CPU troubleshooting",
                "vendor": "Juniper",
                "protocol": "System",
                "content": "Review process activity, commit queue, control plane load, and firewall sessions for CPU pressure.",
            },
            {
                "id": "memory-leak",
                "title": "Memory leak detection",
                "vendor": "Arista",
                "protocol": "Telemetry",
                "content": "Track memory growth over time, identify leaked kernel buffers, and validate process memory allocations.",
            },
        ])

    def _seed_knowledge_graph(self) -> None:
        # Seed basic network topology relationships
        devices = ["DEL-CORE-01", "MUM-EDGE-01", "BLR-FW-01", "HYD-LEAF-02"]
        services = ["Internet", "Intranet", "Database", "Web"]
        
        for device in devices:
            self.kg.add_node(device, "Device", {"type": "network_device", "vendor": "Cisco"})
        
        for service in services:
            self.kg.add_node(service, "Service", {"type": "business_service"})
        
        # Add dependencies
        self.kg.add_relationship("DEL-CORE-01", "MUM-EDGE-01", "connects_to", 1.0, {"link_type": "MPLS"})
        self.kg.add_relationship("MUM-EDGE-01", "BLR-FW-01", "connects_to", 1.0, {"link_type": "Internet"})
        self.kg.add_relationship("BLR-FW-01", "HYD-LEAF-02", "connects_to", 1.0, {"link_type": "LAN"})
        
        self.kg.add_relationship("DEL-CORE-01", "Internet", "provides_access", 0.8)
        self.kg.add_relationship("MUM-EDGE-01", "Intranet", "provides_access", 0.9)
        self.kg.add_relationship("BLR-FW-01", "Database", "secures", 1.0)
        self.kg.add_relationship("HYD-LEAF-02", "Web", "hosts", 0.7)

    def record_query(self, query: str, response: str, source: str = "user") -> None:
        self.query_history.append(QueryRecord(query=query, response=response, source=source))

    def get_query_history(self, limit: int = 20) -> List[Dict[str, object]]:
        return [
            {
                "query": record.query,
                "response": record.response,
                "source": record.source,
                "timestamp": record.timestamp.isoformat(),
            }
            for record in self.query_history[-limit:]
        ]

    def build_topology(self, devices: List[Dict[str, object]], links: List[Dict[str, object]]) -> None:
        self.kg = KnowledgeGraph()
        self.twin = DigitalTwinEngine()
        for device in devices:
            hostname = device.get("hostname")
            if not hostname:
                continue
            self.kg.add_node(hostname, device.get("role", "device"), attributes={
                "vendor": device.get("vendor"),
                "site": device.get("site"),
            })
            self.twin.add_device(
                DeviceState(
                    hostname=hostname,
                    vendor=device.get("vendor", "unknown"),
                    model=device.get("model", "unknown"),
                    os_version=device.get("os_version", "unknown"),
                    status=device.get("status", "healthy"),
                    cpu=float(device.get("cpu", 0.0)) if device.get("cpu") is not None else 0.0,
                    memory=float(device.get("memory", 0.0)) if device.get("memory") is not None else 0.0,
                    interfaces=device.get("interfaces", []),
                )
            )

        for link in links:
            source = link.get("source_device") or link.get("source")
            destination = link.get("destination_device") or link.get("destination")
            if not source or not destination:
                continue
            self.kg.add_node(source, "device")
            self.kg.add_node(destination, "device")
            self.kg.add_relationship(source, destination, link.get("link_type", "link"), weight=float(link.get("bandwidth_mbps", 1.0)))
            self.twin.add_link(
                TopologyLink(
                    source=source,
                    destination=destination,
                    link_type=link.get("link_type", "link"),
                    status=link.get("status", "up"),
                    bandwidth_mbps=float(link.get("bandwidth_mbps", 0.0) or 0.0),
                )
            )

    def detect_anomalies(
        self,
        device_states: List[Dict[str, object]],
        interfaces: List[Dict[str, object]],
        bgp_peers: List[Dict[str, object]],
    ) -> List[Dict[str, object]]:
        anomalies: List[Dict[str, object]] = []
        cpu_samples = self.obs.collect_cpu_metrics(device_states)
        memory_samples = self.obs.collect_memory_metrics(device_states)
        interface_samples = self.obs.collect_interface_metrics(interfaces)

        for sample in cpu_samples + memory_samples + interface_samples:
            if sample.status in {"warning", "critical"}:
                anomalies.append({
                    "device": sample.device,
                    "metric": sample.metric,
                    "status": sample.status,
                    "value": sample.value,
                    "unit": sample.unit,
                })

        for peer in self.obs.collect_bgp_state(bgp_peers):
            if peer["session_status"] == "down":
                anomalies.append({
                    "device": peer["local_device"],
                    "metric": "bgp",
                    "status": "critical",
                    "note": f"Peer {peer['peer_ip']} is {peer['state']}",
                })

        return anomalies

    def score_device_health(self, device: Dict[str, object]) -> float:
        cpu = float(device.get("cpu", 0.0))
        memory = float(device.get("memory", 0.0))
        compliance = self.comp.evaluate_device(device).get("compliance_score", 100.0)
        health = 100.0 - (cpu * 0.25 + memory * 0.25 + (100.0 - compliance) * 0.5)
        return round(max(0.0, min(100.0, health)), 2)

    def get_executive_summary(
        self,
        devices: List[Dict[str, object]],
        incidents: List[Dict[str, object]],
        anomalies: List[Dict[str, object]],
    ) -> Dict[str, object]:
        healthy = sum(1 for device in devices if self.score_device_health(device) >= 75.0)
        critical_incidents = sum(1 for incident in incidents if incident.get("severity", "").lower() in {"high", "critical"})
        return {
            "device_count": len(devices),
            "healthy_device_count": healthy,
            "incident_count": len(incidents),
            "critical_incident_count": critical_incidents,
            "anomaly_count": len(anomalies),
            "average_health_score": round(sum(self.score_device_health(device) for device in devices) / max(1, len(devices)), 2),
        }

    def root_cause_analysis(
        self,
        query: str,
        device_states: List[Dict[str, object]],
        interfaces: List[Dict[str, object]],
        bgp_peers: List[Dict[str, object]],
        incidents: List[Dict[str, object]],
    ) -> str:
        normalized = query.lower()
        if "bgp" in normalized:
            down_peers = [peer for peer in self.obs.collect_bgp_state(bgp_peers) if peer["session_status"] == "down"]
            if down_peers:
                return f"Likely BGP neighbor instability; down sessions exist on {', '.join({peer['local_device'] for peer in down_peers})}."
            return "BGP appears up; investigate route policies and peer flaps."

        if "cpu" in normalized:
            high_cpu = [d for d in self.obs.collect_cpu_metrics(device_states) if d.status in {"warning", "critical"}]
            if high_cpu:
                return f"CPU pressure detected on {', '.join({d.device for d in high_cpu})}; verify process and traffic patterns."

        if "memory" in normalized:
            high_mem = [d for d in self.obs.collect_memory_metrics(device_states) if d.status in {"warning", "critical"}]
            if high_mem:
                return f"Memory stress detected on {', '.join({d.device for d in high_mem})}; investigate caching or process growth."

        packet_loss = [iface for iface in interfaces if float(iface.get("packet_loss", 0.0)) > 1.0]
        if packet_loss:
            return f"Packet loss observed on {', '.join({iface.get('interface_name', 'unknown') for iface in packet_loss})}; validate link health and queue drops."

        return "No obvious root cause found locally; use AI engine for deeper interpretation."

    def ai_troubleshoot(
        self,
        query: str,
        device_states: List[Dict[str, object]],
        interfaces: List[Dict[str, object]],
        bgp_peers: List[Dict[str, object]],
        incidents: List[Dict[str, object]],
        links: List[Dict[str, object]],
    ) -> Dict[str, object]:
        analysis = self.nlp.extract_entities(query)
        docs = self.rag.search(query, vendor=(analysis["vendors"][0] if analysis["vendors"] else None), protocol=(analysis["protocols"][0] if analysis["protocols"] else None))
        anomalies = self.detect_anomalies(device_states, interfaces, bgp_peers)
        root_cause = self.root_cause_analysis(query, device_states, interfaces, bgp_peers, incidents)
        recommendation = "Review related anomalies and validate device state." if anomalies else "No local anomalies detected."
        self.record_query(query, root_cause)
        return {
            "query": query,
            "entities": analysis,
            "root_cause": root_cause,
            "recommendation": recommendation,
            "documents": docs,
            "anomalies": anomalies,
            "executive_summary": self.get_executive_summary(device_states, incidents, anomalies),
            "topology_links": links,
        }

    def recommend_remediation(self, alerts: List[Dict[str, object]], device_states: List[Dict[str, object]]) -> List[RemediationAction]:
        actions: List[RemediationAction] = []
        for alert in alerts:
            device_name = alert.get("device")
            device = next((device for device in device_states if device.get("hostname") == device_name), {})
            actions.extend(self.self_heal.recommend_remediation(alert, device))
        return actions

    def service_impact_analysis(self, origin: str, depth: int = 2) -> Dict[str, object]:
        return self.kg.trace_impact_chain(origin, depth)

    def simulate_change_impact(self, hostname: str, action: str) -> Dict[str, object]:
        return self.twin.simulate_change(hostname, action)

    def get_sample_devices(self) -> List[Dict[str, object]]:
        return [
            {
                "hostname": "DEL-CORE-01",
                "vendor": "Cisco",
                "model": "IOS-XR",
                "role": "Core Router",
                "site": "DEL",
                "os_version": "7.5.3",
                "status": "healthy",
                "cpu": 32.0,
                "memory": 44.0,
                "password_encryption": True,
                "management_protocol": "ssh",
                "ntp_servers": ["10.0.0.10"],
                "ospf_enabled": True,
                "ospf_auth": True,
            },
            {
                "hostname": "MUM-EDGE-01",
                "vendor": "Juniper",
                "model": "MX480",
                "role": "Edge Router",
                "site": "MUM",
                "os_version": "20.4R3",
                "status": "warning",
                "cpu": 78.0,
                "memory": 72.0,
                "password_encryption": True,
                "management_protocol": "ssh",
                "ntp_servers": ["10.0.0.11"],
                "ospf_enabled": False,
                "ospf_auth": False,
            },
            {
                "hostname": "BLR-FW-01",
                "vendor": "Fortinet",
                "model": "FortiGate-600C",
                "role": "Firewall",
                "site": "BLR",
                "os_version": "7.2.0",
                "status": "critical",
                "cpu": 91.0,
                "memory": 87.0,
                "password_encryption": False,
                "management_protocol": "https",
                "ntp_servers": [],
                "ospf_enabled": False,
                "ospf_auth": False,
            },
            {
                "hostname": "HYD-LEAF-02",
                "vendor": "Arista",
                "model": "7280R",
                "role": "Leaf Switch",
                "site": "HYD",
                "os_version": "4.29.2F",
                "status": "healthy",
                "cpu": 28.0,
                "memory": 39.0,
                "password_encryption": True,
                "management_protocol": "ssh",
                "ntp_servers": ["10.0.0.12"],
                "ospf_enabled": False,
                "ospf_auth": False,
            },
        ]

    def get_sample_topology(self) -> Dict[str, List[Dict[str, object]]]:
        return {
            "interfaces": [
                {"device": "DEL-CORE-01", "interface_name": "Gig1/0/1", "utilization": 82.0, "packet_loss": 0.2},
                {"device": "MUM-EDGE-01", "interface_name": "Gig0/0/0", "utilization": 95.0, "packet_loss": 1.8},
                {"device": "BLR-FW-01", "interface_name": "Ethernet1/2", "utilization": 44.0, "packet_loss": 0.0},
                {"device": "HYD-LEAF-02", "interface_name": "Port-Channel10", "utilization": 61.0, "packet_loss": 0.1},
            ],
            "bgp_peers": [
                {"local_device": "DEL-CORE-01", "peer_ip": "192.168.100.1", "state": "Established", "prefixes_received": 850},
                {"local_device": "MUM-EDGE-01", "peer_ip": "192.168.200.1", "state": "Idle", "prefixes_received": 0},
                {"local_device": "BLR-FW-01", "peer_ip": "10.100.1.2", "state": "Established", "prefixes_received": 120},
            ],
            "links": [
                {"source_device": "DEL-CORE-01", "destination_device": "MUM-EDGE-01", "link_type": "mpls", "status": "up", "bandwidth_mbps": 1000.0},
                {"source_device": "DEL-CORE-01", "destination_device": "HYD-LEAF-02", "link_type": "evpn", "status": "up", "bandwidth_mbps": 10000.0},
                {"source_device": "BLR-FW-01", "destination_device": "MUM-EDGE-01", "link_type": "internet", "status": "warning", "bandwidth_mbps": 500.0},
            ],
        }

    def service_dependencies(self, dependencies: List[Dict[str, object]]) -> None:
        for dependency in dependencies:
            source = dependency.get("source")
            target = dependency.get("target")
            service = dependency.get("service", "service")
            if source and target:
                self.kg.add_node(source, "device")
                self.kg.add_node(target, "device")
                self.kg.add_relationship(source, target, service)
