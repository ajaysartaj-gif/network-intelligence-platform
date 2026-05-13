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

    def emit_event(self, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Emit an event and process all handlers.
        Returns list of downstream events triggered.
        """
        event_type = event.get("type")
        
        if not event_type:
            return []

        # Record in history
        event_record = {
            "id": f"EVT-{int(datetime.utcnow().timestamp())}",
            "type": event_type,
            "timestamp": datetime.utcnow().isoformat(),
            **event,
        }
        self.event_history.append(event_record)

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
            except Exception as e:
                # Log handler error but continue
                pass

        # Process downstream events
        all_downstream = downstream_events.copy()
        for downstream in downstream_events:
            further_downstream = self.emit_event(downstream)
            all_downstream.extend(further_downstream)

        return all_downstream

    # ═══════════════════════════════════════════════════════════════
    # ANOMALY TO INCIDENT WORKFLOW
    # ═══════════════════════════════════════════════════════════════

    def process_anomalies(self, anomalies: List[Dict[str, Any]]) -> List[str]:
        """Process detected anomalies and trigger workflows."""
        incident_ids = []

        for anomaly in anomalies:
            event = self._anomaly_to_event(anomaly)
            
            if event:
                self.emit_event(event)
                
                # Create incident if severity warrants
                if anomaly.get("severity") in ["high", "critical"]:
                    incident_id = self._create_incident_from_anomaly(anomaly)
                    incident_ids.append(incident_id)
                    self.emit_event({
                        "type": "incident_created",
                        "severity": anomaly.get("severity", "high"),
                        "source": "event_engine",
                        "description": f"Incident {incident_id} created for {anomaly.get('type')}",
                        "data": {"incident_id": incident_id, "anomaly": anomaly},
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
        elif atype == "packet_loss":
            return {
                "type": "packet_loss_detected",
                "severity": severity,
                "source": "telemetry_engine",
                "description": f"Packet loss on {device}: {anomaly.get('loss_pct', 'unknown')}%",
                "data": anomaly,
            }
        elif atype == "latency_spike":
            return {
                "type": "latency_spike_detected",
                "severity": severity,
                "source": "telemetry_engine",
                "description": f"Latency spike on {device}: {anomaly.get('latency_ms', 'unknown')}ms",
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

        return None

    def _create_incident_from_anomaly(self, anomaly: Dict[str, Any]) -> str:
        """Create incident from anomaly."""
        atype = anomaly.get("type")
        device = anomaly.get("device", "unknown")
        severity = anomaly.get("severity", "medium")

        title_map = {
            "cpu_spike": f"High CPU on {device}",
            "memory_exhaustion": f"Memory exhaustion on {device}",
            "interface_flap": f"Interface flap on {device}",
            "packet_loss": f"Packet loss on {device}",
            "latency_spike": f"Latency spike on {device}",
            "bgp_instability": f"BGP instability on {device}",
            "wan_degradation": "WAN link degradation",
        }

        title = title_map.get(atype, f"Network anomaly: {atype}")
        description = f"Anomaly detected: {anomaly.get('description', str(anomaly))}"
        
        incident_id = f"INC-{int(datetime.utcnow().timestamp())}"
        
        self.state.create_incident(
            incident_id=incident_id,
            title=title,
            description=description,
            severity=severity,
            affected_devices=[device] if device != "unknown" else [],
            affected_services=[],
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
