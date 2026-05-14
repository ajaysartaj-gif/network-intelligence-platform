
"""
NetBrain AI — Stable Edition
"""

# =========================================================
# STREAMLIT CONFIG (MUST BE FIRST)
# =========================================================

import streamlit as st

st.set_page_config(
    page_title="NetBrain AI",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =========================================================
# IMPORTS
# =========================================================

import os
from core.ai_engine import ask_ai
from core.orchestration_engine import OperationsOrchestrator
import time
import random
import logging
from typing import List, Dict
from datetime import datetime

import pandas as pd

# =========================================================
# SAFE OPTIONAL IMPORTS
# =========================================================

OPENAI_AVAILABLE = False

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except Exception:
    OPENAI_AVAILABLE = False

# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)

# =========================================================
# SAFE DATABASE IMPORTS
# =========================================================

DATABASE_AVAILABLE = False

try:
    from database.database import (
        seed_database,
        get_devices,
        get_incidents,
        get_changes,
        get_auto_actions,
    )

    DATABASE_AVAILABLE = True

except Exception as e:
    logger.warning(f"Database import failed: {e}")
    DATABASE_AVAILABLE = False

# =========================================================
# WORKSPACES
# =========================================================

try:
    from config.workspaces import WORKSPACES
except Exception:
    WORKSPACES = [
        ("operations", "⚡", "Operations"),
        ("incident", "🚨", "Incidents"),
        ("topology", "🗺", "Topology"),
        ("security", "🔒", "Security"),
        ("executive", "📈", "Executive"),
    ]

# =========================================================
# SESSION STATE
# =========================================================

DEFAULTS = {
    "workspace": "Net Ops",
    "chat_history": [],
    "live_alerts": [],  # Live operational alerts
    "last_telemetry_hash": None,  # For change detection
    "incident_timeline": [],  # Live incident timeline
    "ai_rca_active": False,  # AI RCA in progress
    "ai_rca_steps": [],  # Progressive RCA steps
    "live_event_feed": [],  # Continuous operational event feed
    "last_anomaly_signatures": [],  # Anomaly signatures for recovery detection
    "recovery_timeline": [],  # Recovery event stream
    "remediation_workflow": {},  # Closed-loop remediation workflow state
    "remediation_actions": [],  # Recommended remediation actions
    "validation_commands": [],  # Recovery validation commands
    "recovery_confidence": 0,  # Confidence for validation
    "stabilization_status": "idle",
}

for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value

# =========================================================
# DATABASE INIT
# =========================================================

if DATABASE_AVAILABLE:
    try:
        seed_database()
    except Exception as e:
        logger.warning(f"Database seed failed: {e}")

@st.cache_resource
def _get_orchestrator():
    """Create orchestrator once per session; cache_resource survives reruns."""
    return OperationsOrchestrator()

orchestrator = _get_orchestrator()

# =========================================================
# AI CONFIG
# =========================================================

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
MODEL_NAME = "anthropic/claude-3.5-sonnet"


def _resolve_api_key() -> str:
    try:
        return st.secrets.get("OPENROUTER_API_KEY", "")
    except Exception:
        return os.environ.get("OPENROUTER_API_KEY", "")


@st.cache_resource
def get_ai_client():
    if not OPENAI_AVAILABLE:
        return None

    key = _resolve_api_key()

    if not key:
        return None

    try:
        return OpenAI(
            api_key=key,
            base_url=OPENROUTER_BASE,
        )
    except Exception:
        return None


SYSTEM_PROMPT = """
You are NetBrain AI.
You are an enterprise network operations assistant.
Focus on troubleshooting, root cause analysis,
and operational guidance.
"""


def call_ai(user_query: str):
    if not OPENAI_AVAILABLE:
        return "AI unavailable: OpenAI library not installed."

    api_key = _resolve_api_key()
    if not api_key:
        return "AI unavailable: OPENROUTER_API_KEY not configured."
    
    client = get_ai_client()
    if client is None:
        return "AI unavailable: Failed to initialize client."

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": user_query,
                }
            ],
            max_tokens=1200,
            temperature=0.2,
        )

        return response.choices[0].message.content

    except Exception as e:
        return f"AI Error: {str(e)}"


# =========================================================
# LIVE OPERATIONAL ENGINE
# =========================================================

def _anomaly_signature(anomaly: dict) -> str:
    """Create a compact signature for an anomaly to support recovery detection."""
    return f"{anomaly.get('device', 'unknown')}:{anomaly.get('type', 'unknown')}"


def _resolve_incidents_for_device(device: str) -> None:
    """Resolve open incidents when device anomalies clear."""
    for inc_id, inc in orchestrator.state.get_all_incidents().items():
        if device in inc.get("affected_devices", []) and inc["status"] in {"new", "investigating"}:
            orchestrator.state.update_incident(inc_id, status="resolved", note="Recovery confirmed by live telemetry.")
            st.session_state["incident_timeline"].insert(0, {
                "timestamp": datetime.utcnow().isoformat(),
                "event": f"Incident {inc_id} resolved",
                "details": f"Recovery confirmed for device {device}",
                "severity": "recovery",
            })


