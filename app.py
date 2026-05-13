
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
    st.markdown("### Live Operational Storytelling — Continuous Simulation")

    if "demo_result" not in st.session_state:
        st.session_state["demo_result"] = {}

    if "operations_initialized" not in st.session_state:
        orchestrator.run_cycle()
        st.session_state["operations_initialized"] = True

    # Auto-run cycles continuously
    if "last_cycle_time" not in st.session_state:
        st.session_state["last_cycle_time"] = time.time()
    
    # Run a cycle every 3 seconds automatically
    current_time = time.time()
    if current_time - st.session_state["last_cycle_time"] > 3:
        cycle = orchestrator.run_cycle()
        st.session_state["demo_result"] = {"last_cycle": cycle}
        st.session_state["last_cycle_time"] = current_time

    demo_options = orchestrator.get_demo_scenarios()
    demo_labels = [scenario["label"] for scenario in demo_options]
    selected_demo_label = st.selectbox("Choose a demo scenario", demo_labels, key="demo_scenario_select")
    selected_demo_id = next((scenario["id"] for scenario in demo_options if scenario["label"] == selected_demo_label), demo_options[0]["id"])

    with st.expander("▶️ Simulation Controls", expanded=False):
        control_col1, control_col2, control_col3 = st.columns([2, 1, 1])
        with control_col1:
            if st.button("Launch Demo Scenario", type="primary", key="launch_demo"):
                with st.spinner("Launching autonomous demo scenario..."):
                    demo_result = orchestrator.launch_demo_scenario(selected_demo_id)
                    st.session_state["demo_result"] = demo_result
                    st.session_state["demo_selected"] = selected_demo_label
                    st.success(f"Demo '{selected_demo_label}' launched.")
        with control_col2:
            if st.button("Run next autonomous cycle", key="run_cycle"):
                cycle = orchestrator.run_cycle()
                st.session_state["demo_result"] = {"last_cycle": cycle}
                st.success(f"Completed cycle {cycle['cycle']} — {cycle['anomalies_detected']} anomalies detected.")
        with control_col3:
            if st.button("Reset Simulation", key="reset_sim"):
                # Reset simulation state
                orchestrator.simulator.time_step = 0
                orchestrator.simulator.workflow_stage = 0
                orchestrator.simulator.last_stage_change = 0
                orchestrator.simulator.anomalies = []
                st.session_state["demo_result"] = {}
                st.success("Simulation reset to initial state.")

    status = orchestrator.get_operational_status()
    topology = orchestrator.simulator.get_topology_summary()
    ai_summary = orchestrator.generate_operational_ai_summary()
    telemetry = orchestrator.telemetry.get_health_metrics()
    demo_result = st.session_state.get("demo_result", {})

    health_score = status["operational_summary"]["operational_score"]
    critical_incidents = status["incidents"]["by_status"].get("new", 0) + status["incidents"]["by_status"].get("investigating", 0)
    pending_events = status["operational_summary"]["events_pending"]
    workflows_active = status["operational_summary"]["workflows_active"]
    blast_radius = status["operational_summary"]["services"]["degraded"] + status["operational_summary"]["services"]["down"]

    # Current workflow stage indicator
    workflow_stage_names = {
        0: "Normal Operation",
        1: "Packet Loss Detected",
        2: "WAN Latency Spike", 
        3: "BGP Instability",
        4: "Voice Degradation",
        5: "Critical Incident"
    }
    current_stage = workflow_stage_names.get(orchestrator.simulator.workflow_stage, "Unknown")
    
    st.info(f"**Current Simulation Stage:** {current_stage} (Cycle: {orchestrator.simulator.time_step})")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Active Devices", topology.get("total_devices", 0), delta=f"{topology.get('healthy_devices', 0)} healthy")
    with col2:
        st.metric("Critical Incidents", critical_incidents, delta=f"{workflows_active} workflows")
    with col3:
        st.metric("Health Score", f"{health_score:.0f}%", delta=f"{pending_events} pending events")
    with col4:
        st.metric("Service Blast Radius", f"{blast_radius}", delta=f"{status['operational_summary']['services']['down']} down")

    st.progress(int(max(0, min(100, health_score))))

    with st.expander("🔎 AI Operational Intelligence", expanded=True):
        st.markdown(f"**Root Cause:** {ai_summary['root_cause']}")
        st.markdown(f"**Executive Summary:** {ai_summary['executive_summary']}")
        st.markdown(f"**Recommendation:** {ai_summary['recommendation']}")
        if ai_summary.get("critical_incidents"):
            st.markdown(f"**Active Critical Incidents:** {', '.join(ai_summary['critical_incidents'])}")

    if demo_result and demo_result.get("status") == "success":
        st.success(f"Demo '{st.session_state.get('demo_selected', selected_demo_label)}' launched successfully")

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
        st.metric("Services Healthy", f"{status['operational_summary']['services']['healthy']}")

    st.divider()
    st.markdown("### Recent Event Timeline")
    recent_events = orchestrator.get_demo_events(limit=15)
    if recent_events:
        event_rows = [
            {
                "timestamp": event.get("timestamp")[-8:] if event.get("timestamp") else "N/A",  # Show time only
                "event": event.get("type", "unknown").replace("_", " ").title(),
                "severity": event.get("severity", "info").upper(),
                "description": event.get("description", "No description")[:60] + "..." if len(event.get("description", "")) > 60 else event.get("description", "No description"),
            }
            for event in recent_events[-12:]
        ]
        st.dataframe(pd.DataFrame(event_rows).sort_values(by="timestamp", ascending=False))
    else:
        st.info("No events have been generated yet.")

    st.divider()
    st.markdown("### Active Incidents")
    active_incidents = [inc for inc in orchestrator.state.get_all_incidents().values() if inc['status'] in {'new', 'investigating'}]
    if active_incidents:
        for inc in active_incidents:
            severity_color = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(inc["severity"], "⚪")
            st.markdown(f"{severity_color} **{inc['id']}** — {inc['title']} — Status: {inc['status']}")
            if inc.get("affected_devices"):
                st.markdown(f"_Affected devices:_ {', '.join(inc['affected_devices'])}")
            if inc.get("affected_services"):
                st.markdown(f"_Affected services:_ {', '.join(inc['affected_services'])}")
            if inc.get("timeline"):
                for note in inc["timeline"][-2:]:
                    st.markdown(f"- {note['timestamp'][-8:]}: {note['note']}")
    else:
        st.info("No active incidents right now.")

    st.divider()
    st.markdown("### Topology Impact Snapshot")
    # Show key devices and their status
    key_devices = ["wan-delhi", "dc1-delhi", "rtr-delhi", "fw-delhi"]
    device_status_data = []
    for hostname in key_devices:
        device = orchestrator.simulator.devices.get(hostname)
        if device:
            device_status_data.append({
                "Device": hostname,
                "Status": device.status.upper(),
                "CPU": f"{device.cpu:.1f}%",
                "BGP Sessions": f"{sum(1 for s in device.bgp_sessions if s.get('state') == 'Established')}/{len(device.bgp_sessions)}"
            })
    
    if device_status_data:
        st.dataframe(pd.DataFrame(device_status_data))
    else:
        st.info("No topology data to display.")

