from __future__ import annotations
from dataclasses import dataclass, field
import os
import time
from datetime import datetime
from typing import Dict, List, Optional, Any

# Live-only mode: do not seed any simulated topology / services.
LIVE_ONLY = os.environ.get("NETBRAIN_LIVE_ONLY", "1").strip().lower() not in ("0", "false", "no")
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

try:
    from config.netmiko_devices import load_device_catalog
except Exception:
    def load_device_catalog():
        return []

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
        device_catalog = load_device_catalog()
        self.telemetry = TelemetryEngine(self.simulator, self.state, device_catalog=device_catalog)
        self.events = EventEngine(self.state, self.telemetry)
        if device_catalog:
            logger.info(f"Live mode: loaded {len(device_catalog)} device(s) from catalog")
        else:
            logger.info("Live mode: no device catalog — using GNS3 / GitHub log sources only")
        
        # Tracking
        self.query_history: List[QueryRecord] = []
        self.run_count = 0
        self.last_update = datetime.utcnow().isoformat()
        self.current_demo: Optional[str] = None
        self.demo_scenarios = self._load_demo_scenarios()
        
        # Initialize all systems
        self._seed_default_documents()
        self._seed_knowledge_graph()
        self._initialize_service_topology()
        self.events.register_standard_handlers()
        
        logger.info("OperationsOrchestrator initialized successfully")

    def _load_demo_scenarios(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": "bgp_flapping",
                "label": "BGP Flapping",
                "description": "Simulate Delhi data center BGP instability with packet loss and service blast radius.",
                "workflow_steps": [
                    "BGP session instability",
                    "Packet loss escalation",
                    "WAN latency spike",
                    "Incident creation",
                    "AI RCA generation",
                ],
            },
            {
                "id": "wan_outage",
                "label": "WAN Outage",
                "description": "Simulate a Delhi WAN degradation affecting regional services and connectivity.",
                "workflow_steps": [
                    "WAN link degradation",
                    "Regional service impact",
                    "Incident creation",
                    "Executive alert",
                ],
            },
            {
                "id": "high_cpu_storm",
                "label": "High CPU Storm",
                "description": "Simulate a CPU and memory storm across Delhi infrastructure with auto-escalation.",
                "workflow_steps": [
                    "CPU spike",
                    "Memory pressure",
                    "Application degradation",
                    "Incident escalation",
                ],
            },
            {
                "id": "packet_loss_cascade",
                "label": "Packet Loss Cascade",
                "description": "Simulate packet drops that trigger interface degradation and BGP impact.",
                "workflow_steps": [
                    "Interface packet loss",
                    "BGP instability",
                    "Incident creation",
                    "Remediation recommendation",
                ],
            },
            {
                "id": "compliance_drift",
                "label": "Compliance Failure",
                "description": "Simulate a compliance drift event that raises a security and operational alert.",
                "workflow_steps": [
                    "Compliance drift",
                    "Config risk detected",
                    "Incident created",
                    "AI recommendation",
                ],
            },
            {
                "id": "service_dependency_failure",
                "label": "Service Dependency Failure",
                "description": "Simulate service blast radius from a critical Delhi device failure.",
                "workflow_steps": [
                    "Service dependency degradation",
                    "Service impact calculated",
                    "Incident created",
                    "Executive summary generated",
                ],
            },
        ]

    def get_demo_scenarios(self) -> List[Dict[str, Any]]:
        return self.demo_scenarios.copy()

    def launch_demo_scenario(self, scenario_id: str) -> Dict[str, Any]:
        scenario = next((s for s in self.demo_scenarios if s["id"] == scenario_id), None)
        if not scenario:
            return {"status": "error", "message": f"Scenario '{scenario_id}' not found"}

        self.current_demo = scenario_id
        workflow_id = f"demo-{scenario_id}-{int(time.time())}"
        self.state.start_workflow(
            workflow_id=workflow_id,
            name=scenario["label"],
            triggered_by="demo_mode",
            total_steps=len(scenario["workflow_steps"]),
        )

        self.events.emit_event({
            "type": "demo_started",
            "severity": "info",
            "source": "demo_mode",
            "description": scenario["description"],
            "data": {"scenario_id": scenario_id},
        })

        self._inject_demo_scenario(scenario_id)

        cycle_results: List[Dict[str, Any]] = []
        for step_index in range(3):
            result = self.run_cycle()
            self.state.update_workflow(
                workflow_id,
                step_completed=True,
                data={"step": step_index + 1, "cycle_result": result},
            )
            cycle_results.append(result)

        self.state.update_workflow(workflow_id, status="completed", data={"completed_at": datetime.utcnow().isoformat()})

        return {
            "status": "success",
            "scenario": scenario,
            "workflow_id": workflow_id,
            "cycle_results": cycle_results,
            "event_history": self.events.get_event_history(limit=15),
        }

    def _inject_demo_scenario(self, scenario_id: str) -> None:
        def _find_device(hostname: str):
            return self.simulator.get_device(hostname)

        def _find_link(source: str, destination: str):
            return next(
                (link for link in self.simulator.links if link.source == source and link.destination == destination),
                None,
            )

        if scenario_id == "bgp_flapping":
            target = _find_device("rtr-delhi") or _find_device("dc1-delhi")
            if target:
                target.cpu = 92.0
                target.memory = 76.0
                target.status = "warning"
                if not target.bgp_sessions:
                    target.bgp_sessions = [{"peer_ip": "192.168.254.1", "peer_asn": target.bgp_asn or 65000, "state": "Idle"}]
                for session in target.bgp_sessions:
                    session["state"] = "Idle" if session.get("state") == "Established" else "Established"
                self.telemetry.baseline_metrics[target.hostname]["packet_loss_pct"] = 6.5
                self.telemetry.baseline_metrics[target.hostname]["latency_ms"] = 120.0

            link = _find_link("dc1-delhi", "dc1-mumbai")
            if link:
                link.status = "warning"
                link.current_latency_ms = 180.0

            self.events.emit_event({
                "type": "bgp_flap_detected",
                "severity": "critical",
                "source": "demo_mode",
                "description": "Delhi BGP session became unstable under packet loss.",
                "data": {"device": target.hostname if target else "rtr-delhi"},
            })

        elif scenario_id == "wan_outage":
            wan_device = _find_device("wan-delhi")
            if wan_device:
                wan_device.cpu = 68.0
                wan_device.memory = 61.0
                wan_device.status = "warning"
                self.telemetry.baseline_metrics[wan_device.hostname]["latency_ms"] = 210.0
                self.telemetry.baseline_metrics[wan_device.hostname]["packet_loss_pct"] = 8.2

            for link in self.simulator.links:
                if "wan-delhi" in {link.source, link.destination}:
                    link.status = "down"
                    link.current_latency_ms = 250.0

            impacted = self.state.get_dependent_services("wan-delhi")
            for svc in impacted:
                if svc in self.state.service_dependencies:
                    self.state.service_dependencies[svc].status = "degraded"

            self.events.emit_event({
                "type": "wan_degradation_detected",
                "severity": "high",
                "source": "demo_mode",
                "description": "Delhi WAN link outage causing regional service degradation.",
                "data": {"device": "wan-delhi", "impacted_services": impacted},
            })

        elif scenario_id == "high_cpu_storm":
            for device in self.simulator.devices.values():
                if device.site == "delhi":
                    device.cpu = min(99.0, device.cpu + 30.0)
                    device.memory = min(96.0, device.memory + 25.0)
                    device.status = "critical"
                    self.telemetry.baseline_metrics[device.hostname]["latency_ms"] = self.telemetry.baseline_metrics[device.hostname].get("latency_ms", 10) + 20.0

            self.events.emit_event({
                "type": "cpu_spike_detected",
                "severity": "critical",
                "source": "demo_mode",
                "description": "High CPU storm in Delhi datacenter affecting core infrastructure.",
                "data": {"site": "delhi"},
            })

        elif scenario_id == "packet_loss_cascade":
            target = _find_device("fw-delhi") or _find_device("sw1-delhi")
            if target:
                self.telemetry.baseline_metrics[target.hostname]["packet_loss_pct"] = 12.0
                self.telemetry.baseline_metrics[target.hostname]["latency_ms"] = 140.0
                target.status = "warning"
                target.cpu = min(95.0, target.cpu + 18.0)

            self.events.emit_event({
                "type": "packet_loss_detected",
                "severity": "high",
                "source": "demo_mode",
                "description": "Packet loss cascade observed on Delhi firewall.",
                "data": {"device": target.hostname if target else "fw-delhi"},
            })

        elif scenario_id == "compliance_drift":
            self.state.update_compliance_status(
                "compliance-drift-delhi",
                {
                    "status": "degraded",
                    "description": "Configuration drift detected on Delhi security and network infrastructure.",
                    "risk": "high",
                },
            )
            self.events.emit_event({
                "type": "incident_created",
                "severity": "high",
                "source": "demo_mode",
                "description": "Compliance drift triggered a security alert.",
                "data": {"issue": "compliance_drift"},
            })

        elif scenario_id == "service_dependency_failure":
            device = _find_device("dc1-delhi")
            if device:
                device.status = "critical"
                device.cpu = 94.0
                device.memory = 82.0
                self.telemetry.baseline_metrics[device.hostname]["latency_ms"] = 130.0
                self.telemetry.baseline_metrics[device.hostname]["packet_loss_pct"] = 7.5

            impacted = self.state.get_dependent_services(device.hostname if device else "dc1-delhi")
            for svc in impacted:
                if svc in self.state.service_dependencies:
                    self.state.service_dependencies[svc].status = "down"

            self.events.emit_event({
                "type": "service_impact_calculated",
                "severity": "critical",
                "source": "demo_mode",
                "description": "Service dependency failure from Delhi data center node.",
                "data": {"impacted_services": impacted},
            })

        else:
            self.events.emit_event({
                "type": "demo_generic",
                "severity": "info",
                "source": "demo_mode",
                "description": f"Running demo scenario {scenario_id}.",
            })

    def generate_operational_ai_summary(self) -> Dict[str, Any]:
        incidents = self.state.get_all_incidents()
        critical_incidents = [inc for inc in incidents.values() if inc["severity"] in {"critical", "high"}]
        critical_devices = self.state.get_critical_devices()
        score = self.state.global_operational_score
        service_impact = self.state.calculate_service_impact(critical_devices)

        # Get current simulation stage for context
        current_stage = self.simulator.workflow_stage
        workflow_context = {
            0: "Network operating normally with stable BGP and WAN connectivity.",
            1: "Packet loss detected on WAN edge affecting link quality.",
            2: "WAN latency spike causing routing performance degradation.",
            3: "BGP neighbor instability leading to routing convergence issues.",
            4: "Voice traffic experiencing jitter and MOS degradation.",
            5: "Critical incident active with multiple services impacted."
        }

        if critical_incidents:
            incident = critical_incidents[0]
            affected_devices = incident.get("affected_devices", [])
            impacted_services = service_impact.get("impacted_services", [])
            impacted_text = ", ".join(impacted_services) if impacted_services else "downstream services"
            device_text = ", ".join(affected_devices) if affected_devices else "core infrastructure"
            
            if current_stage == 1:
                root_cause = f"Packet loss on WAN edge router {device_text} is causing interface utilization spikes and link quality degradation."
                executive = f"Packet loss detected on WAN circuits affecting {impacted_text}. Immediate investigation required to prevent BGP instability."
                recommendation = "Validate WAN circuit quality, check for interface errors, and monitor for BGP adjacency flaps."
            elif current_stage == 2:
                root_cause = f"WAN latency increase from {device_text} is causing routing protocol timeouts and path selection issues."
                executive = f"WAN latency spike impacting {impacted_text} with elevated packet loss. BGP sessions at risk of flapping."
                recommendation = "Reroute traffic via secondary WAN paths and validate MPLS provider performance."
            elif current_stage == 3:
                root_cause = f"BGP neighbor instability on {device_text} causing routing table churn and service path changes."
                executive = f"BGP adjacency flaps affecting {impacted_text}. Voice and data services experiencing intermittent connectivity."
                recommendation = "Reset BGP peering sessions, validate route policies, and stabilize routing convergence."
            elif current_stage == 4:
                root_cause = f"Voice traffic degradation due to routing instability on {device_text} with elevated jitter and latency."
                executive = f"Voice services experiencing MOS degradation affecting {impacted_text}. Critical business communications impacted."
                recommendation = "Prioritize voice traffic QoS, stabilize BGP routing, and validate WAN circuit performance."
            elif current_stage == 5:
                root_cause = f"Critical incident: WAN outage on {device_text} causing complete service disruption for {impacted_text}."
                executive = f"Critical network incident active. Multiple services down affecting business operations. Executive escalation required."
                recommendation = "Activate disaster recovery procedures, failover to backup WAN circuits, and engage vendor support."
            else:
                root_cause = f"{incident['title']} on {device_text} is causing service impact to {impacted_text}."
                executive = f"Critical incident '{incident['title']}' is active. Impact analysis shows {impacted_text} are degraded."
                recommendation = "Review BGP neighbor state, validate WAN circuit stability, and restore service paths."
        else:
            root_cause = workflow_context.get(current_stage, "Network is stable with no critical incidents detected.")
            executive = "Operational metrics are healthy and no active outages are present. Continue monitoring core BGP, WAN, and service dependencies."
            recommendation = "Maintain current automation posture and verify SLAs on the next maintenance window."

        return {
            "root_cause": root_cause,
            "executive_summary": executive,
            "recommendation": recommendation,
            "service_impact": service_impact,
            "critical_incidents": [inc["title"] for inc in critical_incidents[:3]],
            "health_score": score,
            "workflow_stage": current_stage,
        }

    def get_demo_events(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self.events.get_event_history(limit=limit)

    def get_demo_status(self) -> Dict[str, Any]:
        return {
            "current_demo": self.current_demo,
            "health_score": self.state.global_operational_score,
            "active_workflows": [wf.name for wf in self.state.get_active_workflows()],
            "pending_events": self.state.get_pending_events(),
        }

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
        # In live-only mode, the knowledge graph is built from REAL devices as
        # they are discovered from the logs — do not seed fake topology.
        if LIVE_ONLY:
            return
        # Seed basic network topology relationships (demo mode only)
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
        # In live-only mode there are no simulated services/sites.
        if LIVE_ONLY:
            logger.info("Live-only mode: skipping simulated service topology")
            return
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
            # 1. LIVE TELEMETRY (simulation disabled — real GNS3 / catalog only)
            if LIVE_ONLY:
                simulation_changes = {"anomalies": []}
            else:
                simulation_changes = self.simulator.step()

            # 2. COLLECT TELEMETRY
            telemetry = self.telemetry.collect_all_telemetry()

            # 3. DETECT ANOMALIES
            telemetry_anomalies = self.telemetry.detect_anomalies()
            simulation_anomalies = (
                [] if LIVE_ONLY else simulation_changes.get("anomalies", [])
            )
            all_anomalies = telemetry_anomalies + simulation_anomalies
            
            # 4. PROCESS ANOMALIES → EVENTS → INCIDENTS
            incident_ids = self.events.process_anomalies(all_anomalies)

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
            if LIVE_ONLY:
                live_metrics = self.state.get_all_device_metrics()
                topology_state = {
                    "devices": {
                        "total_devices": len(live_metrics),
                        "device_types": {},
                    },
                    "links": 0,
                    "critical_devices": critical_devices,
                    "mode": "live",
                }
            else:
                topology_state = {
                    "devices": self.simulator.get_topology_summary(),
                    "links": len(self.simulator.links),
                    "critical_devices": critical_devices,
                    "mode": "simulation",
                }
            self.state.update_topology(topology_state)

            # 9. UPDATE DIGITAL TWIN (live metrics only in live mode)
            if LIVE_ONLY:
                for hostname, metrics in live_metrics.items():
                    dt_device = DeviceState(
                        hostname=hostname,
                        vendor="Cisco",
                        model="GNS3",
                        os_version="",
                        status="healthy" if getattr(metrics, "reachable", True) else "critical",
                        cpu=getattr(metrics, "cpu", 0.0),
                        memory=getattr(metrics, "memory", 0.0),
                        interfaces=[],
                    )
                    self.twin.add_device(dt_device)
            else:
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
                "anomalies_detected": len(all_anomalies),
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

    # ── Autonomic self-management (additive; does not change run_cycle) ───────
    def autonomic_cycle(self, candidates: Optional[List[Any]] = None) -> Dict[str, Any]:
        """
        Run one SELF-MANAGED operational cycle: the normal run_cycle() wrapped in
        the MAPE-K controller (monitor→analyze→plan→execute→verify→learn). The
        controller never pushes a network change itself — it authorises and
        recommends; every change still flows through the approval-gated path.
        Falls back to a plain run_cycle() if the autonomy layer is unavailable.
        """
        try:
            from core.intelligence.autonomy import get_controller
            return get_controller().governed_run(self.run_cycle, candidates=candidates)
        except Exception as exc:
            logger.debug(f"autonomic_cycle falling back to run_cycle: {exc}")
            return {"cycle": self.run_cycle(), "governance": {"error": str(exc)}}

    def authorize_change(self, intent: str, device: str, protocol: str = "",
                         site: str = "", operator: str = "") -> Dict[str, Any]:
        """
        The single safety gate any change path can call BEFORE applying config.
        Returns a plain dict {verdict, reasons, risk, level, requires_approval}.
        Defaults to requiring approval if the autonomy layer is unavailable.
        """
        try:
            from core.intelligence.autonomy import authorize, Action
            d = authorize(Action(kind="config_change", intent=intent, device=device,
                                 protocol=protocol, site=site, operator=operator))
            return {"verdict": d.verdict.value, "reasons": d.reasons,
                    "risk": d.risk, "level": d.level.name,
                    "requires_approval": d.requires_approval, "allowed": d.allowed}
        except Exception as exc:
            return {"verdict": "gate", "reasons": [f"autonomy layer unavailable: {exc}"],
                    "risk": 0.0, "level": "observe", "requires_approval": True,
                    "allowed": False}

    def autonomy_report(self) -> Dict[str, Any]:
        try:
            from core.intelligence.autonomy import get_controller
            return get_controller().report()
        except Exception as exc:
            return {"error": str(exc)}

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


    def service_dependencies(self, dependencies: List[Dict[str, object]]) -> None:
        for dependency in dependencies:
            source = dependency.get("source")
            target = dependency.get("target")
            service = dependency.get("service", "service")
            if source and target:
                self.kg.add_node(source, "device")
                self.kg.add_node(target, "device")
                self.kg.add_relationship(source, target, service)
