"""
Centralized operational state manager for all engines.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional, Any
import json


@dataclass
class DeviceMetrics:
    """Real-time device performance metrics."""
    hostname: str
    cpu: float = 0.0
    memory: float = 0.0
    latency_ms: float = 0.0
    packet_loss_pct: float = 0.0
    interface_errors: int = 0
    bgp_sessions_up: int = 0
    bgp_sessions_down: int = 0
    ospf_neighbors: int = 0
    last_updated: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class ServiceDependency:
    """Service dependency mapping."""
    service: str
    depends_on: List[str] = field(default_factory=list)
    status: str = "healthy"
    affected_by: List[str] = field(default_factory=list)


@dataclass
class WorkflowState:
    """Track operational workflows."""
    workflow_id: str
    name: str
    status: str
    triggered_by: str
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    steps_completed: int = 0
    total_steps: int = 0
    data: Dict[str, Any] = field(default_factory=dict)


class StateManager:
    """
    Centralized operational state management.
    All engines should consume and update through this manager.
    """

    def __init__(self):
        """Initialize state manager."""
        self.device_metrics: Dict[str, DeviceMetrics] = {}
        self.incidents: Dict[str, Dict[str, Any]] = {}
        self.service_dependencies: Dict[str, ServiceDependency] = {}
        self.topology_state: Dict[str, Any] = {}
        self.telemetry_history: Dict[str, List[Dict[str, Any]]] = {}
        self.active_workflows: Dict[str, WorkflowState] = {}
        self.compliance_status: Dict[str, Dict[str, Any]] = {}
        self.event_queue: List[Dict[str, Any]] = []
        self.global_operational_score: float = 100.0
        self.last_updated: str = datetime.utcnow().isoformat()

    # ═══════════════════════════════════════════════════════════════
    # DEVICE METRICS
    # ═══════════════════════════════════════════════════════════════

    def update_device_metrics(self, hostname: str, metrics: DeviceMetrics) -> None:
        """Update device metrics."""
        self.device_metrics[hostname] = metrics
        self.last_updated = datetime.utcnow().isoformat()
        self._add_to_history(hostname, asdict(metrics))

    def get_device_metrics(self, hostname: str) -> Optional[DeviceMetrics]:
        """Get device metrics."""
        return self.device_metrics.get(hostname)

    def get_all_device_metrics(self) -> Dict[str, DeviceMetrics]:
        """Get all device metrics."""
        return self.device_metrics.copy()

    def get_critical_devices(self) -> List[str]:
        """Get list of devices with critical metrics."""
        critical = []
        for hostname, metrics in self.device_metrics.items():
            if (
                metrics.cpu >= 90.0
                or metrics.memory >= 90.0
                or metrics.packet_loss_pct >= 5.0
                or metrics.latency_ms > 100.0
            ):
                critical.append(hostname)
        return critical

    # ═══════════════════════════════════════════════════════════════
    # INCIDENT STATE
    # ═══════════════════════════════════════════════════════════════

    def create_incident(
        self,
        incident_id: str,
        title: str,
        description: str,
        severity: str,
        affected_devices: List[str],
        affected_services: List[str],
    ) -> None:
        """Create incident in state."""
        self.incidents[incident_id] = {
            "id": incident_id,
            "title": title,
            "description": description,
            "severity": severity,
            "status": "new",
            "affected_devices": affected_devices,
            "affected_services": affected_services,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "timeline": [
                {
                    "timestamp": datetime.utcnow().isoformat(),
                    "note": "Incident opened by autonomous event engine.",
                }
            ],
        }

    def update_incident(
        self, incident_id: str, status: str = None, note: str = None
    ) -> None:
        """Update incident status."""
        if incident_id in self.incidents:
            if status:
                self.incidents[incident_id]["status"] = status
            if note:
                self.incidents[incident_id]["timeline"].append(
                    {
                        "timestamp": datetime.utcnow().isoformat(),
                        "note": note,
                    }
                )
            self.incidents[incident_id]["updated_at"] = datetime.utcnow().isoformat()

    def get_incident(self, incident_id: str) -> Optional[Dict[str, Any]]:
        """Get incident details."""
        return self.incidents.get(incident_id)

    def get_all_incidents(self) -> Dict[str, Dict[str, Any]]:
        """Get all incidents."""
        return self.incidents.copy()

    def get_incidents_by_status(self, status: str) -> List[Dict[str, Any]]:
        """Get incidents by status."""
        return [
            inc for inc in self.incidents.values() if inc["status"] == status
        ]

    # ═══════════════════════════════════════════════════════════════
    # SERVICE DEPENDENCIES
    # ═══════════════════════════════════════════════════════════════

    def register_service_dependency(
        self,
        service: str,
        depends_on: List[str],
    ) -> None:
        """Register service dependency."""
        self.service_dependencies[service] = ServiceDependency(
            service=service,
            depends_on=depends_on,
            status="healthy",
        )

    def get_service_status(self, service: str) -> str:
        """Get service status."""
        if service in self.service_dependencies:
            return self.service_dependencies[service].status
        return "unknown"

    def get_dependent_services(self, device: str) -> List[str]:
        """Get services that depend on this device."""
        dependent = []
        for svc, dep in self.service_dependencies.items():
            if device in dep.depends_on:
                dependent.append(svc)
        return dependent

    def calculate_service_impact(self, failed_devices: List[str]) -> Dict[str, Any]:
        """Calculate impact of device failures on services."""
        impacted_services = []
        for device in failed_devices:
            impacted_services.extend(self.get_dependent_services(device))

        return {
            "failed_devices": failed_devices,
            "impacted_services": list(set(impacted_services)),
            "impact_level": (
                "critical" if len(impacted_services) > 5
                else "high" if len(impacted_services) > 2
                else "medium" if impacted_services else "low"
            ),
        }

    # ═══════════════════════════════════════════════════════════════
    # TOPOLOGY STATE
    # ═══════════════════════════════════════════════════════════════

    def update_topology(self, topology: Dict[str, Any]) -> None:
        """Update topology state."""
        self.topology_state = topology
        self.last_updated = datetime.utcnow().isoformat()

    def get_topology(self) -> Dict[str, Any]:
        """Get current topology."""
        return self.topology_state.copy()

    # ═══════════════════════════════════════════════════════════════
    # TELEMETRY HISTORY
    # ═══════════════════════════════════════════════════════════════

    def _add_to_history(self, hostname: str, metrics: Dict[str, Any]) -> None:
        """Add metrics to history."""
        if hostname not in self.telemetry_history:
            self.telemetry_history[hostname] = []
        self.telemetry_history[hostname].append(metrics)
        # Keep only last 1000 samples per device
        if len(self.telemetry_history[hostname]) > 1000:
            self.telemetry_history[hostname] = self.telemetry_history[hostname][-1000:]

    def get_telemetry_history(self, hostname: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get telemetry history for device."""
        history = self.telemetry_history.get(hostname, [])
        return history[-limit:]

    # ═══════════════════════════════════════════════════════════════
    # WORKFLOWS
    # ═══════════════════════════════════════════════════════════════

    def start_workflow(
        self,
        workflow_id: str,
        name: str,
        triggered_by: str,
        total_steps: int,
    ) -> None:
        """Start a workflow."""
        self.active_workflows[workflow_id] = WorkflowState(
            workflow_id=workflow_id,
            name=name,
            status="running",
            triggered_by=triggered_by,
            total_steps=total_steps,
        )

    def update_workflow(
        self,
        workflow_id: str,
        status: str = None,
        step_completed: bool = False,
        data: Dict[str, Any] = None,
    ) -> None:
        """Update workflow state."""
        if workflow_id in self.active_workflows:
            workflow = self.active_workflows[workflow_id]
            if status:
                workflow.status = status
            if step_completed:
                workflow.steps_completed += 1
            if data:
                workflow.data.update(data)

    def get_workflow(self, workflow_id: str) -> Optional[WorkflowState]:
        """Get workflow state."""
        return self.active_workflows.get(workflow_id)

    def get_active_workflows(self) -> List[WorkflowState]:
        """Get all active workflows."""
        return list(self.active_workflows.values())

    # ═══════════════════════════════════════════════════════════════
    # COMPLIANCE STATE
    # ═══════════════════════════════════════════════════════════════

    def update_compliance_status(
        self, compliance_id: str, status: Dict[str, Any]
    ) -> None:
        """Update compliance status."""
        self.compliance_status[compliance_id] = {
            "id": compliance_id,
            **status,
            "updated_at": datetime.utcnow().isoformat(),
        }

    def get_compliance_status(self, compliance_id: str) -> Optional[Dict[str, Any]]:
        """Get compliance status."""
        return self.compliance_status.get(compliance_id)

    # ═══════════════════════════════════════════════════════════════
    # EVENT QUEUE
    # ═══════════════════════════════════════════════════════════════

    def enqueue_event(
        self,
        event_type: str,
        severity: str,
        source: str,
        description: str,
        data: Dict[str, Any] = None,
    ) -> str:
        """Enqueue an operational event."""
        event_id = f"EVT-{int(datetime.utcnow().timestamp())}"
        event = {
            "id": event_id,
            "type": event_type,
            "severity": severity,
            "source": source,
            "description": description,
            "data": data or {},
            "timestamp": datetime.utcnow().isoformat(),
        }
        self.event_queue.append(event)
        return event_id

    def dequeue_event(self) -> Optional[Dict[str, Any]]:
        """Get next event from queue."""
        if self.event_queue:
            return self.event_queue.pop(0)
        return None

    def get_pending_events(self) -> List[Dict[str, Any]]:
        """Get all pending events."""
        return self.event_queue.copy()

    # ═══════════════════════════════════════════════════════════════
    # OPERATIONAL SCORE
    # ═══════════════════════════════════════════════════════════════

    def calculate_operational_score(self) -> float:
        """Calculate overall operational health score."""
        score = 100.0

        # Deduct for critical devices
        critical_devices = self.get_critical_devices()
        score -= len(critical_devices) * 5

        # Deduct for incidents
        open_incidents = self.get_incidents_by_status("new")
        score -= len(open_incidents) * 3

        # Deduct for down services
        for svc_dep in self.service_dependencies.values():
            if svc_dep.status == "down":
                score -= 10
            elif svc_dep.status == "degraded":
                score -= 5

        self.global_operational_score = max(0.0, min(100.0, score))
        return self.global_operational_score

    def get_operational_summary(self) -> Dict[str, Any]:
        """Get operational summary."""
        return {
            "timestamp": self.last_updated,
            "operational_score": self.calculate_operational_score(),
            "total_devices": len(self.device_metrics),
            "critical_devices": len(self.get_critical_devices()),
            "incidents": {
                "total": len(self.incidents),
                "new": len(self.get_incidents_by_status("new")),
                "investigating": len(self.get_incidents_by_status("investigating")),
                "resolved": len(self.get_incidents_by_status("resolved")),
            },
            "services": {
                "total": len(self.service_dependencies),
                "healthy": sum(
                    1 for s in self.service_dependencies.values()
                    if s.status == "healthy"
                ),
                "degraded": sum(
                    1 for s in self.service_dependencies.values()
                    if s.status == "degraded"
                ),
                "down": sum(
                    1 for s in self.service_dependencies.values()
                    if s.status == "down"
                ),
            },
            "events_pending": len(self.event_queue),
            "workflows_active": len(self.active_workflows),
        }

    # ═══════════════════════════════════════════════════════════════
    # EXPORT & DEBUGGING
    # ═══════════════════════════════════════════════════════════════

    def export_state(self) -> Dict[str, Any]:
        """Export complete state for debugging/persistence."""
        return {
            "timestamp": self.last_updated,
            "device_metrics": {k: asdict(v) for k, v in self.device_metrics.items()},
            "incidents": self.incidents.copy(),
            "service_dependencies": {
                k: asdict(v) for k, v in self.service_dependencies.items()
            },
            "topology": self.topology_state.copy(),
            "compliance": self.compliance_status.copy(),
            "operational_summary": self.get_operational_summary(),
        }

    def reset(self) -> None:
        """Reset all state."""
        self.__init__()