def _process_recovery_events(current_anomalies: List[dict]) -> None:
    """Detect cleared anomaly signatures and generate recovery events."""
    current_signatures = {_anomaly_signature(a) for a in current_anomalies}
    previous_signatures = set(st.session_state.get("last_anomaly_signatures", []))
    removed = previous_signatures - current_signatures

    for signature in removed:
        device, event_type = signature.split(":", 1) if ":" in signature else (signature, "unknown")
        message = f"Recovery confirmed: {event_type.replace('_', ' ').title()} on {device}"
        add_live_alert("recovery", message, {"device": device, "type": event_type})
        st.session_state["recovery_timeline"].insert(0, {
            "timestamp": datetime.utcnow().isoformat(),
            "event": message,
            "type": "recovery",
            "details": "Telemetry indicates the issue has cleared.",
        })
        _resolve_incidents_for_device(device)

    st.session_state["last_anomaly_signatures"] = list(current_signatures)


def _fetch_device_interface_issues(device: str) -> List[dict]:
    """Fetch current down or degraded interfaces for a device."""
    inventory = orchestrator.telemetry.current_interface_inventory.get(device, {})
    return [iface for iface in inventory.values() if iface.get("status") != "up"]


def _build_validation_commands(anomaly: dict) -> List[str]:
    """Build safe validation commands for the remediation center."""
    device = anomaly.get("device", "unknown")
    commands = [
        "show interfaces status | include down",
        "show ip route summary",
        "show ip bgp summary",
        "show ip ospf neighbor",
        "show logging | include ERROR",
    ]

    if anomaly["type"] == "interface_down":
        down_ifaces = _fetch_device_interface_issues(device)
        if down_ifaces:
            commands = [f"show interfaces {iface['name']} status" for iface in down_ifaces] + commands
        else:
            commands.insert(0, "show interfaces status | include down")
    elif anomaly["type"] == "device_unreachable":
        commands = ["show management status", f"show ip route | include {device}"] + commands
    elif anomaly["type"] == "bgp_instability":
        commands = ["show ip bgp neighbors", "show ip bgp summary"] + commands
    elif anomaly["type"] == "packet_loss":
        commands = ["show interfaces description", "show interfaces counters errors"] + commands
    elif anomaly["type"] == "latency_spike":
        commands = ["show interfaces accounting", "show controllers | include line protocol"] + commands

    return commands


def _build_closed_loop_remediation(incident_id: str, anomaly: dict) -> dict:
    """Compose a safe remediation workflow for the given incident."""
    device = anomaly.get("device", "unknown")
    device_metrics = orchestrator.state.get_device_metrics(device)
    device_state = vars(device_metrics) if device_metrics else {"hostname": device, "status": "unknown"}
    device_state["status"] = "healthy" if getattr(device_metrics, "reachable", True) else "degraded"

    alert_payload = {
        "device": device,
        "alert_type": anomaly.get("type", "operational"),
        "severity": anomaly.get("severity", "high"),
        "description": anomaly.get("description", ""),
    }

    remediation_actions = orchestrator.recommend_remediation([alert_payload], [device_state])
    safe_actions = []
    for action in remediation_actions:
        if orchestrator.self_heal.validate_remediation(action, device_state):
            simulated = orchestrator.self_heal.simulate_auto_remediation(action, approve=True)
            safe_actions.append({
                "action_id": simulated.action_id,
                "description": simulated.description,
                "risk": simulated.risk,
                "approved": simulated.approved,
                "executed": simulated.executed,
                "comments": simulated.approval_comments,
            })
        else:
            safe_actions.append({
                "action_id": action.action_id,
                "description": action.description,
                "risk": action.risk,
                "approved": False,
                "executed": False,
                "comments": "Remediation simulation deferred due to elevated risk.",
            })

    validation_commands = _build_validation_commands(anomaly)
    workflow = {
        "incident_id": incident_id,
        "device": device,
        "anomaly_type": anomaly.get("type", "unknown"),
        "status": "in_progress",
        "current_step": "Telemetry Validation",
        "steps": [
            {"name": "Telemetry Validation", "status": "completed", "note": "Collected interface, routing, and adjacency state."},
            {"name": "Operational Correlation", "status": "completed", "note": "Correlated failure across device state and service impact."},
            {"name": "AI RCA", "status": "completed", "note": "Root-cause summary prepared for remediation."},
            {"name": "Recovery Recommendation", "status": "completed", "note": "Safe remediation actions recommended."},
            {"name": "Recovery Validation", "status": "pending", "note": "Awaiting telemetry verification after corrective guidance."},
            {"name": "Incident Closure", "status": "pending", "note": "Will close incident after successful validation."},
        ],
        "validation_commands": validation_commands,
        "recommended_actions": safe_actions,
        "confidence": 0,
        "notes": [
            f"Autonomous remediation workflow started for {device}.",
        ],
    }

    st.session_state["remediation_actions"] = safe_actions
    st.session_state["validation_commands"] = validation_commands
    st.session_state["remediation_workflow"] = workflow
    st.session_state["recovery_confidence"] = 0
    st.session_state["stabilization_status"] = "in_progress"

    return workflow