elif workspace == "incident":
    st.header("🚨 Incident Management")
    
    status = orchestrator.get_operational_status()
    incidents_data = status["incidents"]
    open_incidents = incidents_data["by_status"].get("new", 0) + incidents_data["by_status"].get("investigating", 0)
    critical_count = sum(1 for inc in orchestrator.state.get_all_incidents().values() if inc.get("severity") == "critical")
    resolved_today = incidents_data["by_status"].get("resolved", 0)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Open Incidents", open_incidents)
    with col2:
        st.metric("Critical", critical_count)
    with col3:
        st.metric("Resolved Today", resolved_today)
    
    st.subheader("Active Incidents")
    all_incidents = orchestrator.state.get_all_incidents()
    
    if all_incidents:
        for inc_id, inc in all_incidents.items():
            if inc["status"] in ["new", "investigating"]:
                severity_color = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(inc["severity"], "⚪")
                st.error(f"{severity_color} **{inc_id}**: {inc['title']} - {inc['status']}")
                if inc.get("affected_devices"):
                    st.markdown(f"_Affected devices:_ {', '.join(inc['affected_devices'])}")
                if inc.get("affected_services"):
                    st.markdown(f"_Affected services:_ {', '.join(inc['affected_services'])}")
                if inc.get("timeline"):
                    for note in inc["timeline"][-3:]:
                        st.markdown(f"- {note['timestamp']}: {note['note']}")
    else:
        st.info("No active incidents")

elif workspace == "topology":
    st.header("🗺 Network Topology")
    
    topology = orchestrator.simulator.get_topology_summary()
    critical_devices = len(orchestrator.state.get_critical_devices())
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Nodes", topology.get("total_devices", 0))
    with col2:
        st.metric("Links", topology.get("total_links", 0))
    with col3:
        st.metric("Sites", len(topology.get("sites", {})))
    with col4:
        st.metric("Critical Devices", critical_devices)
    
    st.subheader("Topology Visualization")
    st.info("Interactive topology map would be displayed here")
    
    st.subheader("Network Links")
    links_data = [
        {"source": link.source, "target": link.destination, "type": link.link_type, "status": link.status}
        for link in orchestrator.simulator.links[:10]
    ]
    if links_data:
        st.dataframe(pd.DataFrame(links_data))
    else:
        st.info("No links available")

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
