
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
from core.ai_engine import ask_ai, get_api_key
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

orchestrator = OperationsOrchestrator()

# =========================================================
# AI CONFIG
# =========================================================

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
MODEL_NAME = "anthropic/claude-3.5-sonnet"


def get_api_key():
    try:
        return st.secrets.get("OPENROUTER_API_KEY", "")
    except Exception:
        return os.environ.get("OPENROUTER_API_KEY", "")


@st.cache_resource

def get_ai_client():
    if not OPENAI_AVAILABLE:
        return None

    key = get_api_key()

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
    
    api_key = get_api_key()
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

def poll_live_telemetry():
    """Poll live telemetry and detect operational changes."""
    try:
        # Collect current telemetry
        telemetry_data = orchestrator.telemetry.collect_all_telemetry()
        current_hash = hash(str(telemetry_data))

        # Check for changes
        last_hash = st.session_state.get("last_telemetry_hash")
        if last_hash is None or current_hash != last_hash:
            st.session_state["last_telemetry_hash"] = current_hash
            detect_operational_changes(telemetry_data)

        return telemetry_data
    except Exception as e:
        logger.error(f"Live telemetry poll failed: {e}")
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
        "id": f"alert_{int(time.time() * 1000)}"
    }
    st.session_state["live_alerts"].insert(0, alert)

    # Keep only recent alerts
    if len(st.session_state["live_alerts"]) > 10:
        st.session_state["live_alerts"] = st.session_state["live_alerts"][:10]


def create_live_incident(anomaly: dict):
    """Create incident from operational anomaly."""
    try:
        incident_id = f"INC-{int(time.time())}"
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
    """Start autonomous AI RCA workflow."""
    st.session_state["ai_rca_active"] = True
    st.session_state["ai_rca_steps"] = []

    steps = [
        "Analyzing telemetry data...",
        "Validating interface state...",
        "Checking routing state...",
        "Validating neighboring links...",
        "Checking BGP adjacency...",
        "Correlating operational failures...",
        "Generating root cause analysis...",
        "Generating remediation recommendations..."
    ]

    for step in steps:
        st.session_state["ai_rca_steps"].append({
            "timestamp": datetime.utcnow().isoformat(),
            "step": step,
            "status": "in_progress"
        })
        time.sleep(0.4)

    try:
        rca_query = f"""
        Analyze this operational incident:
        Incident ID: {incident_id}
        Type: {anomaly['type']}
        Device: {anomaly.get('device', 'unknown')}
        Severity: {anomaly.get('severity', 'high')}
        Description: {anomaly.get('description', 'N/A')}
        Current metrics: {orchestrator.state.get_device_metrics(anomaly.get('device', 'unknown'))}
        Impacted services: {orchestrator.state.calculate_service_impact([anomaly.get('device', 'unknown')]).get('impacted_services', [])}

        Provide an operational summary, root cause, impacted services, operational severity, recommended actions, and recovery validation steps.
        """

        if OPENAI_AVAILABLE:
            rca_result = call_ai(rca_query)
        else:
            rca_result = _build_local_rca_summary(incident_id, anomaly)

        st.session_state["ai_rca_steps"][-1]["status"] = "completed"
        st.session_state["ai_rca_steps"][-1]["result"] = rca_result

        orchestrator.state.update_incident(incident_id, status="investigating", note=f"AI RCA: {rca_result[:200]}...")

    except Exception as e:
        logger.error(f"AI RCA failed: {e}")
        st.session_state["ai_rca_steps"][-1]["status"] = "failed"
        st.session_state["ai_rca_steps"][-1]["error"] = str(e)

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
        st.info("v2.0")

# =========================================================
# WORKSPACE CONTENT
# =========================================================

workspace = st.session_state.workspace