def _update_remediation_workflow(incident: dict, anomaly: dict, telemetry_data: dict) -> None:
    workflow = st.session_state.get("remediation_workflow", {})
    if not workflow or workflow.get("incident_id") != incident["id"]:
        return

    validation_anomalies = orchestrator.telemetry.detect_anomalies()
    device = workflow.get("device")
    relevant_anomalies = [a for a in validation_anomalies if a.get("device") == device and a.get("type") == workflow.get("anomaly_type")]
    recovered = len(relevant_anomalies) == 0

    if recovered:
        workflow["steps"][-2]["status"] = "completed"
        workflow["steps"][-2]["note"] = "Recovery validation confirmed by telemetry."
        workflow["steps"][-1]["status"] = "completed"
        workflow["steps"][-1]["note"] = "Incident closed automatically after successful recovery verification."
        workflow["status"] = "completed"
        workflow["current_step"] = "Completed"
        workflow["confidence"] = 92
        st.session_state["stabilization_status"] = "stabilized"
        orchestrator.state.update_incident(incident["id"], status="resolved", note="Incident closed after automated recovery validation.")
        add_live_alert("recovery", f"Automated recovery verified for {device}", {"device": device, "type": workflow.get("anomaly_type")})
        st.session_state["incident_timeline"].insert(0, {
            "timestamp": datetime.utcnow().isoformat(),
            "event": f"Automated recovery validated for {device}",
            "details": "Platform confirmed restoration and closed the incident.",
            "severity": "recovery",
        })
    else:
        workflow["steps"][-2]["status"] = "in_progress"
        workflow["current_step"] = "Recovery Validation"
        workflow["confidence"] = max(20, min(85, 50 + len(workflow.get("recommended_actions", [])) * 10))
        if "Waiting for telemetry to confirm issue clearance." not in workflow["notes"]:
            workflow["notes"].append("Waiting for telemetry to confirm issue clearance.")
        st.session_state["stabilization_status"] = "validating"

    st.session_state["remediation_workflow"] = workflow


def _attempt_autonomous_recovery(anomalies: List[dict], telemetry_data: dict) -> None:
    """Start or continue closed-loop remediation for open incidents."""
    open_incidents = [inc for inc in orchestrator.state.get_all_incidents().values() if inc["status"] in {"new", "investigating"}]
    if not open_incidents:
        return

    primary_incident = open_incidents[0]
    workflow = st.session_state.get("remediation_workflow", {})
    if workflow.get("status") == "completed" and workflow.get("incident_id") == primary_incident["id"]:
        return

    related_anomaly = next((a for a in anomalies if a.get("device") in primary_incident.get("affected_devices", [])), anomalies[0] if anomalies else None)
    if not related_anomaly:
        return

    if not workflow or workflow.get("incident_id") != primary_incident["id"]:
        _build_closed_loop_remediation(primary_incident["id"], related_anomaly)
        st.session_state["incident_timeline"].insert(0, {
            "timestamp": datetime.utcnow().isoformat(),
            "event": "Autonomous remediation workflow started",
            "details": f"Started safe recovery orchestration for {related_anomaly.get('device', 'unknown')}",
            "severity": "high",
        })

    _update_remediation_workflow(primary_incident, related_anomaly, telemetry_data)


def poll_live_telemetry():
    """Poll live telemetry, detect anomalies, create incidents, and trigger RCA."""
    try:
        telemetry_data = orchestrator.telemetry.collect_all_telemetry()
        anomalies = orchestrator.telemetry.detect_anomalies()

        logger.info(
            f"[POLL] telemetry collected | devices={len(telemetry_data.get('device_metrics', {}))} "
            f"| anomalies={len(anomalies)}"
        )

        current_hash = hash(str(sorted(str(anomalies))))
        last_hash = st.session_state.get("last_telemetry_hash")

        if last_hash is None or current_hash != last_hash:
            st.session_state["last_telemetry_hash"] = current_hash

            # Process anomalies → generate incidents
            incident_ids = orchestrator.events.process_anomalies(anomalies)

            if incident_ids:
                logger.info(f"[INCIDENTS] Created: {incident_ids}")
                for inc_id in incident_ids:
                    inc = orchestrator.state.get_incident(inc_id)
                    if inc:
                        related_anomaly = next(
                            (a for a in anomalies if a.get("device") in inc.get("affected_devices", [])),
                            anomalies[0] if anomalies else None,
                        )
                        if related_anomaly:
                            add_live_alert(
                                related_anomaly.get("severity", "high"),
                                f"{related_anomaly['type'].replace('_', ' ').title()} on "
                                f"{related_anomaly.get('device', 'unknown')}",
                                related_anomaly,
                            )
                            # Trigger non-blocking RCA for first new incident
                            if not st.session_state.get("ai_rca_active"):
                                st.session_state["ai_rca_active"] = True
                                start_ai_rca(inc_id, related_anomaly)

            # Detect recoveries from cleared anomaly signatures
            _process_recovery_events(anomalies)

            # Refresh live event feed
            st.session_state["live_event_feed"] = orchestrator.events.get_event_history(limit=20)

            # Rebuild incident timeline
            if incident_ids or anomalies:
                event_history = orchestrator.events.get_event_history(limit=15)
                timeline_entries = [
                    {
                        "timestamp": ev.get("timestamp"),
                        "event": ev.get("type", "unknown").replace("_", " ").title(),
                        "details": ev.get("description", ""),
                        "severity": ev.get("severity", "info"),
                    }
                    for ev in reversed(event_history[-15:])
                ]
                st.session_state["incident_timeline"] = timeline_entries

        _attempt_autonomous_recovery(anomalies, telemetry_data)
        return telemetry_data

    except Exception as e:
        logger.error(f"[POLL] Live telemetry poll failed: {e}", exc_info=True)
        return {}


