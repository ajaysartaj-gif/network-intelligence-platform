from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import streamlit as st
from config import (
    MAX_CHAT_HISTORY,
    MAX_RESULTS_STORED,
    TTL_RESULTS_MINUTES,
    TTL_SIMULATION_MINUTES,
)


@dataclass
class DeviceMetrics:
    hostname: str
    cpu: float = 0.0
    memory: float = 0.0
    latency_ms: float = 0.0
    packet_loss_pct: float = 0.0
    bgp_sessions_up: int = 0
    bgp_sessions_down: int = 0
    ospf_neighbors: int = 0
    interface_errors: int = 0
    reachable: bool = True
    last_updated: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ServiceDependency:
    source: str
    target: str
    service: str
    status: str = "ok"


class SessionStateManager:
    """Manages session state lifecycle with automatic cleanup and TTL."""

    @staticmethod
    def cleanup():
        """Run on every rerun to clean expired data and limit memory."""
        now = datetime.utcnow()

        if "chat_msgs" in st.session_state:
            msgs = st.session_state.chat_msgs
            if len(msgs) > MAX_CHAT_HISTORY:
                st.session_state.chat_msgs = msgs[-MAX_CHAT_HISTORY:]

        if "twin_result_meta" in st.session_state:
            meta = st.session_state["twin_result_meta"]
            if isinstance(meta, dict) and "timestamp" in meta:
                ts = meta["timestamp"]
                if isinstance(ts, datetime):
                    if now - ts > timedelta(minutes=TTL_SIMULATION_MINUTES):
                        if "twin_result" in st.session_state:
                            del st.session_state["twin_result"]
                        del st.session_state["twin_result_meta"]

        if "rag_results" in st.session_state:
            st.session_state.rag_results = st.session_state.rag_results[:MAX_RESULTS_STORED]

        if "mdq_results" in st.session_state:
            st.session_state.mdq_results = st.session_state.mdq_results[-1:]

        temp_keys = ["_nlpf", "_mdqf", "_chgf", "_sample_q"]
        for key in temp_keys:
            if key in st.session_state:
                del st.session_state[key]

    @staticmethod
    def init_defaults():
        """Initialize session state defaults once per session."""
        defaults = {
            "workspace": "operations",
            "persona": "noc",
            "chat_msgs": [],
            "chat_hist": [],
            "kg_selected": None,
            "mdq_results": None,
            "nlp_results": None,
            "rag_results": [],
            "design_output": None,
            "auto_mode": "human",
            "user_role": "admin",
            "user_name": "engineer",
            "styles_loaded": False,
        }
        for key, default_val in defaults.items():
            if key not in st.session_state:
                st.session_state[key] = default_val

    @staticmethod
    def clear():
        """Clear all session state (for logout)."""
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        SessionStateManager.init_defaults()


