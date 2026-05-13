from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any
import logging

from core.compliance_engine import ComplianceEngine
from core.digital_twin_engine import DigitalTwinEngine, DeviceState, TopologyLink
from core.incident_engine import IncidentEngine
from core.knowledge_graph import KnowledgeGraph
from core.nlp_engine import NLPEngine
from core.observability_engine import ObservabilityEngine
from core.rag_engine import KnowledgeDocument, RAGEngine
from core.self_healing_engine import RemediationAction, SelfHealingEngine
from core.state_manager import StateManager
from core.simulation_engine import SimulationEngine
from core.telemetry_engine import TelemetryEngine
from core.event_engine import EventEngine

logger = logging.getLogger(__name__)


@dataclass
class QueryRecord:
    query: str
    response: str
    source: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


class OperationsOrchestrator:
    """
    Orchestrates network operations engines for diagnostics, impact analysis, and AI workflows.
    Integrates both legacy analysis engines and new event-driven autonomous engines.
    """

    def __init__(self, documents: Optional[List[Dict[str, str]]] = None) -> None:
        logger.info("Initializing OperationsOrchestrator with all engines...")
        
        # Legacy analysis engines
        self.nlp = NLPEngine()
        self.rag = RAGEngine(documents or [])
        self.obs = ObservabilityEngine()
        self.incident = IncidentEngine()
        self.twin = DigitalTwinEngine()
        self.comp = ComplianceEngine()
        self.kg = KnowledgeGraph()
        self.self_heal = SelfHealingEngine()
        
        # New event-driven autonomous engines
        self.state = StateManager()
        self.simulator = SimulationEngine()
        self.telemetry = TelemetryEngine(self.simulator, self.state)
        self.events = EventEngine(self.state, self.telemetry)
        
        # Tracking
        self.query_history: List[QueryRecord] = []
        self.run_count = 0
        self.last_update = datetime.utcnow().isoformat()
        
        # Initialize all systems
        self._seed_default_documents()
        self._seed_knowledge_graph()
        self._initialize_service_topology()
        self.events.register_standard_handlers()
        
        logger.info("OperationsOrchestrator initialized successfully")

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

    def _initialize_service_topology(self) -> None:
        """Initialize enterprise service dependency topology."""
        services = {
            "Email Service": ["dc1-delhi", "dc1-mumbai"],
            "Finance Portal": ["dc1-delhi", "sw1-delhi", "fw-delhi"],
            "Customer Portal": ["dc2-delhi", "dc1-mumbai"],
            "Data Warehouse": ["dc1-delhi", "dc2-delhi"],
            "VoIP Service": ["rtr-delhi", "fw-delhi"],
            "Remote Access VPN": ["wan-delhi", "fw-delhi"],
            "Backup Service": ["dc2-delhi", "sw2-delhi"],
            "NTP/DNS": ["dc1-delhi", "rtr-delhi"],
        }

        for service, devices in services.items():
            self.state.register_service_dependency(service, devices)

        logger.info(f"Initialized {len(services)} service dependencies")

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

    # ═══════════════════════════════════════════════════════════════
    # AUTONOMOUS ORCHESTRATION CYCLE
    # ═══════════════════════════════════════════════════════════════

    def run_cycle(self) -> Dict[str, Any]:
        """
        Execute one operational orchestration cycle.
        This is the main event loop that drives autonomous workflows.
        """
        self.run_count += 1
        cycle_start = datetime.utcnow()

        try:
            # 1. SIMULATION STEP
            simulation_changes = self.simulator.step()

            # 2. COLLECT TELEMETRY
            telemetry = self.telemetry.collect_all_telemetry()

            # 3. DETECT ANOMALIES
            anomalies = self.telemetry.detect_anomalies()
            
            # 4. PROCESS ANOMALIES → EVENTS → INCIDENTS
            incident_ids = self.events.process_anomalies(anomalies)

            # 5. PROCESS PENDING EVENTS
            while True:
                event = self.state.dequeue_event()
                if not event:
                    break
                self.events.emit_event(event)

            # 6. UPDATE SERVICE IMPACT
            critical_devices = self.state.get_critical_devices()
            impact = self.state.calculate_service_impact(critical_devices)

            # 7. CALCULATE HEALTH METRICS
            health_metrics = self.telemetry.get_health_metrics()
            operational_summary = self.state.get_operational_summary()

            # 8. UPDATE TOPOLOGY STATE
            topology_state = {
                "devices": self.simulator.get_topology_summary(),
                "links": len(self.simulator.links),
                "critical_devices": critical_devices,
            }
            self.state.update_topology(topology_state)

            # 9. UPDATE DIGITAL TWIN
            for hostname, device in self.simulator.devices.items():
                dt_device = DeviceState(
                    hostname=hostname,
                    vendor=device.vendor,
                    model=device.model,
                    os_version=device.os_version,
                    status=device.status,
                    cpu=device.cpu,
                    memory=device.memory,
                    interfaces=device.interfaces,
                )
                self.twin.add_device(dt_device)

            cycle_duration = (datetime.utcnow() - cycle_start).total_seconds()
            self.last_update = datetime.utcnow().isoformat()

            return {
                "status": "success",
                "cycle": self.run_count,
                "duration_seconds": cycle_duration,
                "timestamp": self.last_update,
                "anomalies_detected": len(anomalies),
                "incidents_created": len(incident_ids),
                "critical_devices": len(critical_devices),
                "operational_summary": operational_summary,
            }

        except Exception as e:
            logger.error(f"Error in orchestration cycle: {e}", exc_info=True)
            return {
                "status": "error",
                "cycle": self.run_count,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            }

    def get_operational_status(self) -> Dict[str, Any]:
        """Get current operational status."""
        return {
            "timestamp": self.last_update,
            "cycle": self.run_count,
            "operational_summary": self.state.get_operational_summary(),
            "critical_devices": self.state.get_critical_devices(),
            "incidents": {
                "total": len(self.state.incidents),
                "by_status": {
                    status: len(self.state.get_incidents_by_status(status))
                    for status in ["new", "investigating", "resolved", "closed"]
                },
            },
            "topology": self.state.get_topology(),
        }

    def get_ai_context(self, query: str = "") -> Dict[str, Any]:
        """
        Get context for AI engines (for RCA, recommendations, etc.)
        This provides comprehensive operational state to AI engines.
        """
        current_incidents = self.state.get_incidents_by_status("new")
        critical_devices = self.state.get_critical_devices()

        context = {
            "query": query,
            "timestamp": datetime.utcnow().isoformat(),
            "operational_state": {
                "overall_health_score": self.state.global_operational_score,
                "critical_devices": critical_devices,
                "total_incidents": len(self.state.incidents),
                "open_incidents": len(current_incidents),
            },
            "recent_events": self.events.get_event_history(limit=20),
            "critical_incidents": [
                {
                    "id": inc["id"],
                    "title": inc["title"],
                    "severity": inc["severity"],
                    "affected_devices": inc.get("affected_devices", []),
                }
                for inc in current_incidents[:5]
            ],
            "telemetry": {
                device: {
                    "cpu": metrics.cpu,
                    "memory": metrics.memory,
                    "latency_ms": metrics.latency_ms,
                }
                for device, metrics in self.state.get_all_device_metrics().items()
            },
            "recent_anomalies": self.telemetry.detect_anomalies()[:10],
        }

        return context

    def export_orchestration_state(self) -> Dict[str, Any]:
        """Export complete orchestrator state."""
        return {
            "timestamp": self.last_update,
            "cycle": self.run_count,
            "state": self.state.export_state(),
            "telemetry": self.telemetry.export_telemetry_state(),
            "events": self.events.export_event_state(),
        }

    def get_topology(self) -> Dict[str, Any]:
        """Get network topology."""
        return {
            "devices": [
                {
                    "hostname": d.hostname,
                    "vendor": d.vendor,
                    "model": d.model,
                    "type": d.device_type,
                    "site": d.site,
                    "role": d.role,
                    "status": d.status,
                    "cpu": d.cpu,
                    "memory": d.memory,
                }
                for d in self.simulator.devices.values()
            ],
            "links": [
                {
                    "source": l.source,
                    "destination": l.destination,
                    "type": l.link_type,
                    "status": l.status,
                    "bandwidth_mbps": l.bandwidth_mbps,
                }
                for l in self.simulator.links
            ],
            "summary": self.simulator.get_topology_summary(),
        }

    def health_check(self) -> Dict[str, Any]:
        """Perform health check on orchestrator."""
        checks = {
            "state_manager": "ok" if self.state else "error",
            "simulator": "ok" if self.simulator and self.simulator.devices else "error",
            "telemetry": "ok" if self.telemetry else "error",
            "event_engine": "ok" if self.events else "error",
        }

        all_ok = all(v == "ok" for v in checks.values())

        return {
            "status": "healthy" if all_ok else "degraded",
            "timestamp": datetime.utcnow().isoformat(),
            "components": checks,
            "run_count": self.run_count,
            "devices": len(self.simulator.devices),
            "incidents": len(self.state.incidents),
        }


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