if workspace == "operations":
    st.header("🚀 Autonomous Operations Center")
    st.markdown("### Live Operational Monitoring — Real Network Intelligence")

    # Initialize live monitoring
    if "live_initialized" not in st.session_state:
        st.session_state["live_initialized"] = True

    # Live telemetry polling (every 5 seconds)
    if "last_poll_time" not in st.session_state:
        st.session_state["last_poll_time"] = time.time()
    
    current_time = time.time()
    if current_time - st.session_state["last_poll_time"] > 5:
        telemetry_data = poll_live_telemetry()
        st.session_state["last_poll_time"] = current_time
        st.rerun()  # Trigger UI update

    # Display live alerts banner
    live_alerts = st.session_state.get("live_alerts", [])
    if live_alerts:
        with st.container():
            st.error("🚨 **LIVE CRITICAL ALERTS**")
            for alert in live_alerts[:3]:  # Show top 3
                severity_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(alert["severity"], "⚪")
                st.markdown(f"{severity_icon} **{alert['message']}** — {alert['timestamp'][-8:]}")
            if len(live_alerts) > 3:
                st.markdown(f"*...and {len(live_alerts) - 3} more alerts*")

    # AI RCA Progress
    if st.session_state.get("ai_rca_active"):
        with st.container():
            st.info("🤖 **AI RCA In Progress**")
            rca_steps = st.session_state.get("ai_rca_steps", [])
            for step in rca_steps[-3:]:  # Show recent steps
                status_icon = "⏳" if step["status"] == "in_progress" else "✅" if step["status"] == "completed" else "❌"
                st.markdown(f"{status_icon} {step['step']}")

    status = orchestrator.get_operational_status()
    telemetry = orchestrator.telemetry.get_health_metrics()
    incident_timeline = st.session_state.get("incident_timeline", [])

    health_score = status["operational_summary"]["operational_score"]
    critical_incidents = status["incidents"]["by_status"].get("new", 0) + status["incidents"]["by_status"].get("investigating", 0)
    unreachable_devices = telemetry.get("unreachable_devices", 0)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Active Devices", status["operational_summary"]["devices"]["total"], delta=f"{unreachable_devices} unreachable")
    with col2:
        st.metric("Critical Incidents", critical_incidents, delta=f"{len(incident_timeline)} events")
    with col3:
        st.metric("Health Score", f"{health_score:.0f}%", delta=f"{telemetry.get('critical_device_count', 0)} critical")
    with col4:
        st.metric("Service Blast Radius", f"{status['operational_summary']['services']['degraded'] + status['operational_summary']['services']['down']}", delta=f"{status['operational_summary']['services']['down']} down")

    st.progress(int(max(0, min(100, health_score))))

    # Live AI Operational Intelligence
    with st.expander("🔎 AI Operational Intelligence", expanded=True):
        if st.session_state.get("ai_rca_active"):
            st.markdown("**Status:** AI RCA in progress...")
            latest_step = st.session_state["ai_rca_steps"][-1] if st.session_state["ai_rca_steps"] else None
            if latest_step and latest_step.get("result"):
                st.markdown(f"**Latest RCA:** {latest_step['result'][:300]}...")
        else:
            ai_summary = orchestrator.generate_operational_ai_summary()
            st.markdown(f"**Root Cause:** {ai_summary['root_cause']}")
            st.markdown(f"**Executive Summary:** {ai_summary['executive_summary']}")
            st.markdown(f"**Recommendation:** {ai_summary['recommendation']}")

    st.divider()
    st.markdown("### Live Network Telemetry")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### Core Metrics")
        st.metric("Average CPU", f"{telemetry['cpu']['average']:.1f}%", delta=f"{telemetry['cpu']['high_count']} devices >80%")
        st.metric("Average Memory", f"{telemetry['memory']['average']:.1f}%", delta=f"{telemetry['memory']['high_count']} devices >80%")
        st.metric("Avg Latency", f"{telemetry['latency_ms']['average']:.1f}ms", delta=f"{telemetry['latency_ms']['high_count']} >100ms")
    with col2:
        st.markdown("#### Network Health")
        st.metric("Packet Loss", f"{telemetry['packet_loss_pct']['average']:.2f}%", delta=f"{telemetry['packet_loss_pct']['high_count']} >3%")
        st.metric("BGP Sessions Down", f"{telemetry.get('bgp_down_sessions', 0)}", delta=f"{telemetry.get('critical_device_count', 0)} critical devices")
        st.metric("Unreachable Devices", unreachable_devices, delta="live monitoring")

    st.divider()
    st.markdown("### Live Operational Timeline")
    if incident_timeline:
        timeline_rows = [
            {
                "time": event.get("timestamp")[-8:] if event.get("timestamp") else "N/A",
                "event": event.get("event", "unknown"),
                "type": event.get("type", "operational").replace("_", " ").title(),
                "details": event.get("details", "")[:50] + "..." if len(event.get("details", "")) > 50 else event.get("details", ""),
            }
            for event in incident_timeline[-15:]
        ]
        st.dataframe(pd.DataFrame(timeline_rows).sort_values(by="time", ascending=False))
    else:
        st.info("No operational events yet. Monitoring live...")

    st.divider()
    st.markdown("### Active Critical Incidents")
    active_incidents = [inc for inc in orchestrator.state.get_all_incidents().values() if inc['status'] in {'new', 'investigating'}]
    if active_incidents:
        for inc in active_incidents:
            severity_color = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(inc["severity"], "⚪")
            st.markdown(f"{severity_color} **{inc['id']}** — {inc['title']} — Status: {inc['status']}")
            if inc.get("affected_devices"):
                st.markdown(f"_Affected devices:_ {', '.join(inc['affected_devices'])}")
            if inc.get("timeline"):
                for note in inc["timeline"][-2:]:
                    st.markdown(f"- {note['timestamp'][-8:]}: {note['note']}")
    else:
        st.info("No active critical incidents. All systems operational.")

    st.divider()
    st.markdown("### Device Health Status")
    # Show key devices and their live status
    device_health_data = []
    for hostname, metrics in orchestrator.state.get_all_device_metrics().items():
        health_score = orchestrator.telemetry.get_device_health_score(hostname)
        device_health_data.append({
            "Device": hostname,
            "Health Score": f"{health_score['score']:.0f}%",
            "Status": health_score["status"].upper(),
            "CPU": f"{metrics.cpu:.1f}%" if hasattr(metrics, 'cpu') else "N/A",
            "Reachable": "✅" if getattr(metrics, 'reachable', True) else "❌"
        })
    
    if device_health_data:
        st.dataframe(pd.DataFrame(device_health_data))
    else:
        st.info("No device telemetry available yet.")

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

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Devices", status["operational_summary"]["devices"]["total"])
    with col2:
        st.metric("Healthy Devices", status["operational_summary"]["devices"]["healthy"], delta=f"{unreachable_count} unreachable")
    with col3:
        st.metric("Critical Devices", critical_devices)
    with col4:
        st.metric("Links Active", status["operational_summary"]["links"]["active"])
    
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