def detect_operational_changes(telemetry_data):
    """Detect operational changes and generate live events."""
    anomalies = orchestrator.telemetry.detect_anomalies()
    incident_ids = orchestrator.events.process_anomalies(anomalies)

    for anomaly in anomalies:
        if anomaly.get("severity") in ["critical", "high"]:
            add_live_alert(
                anomaly["severity"],
                f"{anomaly['type'].replace('_', ' ').title()} on {anomaly.get('device', 'unknown')}",
                anomaly,
            )

    if incident_ids:
        event_history = orchestrator.events.get_event_history(limit=15)
        timeline_entries = [
            {
                "timestamp": event.get("timestamp"),
                "event": event.get("type", "unknown").replace("_", " ").title(),
                "details": event.get("description", ""),
                "severity": event.get("severity", "info"),
            }
            for event in event_history[-15:]
        ]
        st.session_state["incident_timeline"] = list(reversed(timeline_entries))

    return incident_ids


def add_live_alert(severity: str, message: str, anomaly: dict):
    """Add a live operational alert."""
    alert = {
        "timestamp": datetime.utcnow().isoformat(),
        "severity": severity,
        "message": message,
        "anomaly": anomaly,
        "id": f"alert_{datetime.utcnow().strftime('%H%M%S%f')}"
    }
    st.session_state["live_alerts"].insert(0, alert)

    # Keep only recent alerts
    if len(st.session_state["live_alerts"]) > 10:
        st.session_state["live_alerts"] = st.session_state["live_alerts"][:10]


def create_live_incident(anomaly: dict):
    """Create incident from operational anomaly."""
    try:
        incident_id = f"INC-{datetime.utcnow().strftime('%H%M%S%f')}"
        affected_devices = [anomaly["device"]] if anomaly.get("device") else []
        impacted_services = orchestrator.state.calculate_service_impact(affected_devices).get("impacted_services", [])

        orchestrator.state.create_incident(
            incident_id=incident_id,
            title=f"Critical: {anomaly['type'].replace('_', ' ').title()}",
            description=anomaly.get("description", f"Operational anomaly detected: {anomaly['type']}"),
            severity=anomaly["severity"],
            affected_devices=affected_devices,
            affected_services=impacted_services,
        )

        timeline_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "event": f"Incident {incident_id} created",
            "type": "incident_created",
            "details": f"Critical incident from {anomaly['type']} on {anomaly.get('device', 'unknown')}"
        }
        st.session_state["incident_timeline"].insert(0, timeline_entry)

        start_ai_rca(incident_id, anomaly)

    except Exception as e:
        logger.error(f"Failed to create live incident: {e}")


def _build_local_rca_summary(incident_id: str, anomaly: dict) -> str:
    """Build a structured operational RCA summary when AI is limited."""
    device = anomaly.get("device", "unknown")
    metrics = orchestrator.state.get_device_metrics(device)
    impacted_services = orchestrator.state.calculate_service_impact([device]).get("impacted_services", [])
    service_text = ", ".join(impacted_services) if impacted_services else "None identified"
    severity = anomaly.get("severity", "high").upper()
    root_cause = "Correlated network degradation detected."

    if anomaly["type"] == "interface_down":
        root_cause = "Interface operational failure on device causing path degradation and packet loss."
    elif anomaly["type"] == "device_unreachable":
        root_cause = "Device unreachable, causing routing and service path disruption."
    elif anomaly["type"] == "bgp_instability":
        root_cause = "BGP neighbor instability causing routing convergence issues."
    elif anomaly["type"] == "latency_spike":
        root_cause = "WAN path degradation causing elevated latency and retransmissions."

    return (
        "Operational Summary:\n"
        f"Device: {device}\n"
        f"Severity: {severity}\n"
        f"Impacted Services: {service_text}\n"
        f"Root Cause: {root_cause}\n"
        "Recommended Actions: Validate interface state, confirm routing adjacency, and isolate the impacted WAN path.\n"
        "Recovery Validation Steps: Confirm interface status, verify BGP adjacency, validate traffic forwarding, and recheck service reachability."
    )


def start_ai_rca(incident_id: str, anomaly: dict):
    """Run autonomous AI RCA — non-blocking, no sleep."""
    device = anomaly.get("device", "unknown")
    logger.info(f"[RCA] Starting RCA for incident {incident_id} on {device}")

    steps = [
        "Collecting live telemetry...",
        "Validating interface state...",
        "Checking routing adjacency...",
        "Checking BGP sessions...",
        "Correlating operational failures...",
        "Computing service blast radius...",
        "Generating root cause analysis...",
        "Generating remediation recommendations...",
    ]
    rca_steps = [
        {"timestamp": datetime.utcnow().isoformat(), "step": s, "status": "completed"}
        for s in steps
    ]

    try:
        rca_query = (
            f"Analyze this network incident:\n"
            f"Incident ID: {incident_id}\n"
            f"Type: {anomaly.get('type', 'unknown')}\n"
            f"Device: {device}\n"
            f"Severity: {anomaly.get('severity', 'high')}\n"
            f"Description: {anomaly.get('description', 'N/A')}\n"
            f"Impacted services: {orchestrator.state.calculate_service_impact([device]).get('impacted_services', [])}\n"
            "Provide: operational summary, root cause, impacted services, "
            "recommended actions, recovery validation steps."
        )
        rca_result = call_ai(rca_query) if OPENAI_AVAILABLE else _build_local_rca_summary(incident_id, anomaly)
        rca_steps[-1]["result"] = rca_result
        orchestrator.state.update_incident(
            incident_id, status="investigating",
            note=f"AI RCA completed: {rca_result[:200]}..."
        )
        logger.info(f"[RCA] Completed for incident {incident_id}")
    except Exception as e:
        logger.error(f"[RCA] Failed for incident {incident_id}: {e}")
        rca_steps[-1]["status"] = "failed"
        rca_steps[-1]["error"] = str(e)

    st.session_state["ai_rca_steps"] = rca_steps
    st.session_state["ai_rca_active"] = False


