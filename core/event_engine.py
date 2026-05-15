"""
Event engine for event-driven operational workflows.
"""

from __future__ import annotations
from typing import Dict, List, Any, Callable, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class EventHandler:
    """Event handler definition."""
    event_type: str
    handler_func: Callable[[Dict[str, Any]], Any]
    priority: int = 0
    enabled: bool = True


class EventEngine:
    """
    Event-driven workflow engine.
    Manages event workflows like:
    - Link Failure → Packet Loss → BGP Flap → Incident
    - CPU Spike → Memory Spike → Service Degradation → Alert
    """

    def __init__(self, state_manager, telemetry_engine=None):
        """Initialize event engine."""
        self.state = state_manager
        self.telemetry = telemetry_engine
        self.handlers: Dict[str, List[EventHandler]] = {}
        self.workflow_chains: Dict[str, List[str]] = {}
        self.event_history: List[Dict[str, Any]] = []
        # Maps signature → incident_id so we can check if the incident resolved
        self.active_incident_signatures: Dict[str, str] = {}
        self._emit_depth: int = 0  # Recursion guard for emit_event
        self._initialize_workflow_chains()

    # ═══════════════════════════════════════════════════════════════
    # WORKFLOW CHAIN DEFINITIONS
    # ═══════════════════════════════════════════════════════════════

    def _initialize_workflow_chains(self) -> None:
        """Initialize standard event-driven workflow chains."""
        # Link failure cascade
        self.workflow_chains["link_failure"] = [
            "link_failure",
            "packet_loss_detected",
            "bgp_flap_detected",
            "incident_created",
            "service_impact_calculated",
            "rca_triggered",
            "remediation_recommended",
        ]

        # CPU spike cascade
        self.workflow_chains["cpu_spike"] = [
            "cpu_spike_detected",
            "memory_pressure_detected",
            "application_degradation",
            "incident_created",
            "alert_escalated",
        ]

        # Interface flap cascade
        self.workflow_chains["interface_flap"] = [
            "interface_flap_detected",
            "packet_loss_detected",
            "incident_created",
            "auto_investigation_triggered",
        ]

        # WAN degradation cascade
        self.workflow_chains["wan_degradation"] = [
            "latency_spike_detected",
            "wan_degradation_detected",
            "regional_impact_calculated",
            "incident_created",
        ]

    # ═══════════════════════════════════════════════════════════════
    # EVENT HANDLER REGISTRATION
    # ═══════════════════════════════════════════════════════════════

    def register_handler(
        self,
        event_type: str,
        handler_func: Callable[[Dict[str, Any]], Any],
        priority: int = 0,
    ) -> None:
        """Register an event handler."""
        if event_type not in self.handlers:
            self.handlers[event_type] = []
        
        handler = EventHandler(
            event_type=event_type,
            handler_func=handler_func,
            priority=priority,
            enabled=True,
        )
        self.handlers[event_type].append(handler)
        # Sort by priority descending
        self.handlers[event_type].sort(key=lambda h: h.priority, reverse=True)

    # ═══════════════════════════════════════════════════════════════
    # EVENT EMISSION & PROCESSING
    # ═══════════════════════════════════════════════════════════════

    _MAX_EMIT_DEPTH = 8  # Prevent runaway recursive event chains

    def emit_event(self, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Emit an event and process all handlers.
        Returns list of downstream events triggered.
        """
        if self._emit_depth >= self._MAX_EMIT_DEPTH:
            return []

        event_type = event.get("type")
        if not event_type:
            return []

        # Record in history (cap to avoid unbounded memory growth)
        event_record = {
            "id": f"EVT-{int(datetime.utcnow().timestamp())}",
            "type": event_type,
            "timestamp": datetime.utcnow().isoformat(),
            **event,
        }
        self.event_history.append(event_record)
        if len(self.event_history) > 500:
            self.event_history = self.event_history[-500:]

        # Execute handlers
        downstream_events = []
        handlers = self.handlers.get(event_type, [])

        for handler in handlers:
            if not handler.enabled:
                continue
            try:
                result = handler.handler_func(event_record)
                if isinstance(result, dict) and result.get("type"):
                    downstream_events.append(result)
                elif isinstance(result, list):
                    downstream_events.extend([e for e in result if isinstance(e, dict)])
            except Exception:
                pass

        # Process downstream events with depth tracking
        self._emit_depth += 1
        all_downstream = downstream_events.copy()
        for downstream in downstream_events:
            further_downstream = self.emit_event(downstream)
            all_downstream.extend(further_downstream)
        self._emit_depth -= 1

        return all_downstream

    # ═══════════════════════════════════════════════════════════════
    # ANOMALY TO INCIDENT WORKFLOW
    # ═══════════════════════════════════════════════════════════════

    def process_anomalies(self, anomalies: List[Dict[str, Any]]) -> List[str]:
        """Process detected anomalies and trigger workflows."""
        incident_ids = []
        grouped_anomalies = self._group_anomalies(anomalies)

        for device, group in grouped_anomalies.items():
            if not group:
                continue

            signature = self._build_incident_signature(device, group)
            if self._is_duplicate_incident(signature):
                continue

            # Emit raw anomaly events for correlation workflows
            for anomaly in group:
                event = self._anomaly_to_event(anomaly)
                if event:
                    self.emit_event(event)

            # Create one correlated incident per device/group
            correlated_anomaly = self._build_correlated_anomaly(group, device)
            if correlated_anomaly:
                incident_id = self._create_incident_from_anomaly(correlated_anomaly)
                # Register so we can detect when this incident resolves
                self._register_incident_signature(signature, incident_id)
                incident_ids.append(incident_id)
                self.emit_event({
                    "type": "incident_created",
                    "severity": correlated_anomaly.get("severity", "high"),
                    "source": "event_engine",
                    "description": f"Incident {incident_id} created for correlated failures on {device}.",
                    "data": {
                        "incident_id": incident_id,
                        "device": device,
                        "correlated_types": [a.get("type") for a in group],
                    },
                })

        return incident_ids

    def _anomaly_to_event(self, anomaly: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert an anomaly to an event."""
        atype = anomaly.get("type")
        device = anomaly.get("device", "unknown")
        severity = anomaly.get("severity", "medium")

        if atype == "cpu_spike":
            return {
                "type": "cpu_spike_detected",
                "severity": severity,
                "source": "telemetry_engine",
                "description": f"CPU spike on {device}: {anomaly.get('value', 'unknown')}%",
                "data": anomaly,
            }
        elif atype == "memory_exhaustion":
            return {
                "type": "memory_pressure_detected",
                "severity": severity,
                "source": "telemetry_engine",
                "description": f"Memory exhaustion on {device}: {anomaly.get('value', 'unknown')}%",
                "data": anomaly,
            }
        elif atype == "interface_flap":
            return {
                "type": "interface_flap_detected",
                "severity": severity,
                "source": "telemetry_engine",
                "description": f"Interface flap on {device}: {anomaly.get('interface', 'unknown')}",
                "data": anomaly,
            }
        elif atype == "interface_down":
            return {
                "type": "interface_down_detected",
                "severity": severity,
                "source": "telemetry_engine",
                "description": f"Interface down on {device} detected",
                "data": anomaly,
            }
        elif atype == "device_unreachable":
            return {
                "type": "device_unreachable_detected",
                "severity": severity,
                "source": "telemetry_engine",
                "description": f"Device unreachable: {device}",
                "data": anomaly,
            }
        elif atype == "packet_loss":
            return {
                "type": "packet_loss_detected",
                "severity": severity,
                "source": "telemetry_engine",
                "description": f"Packet loss on {device}: {anomaly.get('value', anomaly.get('packet_loss_pct', 'unknown'))}%",
                "data": anomaly,
            }
        elif atype == "latency_spike":
            return {
                "type": "latency_spike_detected",
                "severity": severity,
                "source": "telemetry_engine",
                "description": f"Latency spike on {device}: {anomaly.get('value', anomaly.get('latency_ms', 'unknown'))}ms",
                "data": anomaly,
            }
        elif atype == "bgp_instability":
            return {
                "type": "bgp_flap_detected",
                "severity": severity,
                "source": "telemetry_engine",
                "description": f"BGP instability on {device}: {anomaly.get('down_sessions', 0)} sessions down",
                "data": anomaly,
            }
        elif atype == "wan_degradation":
            return {
                "type": "wan_degradation_detected",
                "severity": severity,
                "source": "telemetry_engine",
                "description": f"WAN degradation: {anomaly.get('latency_ms', 'unknown')}ms latency",
                "data": anomaly,
            }
        elif atype == "voice_degradation":
            return {
                "type": "voice_degradation_detected",
                "severity": severity,
                "source": "telemetry_engine",
                "description": f"Voice traffic degradation: {anomaly.get('latency_ms', 'unknown')}ms latency affecting MOS scores",
                "data": anomaly,
            }
        elif atype == "critical_incident":
            return {
                "type": "critical_incident_detected",
                "severity": severity,
                "source": "telemetry_engine",
                "description": f"Critical incident triggered: {anomaly.get('description', 'Multiple services affected')}",
                "data": anomaly,
            }

        return None

    def _group_anomalies(self, anomalies: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Group anomalies by device for correlation."""
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for anomaly in anomalies:
            device = anomaly.get("device", "unknown") or "unknown"
            grouped.setdefault(device, []).append(anomaly)
        return grouped

    def _build_incident_signature(self, device: str, anomalies: List[Dict[str, Any]]) -> str:
        """Build a dedupe signature for correlated incidents."""
        anomaly_types = sorted({a.get("type", "unknown") for a in anomalies})
        return f"{device}:{','.join(anomaly_types)}"

    def _is_duplicate_incident(self, signature: str) -> bool:
        """
        Suppress duplicate incident creation while an open incident exists for
        the same signature. Allows new incidents once the previous one resolves.
        """
        if signature not in self.active_incident_signatures:
            return False

        incident_id = self.active_incident_signatures[signature]
        if incident_id:
            incident = self.state.get_incident(incident_id)
            if incident and incident["status"] in {"resolved", "closed"}:
                # Previous incident resolved — allow a new one
                del self.active_incident_signatures[signature]
                return False
        return True

    def _register_incident_signature(self, signature: str, incident_id: str) -> None:
        """Associate a newly-created incident_id with its signature."""
        self.active_incident_signatures[signature] = incident_id

    def _get_group_severity(self, anomalies: List[Dict[str, Any]]) -> str:
        """Return the highest severity found in a correlated anomaly group."""
        severity_rank = {"low": 1, "medium": 2, "high": 3, "critical": 4}
        highest = "low"
        for anomaly in anomalies:
            candidate = anomaly.get("severity", "medium")
            if severity_rank.get(candidate, 2) > severity_rank.get(highest, 1):
                highest = candidate
        return highest

    def _build_correlated_anomaly(self, anomalies: List[Dict[str, Any]], device: str) -> Dict[str, Any]:
        """Build a single correlated incident representation from an anomaly group."""
        types = sorted({a.get("type", "unknown") for a in anomalies})
        severity = self._get_group_severity(anomalies)
        impacted_services = self.state.calculate_service_impact([device]).get("impacted_services", [])
        description = (
            f"Correlated operational failure on {device}: "
            f"{', '.join(types)} detected. "
            f"Service impact calculated for {', '.join(impacted_services) or 'affected services'}.")

        return {
            "type": "operational_correlation",
            "severity": severity,
            "device": device,
            "description": description,
            "data": {
                "correlated_anomalies": anomalies,
                "impacted_services": impacted_services,
            },
        }

    def _create_incident_from_anomaly(self, anomaly: Dict[str, Any]) -> str:
        """Create incident from anomaly."""
        atype = anomaly.get("type")
        device = anomaly.get("device", "unknown")
        severity = anomaly.get("severity", "medium")

        title_map = {
            "cpu_spike": f"High CPU on {device}",
            "memory_exhaustion": f"Memory exhaustion on {device}",
            "interface_flap": f"Interface flap on {device}",
            "interface_down": f"Interface down on {device}",
            "device_unreachable": f"Device unreachable: {device}",
            "operational_correlation": f"Operational correlation failure on {device}",
            "packet_loss": f"Packet loss on {device}",
            "latency_spike": f"Latency spike on {device}",
            "bgp_instability": f"BGP instability on {device}",
            "wan_degradation": "WAN link degradation",
            "voice_degradation": f"Voice traffic degradation on {device}",
            "critical_incident": "Critical Network Incident",
        }

        title = title_map.get(atype, f"Network anomaly: {atype}")
        description = anomaly.get("description", f"Anomaly detected: {str(anomaly)}")

        # Use microsecond precision + device hash to guarantee uniqueness
        incident_id = (
            f"INC-{datetime.utcnow().strftime('%H%M%S%f')}"
            f"-{abs(hash(device)) % 9999:04d}"
        )
        
        # For critical incidents, get all affected devices
        if atype == "critical_incident":
            affected_devices = anomaly.get("devices", [device])
        else:
            affected_devices = [device] if device != "unknown" else []
        
        affected_services = self.state.calculate_service_impact(affected_devices).get("impacted_services", [])

        self.state.create_incident(
            incident_id=incident_id,
            title=title,
            description=description,
            severity=severity,
            affected_devices=affected_devices,
            affected_services=affected_services,
        )

        return incident_id

    # ═══════════════════════════════════════════════════════════════
    # STANDARD EVENT HANDLERS
    # ═══════════════════════════════════════════════════════════════

    def _handle_cpu_spike_detected(self, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Handle CPU spike event."""
        downstream = []
        
        # Check if memory is also high
        device = event.get("data", {}).get("device")
        if device:
            metrics = self.state.get_device_metrics(device)
            if metrics and metrics.memory > 80:
                downstream.append({
                    "type": "application_degradation",
                    "severity": "high",
                    "source": "event_engine",
                    "description": f"Application degradation on {device} (CPU+Memory)",
                    "data": {"device": device},
                })

        return downstream

    def _handle_interface_flap_detected(self, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Handle interface flap event."""
        downstream = []
        
        # Interface flaps often lead to packet loss
        downstream.append({
            "type": "packet_loss_detected",
            "severity": event.get("severity"),
            "source": "event_engine",
            "description": "Packet loss following interface flap",
            "data": event.get("data", {}),
        })

        return downstream

    def _handle_packet_loss_detected(self, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Handle packet loss event."""
        downstream = []
        
        # Packet loss can lead to BGP flaps
        downstream.append({
            "type": "bgp_flap_detected",
            "severity": "high",
            "source": "event_engine",
            "description": "BGP instability detected following packet loss",
            "data": event.get("data", {}),
        })

        return downstream

    def _handle_bgp_flap_detected(self, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Handle BGP flap event."""
        downstream = []
        
        # BGP flaps impact services
        downstream.append({
            "type": "service_impact_calculated",
            "severity": "high",
            "source": "event_engine",
            "description": "Service impact from BGP instability",
            "data": event.get("data", {}),
        })

        return downstream

    def _handle_wan_degradation_detected(self, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Handle WAN degradation event."""
        downstream = []
        
        # WAN degradation impacts regional connectivity
        downstream.append({
            "type": "regional_impact_calculated",
            "severity": "high",
            "source": "event_engine",
            "description": "Regional impact from WAN degradation",
            "data": event.get("data", {}),
        })

        return downstream

    def _handle_voice_degradation_detected(self, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Handle voice degradation event."""
        downstream = []
        
        # Voice degradation leads to service impact
        downstream.append({
            "type": "service_impact_calculated",
            "severity": "critical",
            "source": "event_engine",
            "description": "Voice service degradation impacting business communications",
            "data": event.get("data", {}),
        })

        return downstream

    def _handle_critical_incident_detected(self, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Handle critical incident detection."""
        downstream = []
        
        # Critical incident triggers executive alert
        downstream.append({
            "type": "executive_alert_triggered",
            "severity": "critical",
            "source": "event_engine",
            "description": "Executive alert generated for critical incident",
            "data": event.get("data", {}),
        })

        # Also trigger AI RCA
        downstream.append({
            "type": "ai_rca_triggered",
            "severity": "critical",
            "source": "event_engine",
            "description": "AI root cause analysis initiated for critical incident",
            "data": event.get("data", {}),
        })

        return downstream

    def _handle_interface_down_detected(self, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Handle interface down events and correlate failure modes."""
        downstream = []
        downstream.append({
            "type": "packet_loss_detected",
            "severity": "high",
            "source": "event_engine",
            "description": "Packet loss detected after interface down event",
            "data": event.get("data", {}),
        })
        downstream.append({
            "type": "service_impact_calculated",
            "severity": "critical",
            "source": "event_engine",
            "description": "Service impact computed from interface down event",
            "data": event.get("data", {}),
        })
        return downstream

    def _handle_device_unreachable_detected(self, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Handle device unreachable events."""
        downstream = []
        downstream.append({
            "type": "service_impact_calculated",
            "severity": "critical",
            "source": "event_engine",
            "description": "Service impact computed from unreachable device",
            "data": event.get("data", {}),
        })
        downstream.append({
            "type": "ai_rca_triggered",
            "severity": "critical",
            "source": "event_engine",
            "description": "AI RCA triggered for unreachable device",
            "data": event.get("data", {}),
        })
        return downstream

    def _handle_operational_correlation(self, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Handle correlated operational failures."""
        downstream = []
        downstream.append({
            "type": "service_impact_calculated",
            "severity": event.get("severity", "high"),
            "source": "event_engine",
            "description": "Service impact calculated from correlated operational failure",
            "data": event.get("data", {}),
        })
        downstream.append({
            "type": "rca_triggered",
            "severity": event.get("severity", "high"),
            "source": "event_engine",
            "description": "AI RCA triggered from correlated failure",
            "data": event.get("data", {}),
        })
        downstream.append({
            "type": "remediation_recommended",
            "severity": event.get("severity", "high"),
            "source": "event_engine",
            "description": "Remediation recommended for correlated failure",
            "data": event.get("data", {}),
        })
        return downstream

    def _handle_incident_created(self, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Handle incident creation to continue the workflow."""
        downstream = []
        downstream.append({
            "type": "service_impact_calculated",
            "severity": "high",
            "source": "event_engine",
            "description": "Calculating service blast radius for created incident",
            "data": event.get("data", {}),
        })
        downstream.append({
            "type": "rca_triggered",
            "severity": "high",
            "source": "event_engine",
            "description": "AI RCA triggered for incident",
            "data": event.get("data", {}),
        })
        downstream.append({
            "type": "remediation_recommended",
            "severity": "high",
            "source": "event_engine",
            "description": "Remediation recommendations generated",
            "data": event.get("data", {}),
        })
        return downstream

    # ═══════════════════════════════════════════════════════════════
    # REGISTER STANDARD HANDLERS
    # ═══════════════════════════════════════════════════════

    def register_standard_handlers(self) -> None:
        """Register all standard event handlers."""
        self.register_handler(
            "cpu_spike_detected",
            self._handle_cpu_spike_detected,
            priority=10,
        )
        self.register_handler(
            "interface_flap_detected",
            self._handle_interface_flap_detected,
            priority=10,
        )
        self.register_handler(
            "interface_down_detected",
            self._handle_interface_down_detected,
            priority=20,
        )
        self.register_handler(
            "device_unreachable_detected",
            self._handle_device_unreachable_detected,
            priority=20,
        )
        self.register_handler(
            "packet_loss_detected",
            self._handle_packet_loss_detected,
            priority=10,
        )
        self.register_handler(
            "bgp_flap_detected",
            self._handle_bgp_flap_detected,
            priority=10,
        )
        self.register_handler(
            "wan_degradation_detected",
            self._handle_wan_degradation_detected,
            priority=10,
        )
        self.register_handler(
            "voice_degradation_detected",
            self._handle_voice_degradation_detected,
            priority=10,
        )
        self.register_handler(
            "critical_incident_detected",
            self._handle_critical_incident_detected,
            priority=10,
        )
        self.register_handler(
            "operational_correlation",
            self._handle_operational_correlation,
            priority=20,
        )
        self.register_handler(
            "incident_created",
            self._handle_incident_created,
            priority=20,
        )

    # ═══════════════════════════════════════════════════════════════
    # DEBUGGING & MONITORING
    # ═══════════════════════════════════════════════════════════════

    def get_event_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent event history."""
        return self.event_history[-limit:]

    def get_workflow_status(self, workflow_type: str) -> Dict[str, int]:
        """Get count of events in a workflow chain."""
        if workflow_type not in self.workflow_chains:
            return {}

        chain = self.workflow_chains[workflow_type]
        return {
            stage: sum(
                1 for e in self.event_history if e.get("type") == stage
            )
            for stage in chain
        }

    def export_event_state(self) -> Dict[str, Any]:
        """Export complete event engine state."""
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "total_events": len(self.event_history),
            "event_history": self.event_history[-50:],  # Last 50 events
            "workflow_chains": self.workflow_chains,
            "pending_events": self.state.get_pending_events(),
        }