class StateManager:
    """Persistent orchestrator state for devices, incidents, workflows, and services."""

    def __init__(self) -> None:
        self.device_metrics: Dict[str, DeviceMetrics] = {}
        self.incidents: Dict[str, Dict[str, Any]] = {}
        self.workflows: Dict[str, Dict[str, Any]] = {}
        self.service_dependencies: Dict[str, ServiceDependency] = {}
        self.compliance_status: Dict[str, Dict[str, Any]] = {}
        self.global_operational_score: float = 100.0

    def update_device_metrics(self, hostname: str, metrics: Any) -> None:
        if isinstance(metrics, dict):
            metrics = DeviceMetrics(**metrics)
        self.device_metrics[hostname] = metrics

    def get_all_device_metrics(self) -> Dict[str, DeviceMetrics]:
        return self.device_metrics

    def get_device_metrics(self, hostname: str) -> DeviceMetrics:
        return self.device_metrics.get(hostname, DeviceMetrics(hostname=hostname))

    def create_incident(
        self,
        title: str,
        description: str,
        affected_service: str,
        device: Optional[str] = None,
        incident_id: Optional[str] = None,
        impact: int = 1,
        urgency: int = 1,
        visibility: int = 1,
    ) -> str:
        from core.inccident_engine import IncidentEngine

        engine = IncidentEngine()
        incident_record = engine.create_incident(
            title=title,
            description=description,
            affected_service=affected_service,
            device=device,
            impact=impact,
            urgency=urgency,
            visibility=visibility,
        )
        if incident_id is not None:
            incident_record.incident_id = incident_id
        incident = {
            "id": incident_record.incident_id,
            "title": incident_record.title,
            "description": incident_record.description,
            "affected_service": incident_record.affected_service,
            "device": incident_record.device,
            "severity": incident_record.severity,
            "status": incident_record.status,
            "created_at": incident_record.created_at.isoformat(),
            "updated_at": incident_record.updated_at.isoformat(),
            "notes": [],
            "correlated_ids": incident_record.correlated_ids,
        }
        self.incidents[incident["id"]] = incident
        return incident["id"]

    def update_incident(self, incident_id: str, status: Optional[str] = None, note: Optional[str] = None) -> Optional[Dict[str, Any]]:
        incident = self.incidents.get(incident_id)
        if incident is None:
            return None
        if status is not None:
            incident["status"] = status
        if note is not None:
            incident.setdefault("notes", []).append({
                "timestamp": datetime.utcnow().isoformat(),
                "note": note,
            })
        incident["updated_at"] = datetime.utcnow().isoformat()
        return incident

    def get_all_incidents(self) -> Dict[str, Dict[str, Any]]:
        return self.incidents

    def get_incident(self, incident_id: str) -> Optional[Dict[str, Any]]:
        return self.incidents.get(incident_id)

    def get_incidents_by_status(self, status: str) -> List[Dict[str, Any]]:
        return [incident for incident in self.incidents.values() if incident.get("status") == status]

    def start_workflow(
        self,
        workflow_id: str,
        name: str,
        triggered_by: str,
        total_steps: int,
    ) -> None:
        self.workflows[workflow_id] = {
            "id": workflow_id,
            "name": name,
            "triggered_by": triggered_by,
            "total_steps": total_steps,
            "steps_completed": 0,
            "status": "running",
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "data": {},
        }

    def update_workflow(self, workflow_id: str, step_completed: bool = False, status: Optional[str] = None, data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        workflow = self.workflows.get(workflow_id)
        if workflow is None:
            return None
        if step_completed:
            workflow["steps_completed"] = min(workflow["total_steps"], workflow["steps_completed"] + 1)
        if status is not None:
            workflow["status"] = status
        if data is not None:
            workflow["data"].update(data)
        workflow["updated_at"] = datetime.utcnow().isoformat()
        return workflow

    def get_operational_summary(self) -> Dict[str, Any]:
        total_devices = len(self.device_metrics)
        critical_devices = len(self.get_critical_devices())
        active_incidents = len(self.get_incidents_by_status("new")) + len(self.get_incidents_by_status("investigating"))
        operational_score = max(0, 100 - critical_devices * 5 - active_incidents * 2)
        self.global_operational_score = operational_score
        return {
            "total_devices": total_devices,
            "critical_devices": critical_devices,
            "active_incidents": active_incidents,
            "operational_score": operational_score,
            "service_impact": self.calculate_service_impact(self.get_critical_devices()),
        }

    def get_critical_devices(self) -> List[str]:
        return [
            hostname
            for hostname, metrics in self.device_metrics.items()
            if metrics.cpu >= 90.0
            or metrics.memory >= 90.0
            or metrics.packet_loss_pct >= 5.0
            or not metrics.reachable
        ]

    def get_dependent_services(self, device_hostname: str) -> List[str]:
        impacted = []
        for dependency in self.service_dependencies.values():
            if dependency.source == device_hostname or dependency.target == device_hostname:
                impacted.append(dependency.service)
        return list(dict.fromkeys(impacted))

    def calculate_service_impact(self, affected_devices: List[str]) -> Dict[str, Any]:
        impacted_services = []
        for device in affected_devices:
            impacted_services.extend(self.get_dependent_services(device))
        impacted_services = list(dict.fromkeys(impacted_services))
        impact_score = min(100, len(impacted_services) * 10)
        return {
            "affected_devices": affected_devices,
            "impacted_services": impacted_services,
            "impact_score": impact_score,
        }

    def update_compliance_status(self, key: str, status: Dict[str, Any]) -> None:
        self.compliance_status[key] = status

    def export_state(self) -> Dict[str, Any]:
        return {
            "device_metrics": {hostname: metrics.to_dict() for hostname, metrics in self.device_metrics.items()},
            "incidents": {incident_id: incident.copy() for incident_id, incident in self.incidents.items()},
            "workflows": {wf_id: wf.copy() for wf_id, wf in self.workflows.items()},
            "service_dependencies": {svc: asdict(dep) for svc, dep in self.service_dependencies.items()},
            "compliance_status": self.compliance_status.copy(),
            "global_operational_score": self.global_operational_score,
        }