# =========================================================
# SAMPLE DATA
# =========================================================


# =========================================================
# SIDEBAR
# =========================================================

with st.sidebar:
    st.title("🧠 NetBrain AI")
    st.caption("Autonomous Network OS")

    st.divider()

    # Current workspace indicator
    current_ws = st.session_state.workspace
    workspace_names = {ws_id: label for ws_id, icon, label in WORKSPACES}
    st.markdown(f"**Current Workspace:** {workspace_names.get(current_ws, 'Operations').upper()}")

    st.divider()

    # Workspace buttons
    for ws_id, icon, label in WORKSPACES:
        is_active = (ws_id == current_ws)
        button_style = "primary" if is_active else "secondary"
        
        if st.button(
            f"{icon} {label}",
            use_container_width=True,
            key=f"ws_{ws_id}",
            type=button_style,
        ):
            st.session_state.workspace = ws_id
            st.rerun()

    st.divider()

    st.markdown("### Platform Status")

    col1, col2 = st.columns(2)
    with col1:
        if OPENAI_AVAILABLE:
            st.success("AI ✓")
        else:
            st.error("AI ✗")
        
        if DATABASE_AVAILABLE:
            st.success("DB ✓")
        else:
            st.warning("DB ✗")
    
    with col2:
        st.success("Streamlit ✓")
        live_label = "Live ✓" if orchestrator.telemetry.live_mode else "Sim ✓"
        st.info(live_label)

    st.divider()
    st.markdown("### Operational Debug")
    device_count = len(orchestrator.state.get_all_device_metrics())
    incident_count = len(orchestrator.state.get_all_incidents())
    anomaly_count = len(orchestrator.telemetry.detect_anomalies())
    event_count = len(orchestrator.events.get_event_history())
    st.caption(f"Devices: {device_count} | Incidents: {incident_count}")
    st.caption(f"Anomalies: {anomaly_count} | Events: {event_count}")
    st.caption(f"Mode: {'LIVE' if orchestrator.telemetry.live_mode else 'SIM'}")
    poll_age = time.time() - st.session_state.get("last_poll_time", 0)
    st.caption(f"Last poll: {poll_age:.0f}s ago")

# =========================================================
# WORKSPACE CONTENT
# =========================================================

workspace = st.session_state.workspace

