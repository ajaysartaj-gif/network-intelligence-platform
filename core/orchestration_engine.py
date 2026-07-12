from __future__ import annotations
from dataclasses import dataclass, field
import time
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

        # Initialize all systems
        self._seed_default_documents()
        self._seed_knowledge_graph()
        self._initialize_service_topology()
        self.events.register_standard_handlers()
        
        logger.info("OperationsOrchestrator initialized successfully")

    def generate_operational_ai_summary(self) -> Dict[str, Any]:
        """Summarizes REAL incidents/critical devices only — no fabricated
        incident narrative (WAN packet loss / BGP flap / voice degradation
        stage-text) is ever generated regardless of what's actually
        happening on real equipment."""
        incidents = self.state.get_all_incidents()
        critical_incidents = [inc for inc in incidents.values() if inc["severity"] in {"critical", "high"}]
        critical_devices = self.state.get_critical_devices()
        score = self.state.global_operational_score
        service_impact = self.state.calculate_service_impact(critical_devices)

        if critical_incidents:
            incident = critical_incidents[0]
            affected_devices = incident.get("affected_devices", [])
            impacted_services = service_impact.get("impacted_services", [])
            impacted_text = ", ".join(impacted_services) if impacted_services else "downstream services"
            device_text = ", ".join(affected_devices) if affected_devices else "core infrastructure"
            root_cause = f"{incident['title']} on {device_text} is causing service impact to {impacted_text}."
            executive = f"Critical incident '{incident['title']}' is active. Impact analysis shows {impacted_text} are degraded."
            recommendation = "Review BGP neighbor state, validate WAN circuit stability, and restore service paths."
        else:
            root_cause = "Network is stable with no critical incidents detected."
            executive = "Operational metrics are healthy and no active outages are present. Continue monitoring core BGP, WAN, and service dependencies."
            recommendation = "Maintain current automation posture and verify SLAs on the next maintenance window."

        return {
            "root_cause": root_cause,
            "executive_summary": executive,
            "recommendation": recommendation,
            "service_impact": service_impact,
            "critical_incidents": [inc["title"] for inc in critical_incidents[:3]],
            "health_score": score,
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
        # The knowledge graph is built exclusively from REAL devices as they
        # are discovered from real logs/GNS3/SSH — never seeded with fake
        # topology.
        return

    def _initialize_service_topology(self) -> None:
        """Service dependency topology is registered from real discovery
        only — no fabricated services/sites are ever seeded."""
        logger.info("Skipping service-topology seeding: real discovery only, no fabricated data.")
        return

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
            # 1. LIVE TELEMETRY (real GNS3 / catalog only — no simulation path)
            simulation_changes = {"anomalies": []}

            # 2. COLLECT TELEMETRY
            telemetry = self.telemetry.collect_all_telemetry()

            # 3. DETECT ANOMALIES
            telemetry_anomalies = self.telemetry.detect_anomalies()
            simulation_anomalies: List[Dict[str, Any]] = []
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

            # 8. UPDATE TOPOLOGY STATE (real discovery only)
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
            self.state.update_topology(topology_state)

            # 9. UPDATE DIGITAL TWIN (real device metrics only)
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

    def deliberate(self, question: str, options: List[Any],
                   goal: str = "", operator: str = "default") -> Dict[str, Any]:
        """
        Render a senior-architect-style JUDGMENT over a set of options: weighs
        tradeoffs, business value, risk, ethics (hard veto), second-order and
        long-term effects, reversibility and regret; returns an explained,
        confidence-bearing decision (still gated for safety before execution).
        """
        try:
            from core.intelligence.decision import get_deliberation_engine, DecisionContext
            from core.intelligence.decision.engine import _coerce_options
            ctx = DecisionContext(question=question, options=_coerce_options(options),
                                  goal=goal, operator=operator)
            return get_deliberation_engine().judge_dict(ctx)
        except Exception as exc:
            return {"error": str(exc), "chosen": None, "requires_human": True}

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
            # Not "does it hold fake data" (it never does anymore) — just
            # whether the container itself is wired up.
            "simulator": "ok" if self.simulator is not None else "error",
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