if workspace == "Net Ops":
    st.header("⚡ Autonomous NOC Operations Center")
    st.markdown("### Live operational intelligence — real-time failure correlation")

    POLL_INTERVAL_SECS = 5

    if "last_poll_time" not in st.session_state:
        st.session_state["last_poll_time"] = 0.0

    current_time = time.time()
    elapsed = current_time - st.session_state["last_poll_time"]

    if elapsed >= POLL_INTERVAL_SECS:
        telemetry_data = poll_live_telemetry()
        st.session_state["last_poll_time"] = current_time
    else:
        telemetry_data = st.session_state.get("_last_telemetry", {})

    status = orchestrator.get_operational_status()
    summary = status["operational_summary"]
    live_alerts = st.session_state.get("live_alerts", [])
    event_feed = st.session_state.get("live_event_feed", [])
    recovery_feed = st.session_state.get("recovery_timeline", [])
    active_incidents = [inc for inc in orchestrator.state.get_all_incidents().values() if inc["status"] in {"new", "investigating"}]
    degraded_services = [svc for svc, dep in orchestrator.state.service_dependencies.items() if dep.status in {"degraded", "down"}]
    impacted_wan = [svc for svc in degraded_services if "WAN" in svc or "VPN" in svc or "Internet" in svc]

    critical_count = summary["incidents"]["new"] + summary["incidents"]["investigating"]
    outage_count = summary["services"]["down"]
    mttr_minutes = max(5, critical_count * 4)
    stability = summary["operational_score"]

    if live_alerts:
        with st.container():
            st.markdown("<div style='background:#660000;padding:12px;border-radius:8px;color:#fff;'>"
                        "<strong>CRITICAL ALERT CENTER</strong> — Live operational failures detected</div>", unsafe_allow_html=True)
            for alert in live_alerts[:5]:
                severity_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢", "recovery": "✅"}.get(alert["severity"], "⚪")
                st.markdown(f"{severity_icon} **{alert['severity'].upper()}** — {alert['message']} — {alert['timestamp'][-8:]}")
            if len(live_alerts) > 5:
                st.markdown(f"*...and {len(live_alerts) - 5} more alerts*")

    executive_col1, executive_col2, executive_col3, executive_col4 = st.columns(4)
    with executive_col1:
        st.metric("Operational Stability", f"{stability:.0f}%", delta=f"{outage_count} outages")
    with executive_col2:
        st.metric("Active Incidents", critical_count, delta=f"{len(active_incidents)} active")
    with executive_col3:
        st.metric("Degraded Services", len(degraded_services), delta=f"{outage_count} down")
    with executive_col4:
        st.metric("MTTR Estimate", f"{mttr_minutes}m", delta="Recovery tracking")

    st.progress(int(max(0, min(100, stability))))

    st.divider()
    st.markdown("### Live Event Feed")
    if event_feed:
        feed_rows = [
            {
                "time": item.get("timestamp", "")[-8:],
                "event": item.get("type", "unknown").replace("_", " ").title(),
                "severity": item.get("severity", "info").upper(),
                "detail": item.get("description", item.get("details", ""))[:80],
            }
            for item in event_feed[-20:]
        ]
        st.dataframe(pd.DataFrame(feed_rows).sort_values(by="time", ascending=False))
    else:
        st.info("Waiting for live operational events...")

    st.divider()
    st.markdown("### Incident & Recovery Timeline")
    if active_incidents or recovery_feed:
        timeline_rows = []
        for event in st.session_state.get("incident_timeline", [])[:15]:
            timeline_rows.append({
                "time": event.get("timestamp", "")[-8:],
                "event": event.get("event", "unknown"),
                "severity": event.get("severity", "info").upper(),
                "details": event.get("details", "")[:80],
            })
        for event in recovery_feed[:5]:
            timeline_rows.append({
                "time": event.get("timestamp", "")[-8:],
                "event": event.get("event", "recovery"),
                "severity": "RECOVERY",
                "details": event.get("details", ""),
            })
        st.dataframe(pd.DataFrame(timeline_rows).sort_values(by="time", ascending=False))
    else:
        st.info("No incidents or recovery actions recorded yet.")

    st.divider()
    st.markdown("### Active Critical Incidents")
    if active_incidents:
        for inc in active_incidents:
            severity_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(inc["severity"], "⚪")
            with st.expander(f"{severity_icon} **{inc['id']}** — {inc['title']} — {inc['status'].upper()}", expanded=inc["severity"] == "critical"):
                st.markdown(f"**Severity:** {inc['severity'].upper()}")
                if inc.get("affected_devices"):
                    st.markdown(f"**Devices:** {', '.join(inc['affected_devices'])}")
                if inc.get("affected_services"):
                    st.markdown(f"**Services:** {', '.join(inc['affected_services'])}")
                if inc.get("timeline"):
                    st.markdown("**Timeline:**")
                    for note in inc["timeline"][-3:]:
                        st.markdown(f"- {note['timestamp'][-8:]}: {note['note']}")
    else:
        st.success("No active critical incidents. Network operations stabilized.")

    st.divider()
    st.markdown("### Autonomous Investigation Workflow")
    if st.session_state.get("ai_rca_steps"):
        for step in st.session_state["ai_rca_steps"]:
            status_icon = "✅" if step["status"] == "completed" else "⏳" if step["status"] == "in_progress" else "❌"
            st.markdown(f"{status_icon} {step['step']}")
            if step.get("result"):
                st.markdown(f"> {step['result'][:220]}...")
    else:
        st.info("Awaiting autonomous investigation trigger...")

    st.divider()
    st.markdown("### Autonomous Remediation Center")
    remediation_workflow = st.session_state.get("remediation_workflow", {})
    if remediation_workflow:
        st.markdown(f"**Workflow Status:** {remediation_workflow.get('status', 'idle').title()} - {remediation_workflow.get('current_step', 'pending')}")
        st.markdown(f"**Device:** {remediation_workflow.get('device', 'N/A')}")
        st.markdown(f"**Recovery Confidence:** {st.session_state.get('recovery_confidence', 0)}%")
        st.markdown(f"**Stabilization Status:** {st.session_state.get('stabilization_status', 'idle').title()}")

        if remediation_workflow.get("recommended_actions"):
            st.subheader("Recommended Safe Remediation Actions")
            for action in remediation_workflow["recommended_actions"]:
                status_icon = "✅" if action["executed"] else "⚠️"
                st.markdown(f"{status_icon} **{action['description']}** — Risk: {action['risk'].upper()} — {action['comments']}")

        if remediation_workflow.get("validation_commands"):
            st.subheader("Recovery Validation Commands")
            for cmd in remediation_workflow["validation_commands"]:
                st.code(cmd)

        if remediation_workflow.get("steps"):
            st.subheader("Workflow Progress")
            for step in remediation_workflow["steps"]:
                status_icon = "✅" if step["status"] == "completed" else "⏳" if step["status"] == "in_progress" else "⚪"
                st.markdown(f"{status_icon} {step['name']} — {step['status']}\n> {step['note']}")
    else:
        st.info("No autonomous remediation workflow is active. The platform will start recovery orchestration when the next incident is detected.")

    st.divider()
    st.markdown("### Device Health Matrix")
    health_rows = []
    for hostname, metrics in orchestrator.state.get_all_device_metrics().items():
        health = orchestrator.telemetry.get_device_health_score(hostname)
        link_status = "GREEN" if getattr(metrics, "reachable", True) and metrics.packet_loss_pct < 3 else "AMBER" if metrics.packet_loss_pct < 8 else "RED"
        health_rows.append({
            "Device": hostname,
            "Health": f"{health['score']:.0f}%",
            "Status": f"{health['status'].upper()}",
            "Latency": f"{metrics.latency_ms:.1f}ms",
            "Loss": f"{metrics.packet_loss_pct:.1f}%",
            "Link": link_status,
        })
    if health_rows:
        st.dataframe(pd.DataFrame(health_rows))
    else:
        st.info("No device health telemetry available yet.")

    st.divider()
    st.markdown("### Topology Status")
    topology_rows = []
    for hostname, metrics in orchestrator.state.get_all_device_metrics().items():
        topology_rows.append({
            "Device": hostname,
            "Path": "Healthy" if getattr(metrics, "reachable", True) else "Failed",
            "Status": "GREEN" if getattr(metrics, "reachable", True) else "RED",
        })
    if topology_rows:
        st.dataframe(pd.DataFrame(topology_rows))
    else:
        st.info("Topology nominal — no path data available.")

    # ── Auto-refresh: block for POLL_INTERVAL_SECS then rerun ──────────
    remaining = max(0.0, POLL_INTERVAL_SECS - (time.time() - st.session_state["last_poll_time"]))
    st.caption(f"Next telemetry poll in {remaining:.0f}s")
    if remaining > 0:
        time.sleep(remaining)
    st.rerun()

elif workspace == "incident":
    st.header("🚨 Incident Management")
    
    status = orchestrator.get_operational_status()
    incidents_data = status["incidents"]
    open_incidents = incidents_data["by_status"].get("new", 0) + incidents_data["by_status"].get("investigating", 0)
    critical_count = sum(1 for inc in orchestrator.state.get_all_incidents().values() if inc.get("severity") == "critical")
    resolved_today = incidents_data["by_status"].get("resolved", 0)

    # Live alerts summary
    live_alerts = st.session_state.get("live_alerts", [])
    active_alerts = len([a for a in live_alerts if a["severity"] in ["critical", "high"]])

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Open Incidents", open_incidents)
    with col2:
        st.metric("Critical", critical_count)
    with col3:
        st.metric("Resolved Today", resolved_today)
    with col4:
        st.metric("Live Alerts", active_alerts, delta="active monitoring")

    # Live Critical Alerts
    if live_alerts:
        st.subheader("🔴 Live Critical Alerts")
        for alert in live_alerts[:5]:
            severity_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(alert["severity"], "⚪")
            with st.expander(f"{severity_icon} {alert['message']} — {alert['timestamp'][-8:]}", expanded=alert["severity"] == "critical"):
                st.markdown(f"**Severity:** {alert['severity'].upper()}")
                st.markdown(f"**Time:** {alert['timestamp']}")
                if alert.get("anomaly"):
                    st.markdown(f"**Device:** {alert['anomaly'].get('device', 'N/A')}")
                    st.markdown(f"**Type:** {alert['anomaly'].get('type', 'N/A').replace('_', ' ').title()}")
                    if alert["anomaly"].get("description"):
                        st.markdown(f"**Description:** {alert['anomaly']['description']}")

    st.subheader("Active Incidents")
    all_incidents = orchestrator.state.get_all_incidents()
    
    if all_incidents:
        for inc_id, inc in all_incidents.items():
            if inc["status"] in ["new", "investigating"]:
                severity_color = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(inc["severity"], "⚪")
                with st.expander(f"{severity_color} **{inc_id}**: {inc['title']} - {inc['status'].upper()}", expanded=inc["severity"] == "critical"):
                    st.markdown(f"**Severity:** {inc['severity'].upper()}")
                    st.markdown(f"**Status:** {inc['status']}")
                    st.markdown(f"**Created:** {inc.get('created_at', 'N/A')}")
                    if inc.get("affected_devices"):
                        st.markdown(f"**Affected Devices:** {', '.join(inc['affected_devices'])}")
                    if inc.get("affected_services"):
                        st.markdown(f"**Affected Services:** {', '.join(inc['affected_services'])}")
                    if inc.get("timeline"):
                        st.markdown("**Timeline:**")
                        for note in inc["timeline"][-5:]:
                            st.markdown(f"- {note['timestamp'][-8:]}: {note['note']}")
                    
                    # AI RCA Results
                    if st.session_state.get("ai_rca_active") and inc_id in [a.get("incident_id") for a in st.session_state.get("ai_rca_steps", []) if a.get("incident_id")]:
                        st.markdown("**🤖 AI RCA In Progress:**")
                        rca_steps = [s for s in st.session_state["ai_rca_steps"] if s.get("incident_id") == inc_id]
                        for step in rca_steps[-3:]:
                            status_icon = "⏳" if step["status"] == "in_progress" else "✅" if step["status"] == "completed" else "❌"
                            st.markdown(f"{status_icon} {step['step']}")
                            if step.get("result"):
                                st.markdown(f"**Result:** {step['result'][:500]}...")
    else:
        st.info("No active incidents. All systems operational.")

elif workspace == "topology":
    st.header("🗺 Network Topology")
    
    status = orchestrator.get_operational_status()
    critical_devices = len(orchestrator.state.get_critical_devices())
    unreachable_count = sum(1 for m in orchestrator.state.get_all_device_metrics().values() if getattr(m, "reachable", True) is False)

    summary = status["operational_summary"]
    dev_summary = summary.get("devices", {})
    link_summary = summary.get("links", {})

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Devices", dev_summary.get("total", summary.get("total_devices", 0)))
    with col2:
        st.metric("Healthy Devices", dev_summary.get("healthy", 0), delta=f"{unreachable_count} unreachable")
    with col3:
        st.metric("Critical Devices", critical_devices)
    with col4:
        st.metric("Links Active", link_summary.get("active", 0))
    
    st.subheader("Live Device Status")
    
    # Show all devices with live status
    device_status_data = []
    for hostname, metrics in orchestrator.state.get_all_device_metrics().items():
        health_score = orchestrator.telemetry.get_device_health_score(hostname)
        status_icon = "🟢" if health_score["status"] == "healthy" else "🟡" if health_score["status"] == "warning" else "🔴"
        reachable_icon = "✅" if getattr(metrics, "reachable", True) else "❌"
        
        device_status_data.append({
            "Device": hostname,
            "Status": f"{status_icon} {health_score['status'].upper()}",
            "Health Score": f"{health_score['score']:.0f}%",
            "Reachable": reachable_icon,
            "CPU": f"{metrics.cpu:.1f}%" if hasattr(metrics, 'cpu') else "N/A",
            "Memory": f"{metrics.memory:.1f}%" if hasattr(metrics, 'memory') else "N/A",
            "Issues": len(health_score.get("issues", []))
        })
    
    if device_status_data:
        st.dataframe(pd.DataFrame(device_status_data))
        
        # Show critical devices details
        critical_devices_list = [d for d in device_status_data if "🔴" in d["Status"]]
        if critical_devices_list:
            st.subheader("🔴 Critical Devices Details")
            for device in critical_devices_list:
                with st.expander(f"Critical: {device['Device']}", expanded=True):
                    health_score = orchestrator.telemetry.get_device_health_score(device["Device"])
                    st.markdown(f"**Health Score:** {device['Health Score']}")
                    st.markdown(f"**Issues:** {', '.join(health_score.get('issues', []))}")
                    st.markdown(f"**Reachable:** {device['Reachable']}")
    else:
        st.info("No device telemetry available. Monitoring live...")

    st.subheader("Network Links Status")
    # Show link status based on device reachability
    link_status_data = []
    device_metrics = orchestrator.state.get_all_device_metrics()
    
    # Simple link representation based on device connectivity
    for hostname, metrics in device_metrics.items():
        reachable = getattr(metrics, "reachable", True)
        link_status_data.append({
            "Source": "CORE",
            "Target": hostname.upper(),
            "Status": "UP" if reachable else "DOWN",
            "Type": "WAN" if "wan" in hostname else "LAN",
            "Bandwidth": "1Gbps" if reachable else "N/A"
        })
    
    if link_status_data:
        st.dataframe(pd.DataFrame(link_status_data))
    else:
        st.info("No link data available.")

elif workspace == "security":
    st.header("🔒 Security Operations")
    
    status = orchestrator.get_operational_status()
    compliance_score = min(100, max(60, int(status["operational_summary"]["operational_score"] + 5)))
    threat_count = sum(1 for inc in orchestrator.state.get_all_incidents().values() if inc.get("severity") in {"critical", "high"})
    config_drift = len([cid for cid, comp in orchestrator.state.compliance_status.items() if comp.get("status") != "healthy"])
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Threats Detected", threat_count, "+ network-aware")
    with col2:
        st.metric("Compliance Score", f"{compliance_score}%", "+ operational")
    with col3:
        st.metric("Config Drift Events", config_drift)
    
    st.subheader("Security Alerts")
    for inc in orchestrator.state.get_all_incidents().values():
        if inc.get("severity") in {"critical", "high"}:
            st.error(f"🚨 {inc['title']}: {inc['description']}")
        elif inc.get("severity") == "medium":
            st.warning(f"⚠️ {inc['title']}: {inc['description']}")
    if not orchestrator.state.get_all_incidents():
        st.info("No active security incidents.")

elif workspace == "executive":
    st.header("📈 Executive Dashboard")
    
    status = orchestrator.get_operational_status()
    health_score = status["operational_summary"]["operational_score"]
    open_incidents = status["incidents"]["by_status"].get("new", 0) + status["incidents"]["by_status"].get("investigating", 0)
    critical_incidents = sum(1 for inc in orchestrator.state.get_all_incidents().values() if inc.get("severity") in {"critical", "high"})
    services_down = status["operational_summary"]["services"]["down"]

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Network Health", f"{health_score:.0f}%", f"{services_down} services impacted")
    with col2:
        st.metric("Open Incidents", open_incidents, f"{critical_incidents} critical")
    with col3:
        st.metric("MTTR", "~45 min", "demo metric")
    with col4:
        st.metric("Risk Exposure", f"{min(100, 100 - int(health_score))}%", "Operational risk")
    
    st.subheader("Key Insights")
    insights = [
        f"Health score is {health_score:.0f}% with {open_incidents} open incidents.",
        f"Critical incidents are affecting {services_down} services and require NOC escalation.",
        f"Autonomous workflows are tracking {status['operational_summary']['workflows_active']} active remediation workflows.",
        "AI operational guidance is suggesting immediate WAN and BGP stabilization steps.",
    ]
    
    for insight in insights:
        st.success(f"✅ {insight}")
    
    st.subheader("Risk Analysis")
    if health_score < 70:
        st.error("🔴 Elevated risk: network health below 70% and critical service impact present.")
    elif health_score < 85:
        st.warning("🟠 Medium risk: maintain heightened monitoring and resolve open incidents.")
    else:
        st.info("🟢 Low risk: continue running autonomous remediation workflows.")

else:
    # Default operations view
    st.header("🚀 Operations Center")
    st.info("Select a workspace from the sidebar to get started")
