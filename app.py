
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
    st.markdown("### Demo Mode — Live Operational Storytelling")

    if "demo_result" not in st.session_state:
        st.session_state["demo_result"] = {}

    demo_options = orchestrator.get_demo_scenarios()
    demo_labels = [scenario["label"] for scenario in demo_options]
    selected_demo_label = st.selectbox("Choose a demo scenario", demo_labels, key="demo_scenario_select")
    selected_demo_id = next((scenario["id"] for scenario in demo_options if scenario["label"] == selected_demo_label), demo_options[0]["id"])

    if st.button("▶️ Launch Demo Scenario", type="primary"):
        with st.spinner("Launching autonomous demo scenario..."):
            demo_result = orchestrator.launch_demo_scenario(selected_demo_id)
            st.session_state["demo_result"] = demo_result
            st.session_state["demo_selected"] = selected_demo_label

    status = orchestrator.get_operational_status()
    topology = orchestrator.simulator.get_topology_summary()
    ai_summary = orchestrator.generate_operational_ai_summary()
    demo_result = st.session_state.get("demo_result", {})

    health_score = status["operational_summary"]["operational_score"]
    critical_incidents = status["incidents"]["by_status"].get("new", 0) + status["incidents"]["by_status"].get("investigating", 0)
    pending_events = status["operational_summary"]["events_pending"]
    workflows_active = status["operational_summary"]["workflows_active"]

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Active Devices", topology.get("total_devices", 0), delta=f"{topology.get('healthy_devices', 0)} healthy")
    with col2:
        st.metric("Critical Incidents", critical_incidents, delta=f"{workflows_active} workflows")
    with col3:
        st.metric("Health Score", f"{health_score:.0f}%", delta=f"{pending_events} pending events")
    with col4:
        st.metric("Demo Scenario", selected_demo_label)

    st.progress(int(max(0, min(100, health_score))))

    with st.expander("🔎 Current AI Operational Insights", expanded=True):
        st.markdown(f"**Root Cause:** {ai_summary['root_cause']}")
        st.markdown(f"**Executive Summary:** {ai_summary['executive_summary']}")
        st.markdown(f"**Recommendation:** {ai_summary['recommendation']}")
        if ai_summary.get("critical_incidents"):
            st.markdown(f"**Active Critical Incidents:** {', '.join(ai_summary['critical_incidents'])}")

    if demo_result and demo_result.get("status") == "success":
        st.success(f"Demo '{st.session_state.get('demo_selected', selected_demo_label)}' launched successfully")
        st.markdown("#### 🔔 Demo Event Timeline")
        event_rows = [
            {
                "timestamp": event.get("timestamp"),
                "event": event.get("type"),
                "severity": event.get("severity"),
                "description": event.get("description"),
            }
            for event in demo_result.get("event_history", [])
        ]
        if event_rows:
            st.dataframe(pd.DataFrame(event_rows).sort_values(by="timestamp", ascending=False).head(10))

    st.divider()
    st.markdown("### Live Operational Dashboard")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### Network Telemetry")
        telemetry = orchestrator.telemetry.get_health_metrics()
        st.metric("Average CPU", f"{telemetry['cpu']['average']:.1f}%", delta=f"{telemetry['cpu']['high_count']} high")
        st.metric("Average Memory", f"{telemetry['memory']['average']:.1f}%", delta=f"{telemetry['memory']['high_count']} high")
        st.metric("Avg Latency", f"{telemetry['latency_ms']['average']:.1f}ms", delta=f"{telemetry['packet_loss_pct']['high_count']} packet loss alerts")
    with col2:
        st.markdown("#### Impact Summary")
        st.metric("Services Healthy", f"{status['operational_summary']['services']['healthy']}")
        st.metric("Services Degraded", f"{status['operational_summary']['services']['degraded']}")
        st.metric("Services Down", f"{status['operational_summary']['services']['down']}")

    st.divider()
    st.markdown("### Active Incidents")
    active_incidents = [inc for inc in orchestrator.state.get_all_incidents().values() if inc['status'] in {'new', 'investigating'}]
    if active_incidents:
        for inc in active_incidents:
            severity_color = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(inc["severity"], "⚪")
            st.markdown(f"{severity_color} **{inc['id']}** — {inc['title']} — Status: {inc['status']}")
            if inc.get("affected_devices"):
                st.markdown(f"_Affected devices:_ {', '.join(inc['affected_devices'])}")
    else:
        st.info("No active incidents right now.")

    st.divider()
    st.markdown("### Topology Impact Snapshot")
    link_rows = [
        {"source": link.source, "target": link.destination, "type": link.link_type, "status": link.status}
        for link in orchestrator.simulator.links[:10]
    ]
    if link_rows:
        st.dataframe(pd.DataFrame(link_rows))
    else:
        st.info("No topology data to display.")

elif workspace == "incident":
    st.header("🚨 Incident Management")
    
    # Get live incident data
    status = orchestrator.get_operational_status()
    incidents_data = status["incidents"]
    
    # Incident metrics
    col1, col2, col3 = st.columns(3)
    with col1:
        open_incidents = incidents_data["by_status"].get("new", 0) + incidents_data["by_status"].get("investigating", 0)
        st.metric("Open Incidents", open_incidents)
    with col2:
        critical_count = sum(1 for inc in orchestrator.state.get_all_incidents().values() if inc.get("severity") == "critical")
        st.metric("Critical", critical_count)
    with col3:
        resolved_today = incidents_data["by_status"].get("resolved", 0)  # Placeholder, could track daily
        st.metric("Resolved Today", resolved_today)
    
    # Active incidents
    st.subheader("Active Incidents")
    all_incidents = orchestrator.state.get_all_incidents()
    
    if all_incidents:
        for inc_id, inc in all_incidents.items():
            if inc["status"] in ["new", "investigating"]:
                severity_color = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(inc["severity"], "⚪")
                st.error(f"{severity_color} **{inc_id}**: {inc['title']} - {inc['status']}")
    else:
        st.info("No active incidents")

elif workspace == "topology":
    st.header("🗺 Network Topology")
    
    # Get live topology data
    topology = orchestrator.simulator.get_topology_summary()
    
    # Topology metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Nodes", topology.get("total_devices", 0))
    with col2:
        st.metric("Links", topology.get("total_links", 0))
    with col3:
        st.metric("Sites", len(topology.get("sites", {})))
    with col4:
        healthy = topology.get("healthy_devices", 0)
        total = topology.get("total_devices", 1)
        health_pct = int((healthy / total) * 100) if total > 0 else 0
        st.metric("Health", f"{health_pct}%")
    
    st.subheader("Topology Visualization")
    st.info("Interactive topology map would be displayed here")
    
    # Live topology data
    st.subheader("Network Links")
    links_data = [
        {"source": link.source, "target": link.destination, "type": link.link_type, "status": link.status}
        for link in orchestrator.simulator.links[:10]  # Show first 10 links
    ]
    if links_data:
        st.dataframe(pd.DataFrame(links_data))
    else:
        st.info("No links available")

elif workspace == "security":
    st.header("🔒 Security Operations")
    
    # Security metrics
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Threats Detected", "24", "+5")
    with col2:
        st.metric("Compliance Score", "92%", "+1%")
    with col3:
        st.metric("Blocked Attacks", "156", "+12")
    
    st.subheader("Security Alerts")
    alerts = [
        {"type": "Intrusion", "device": "BLR-FW-01", "severity": "high", "description": "Suspicious traffic from unknown IP"},
        {"type": "Compliance", "device": "HYD-LEAF-02", "severity": "medium", "description": "Configuration drift detected"},
        {"type": "Anomaly", "device": "DEL-CORE-01", "severity": "low", "description": "Unusual BGP route changes"},
    ]
    
    for alert in alerts:
        if alert["severity"] == "high":
            st.error(f"🚨 {alert['type']}: {alert['description']} on {alert['device']}")
        elif alert["severity"] == "medium":
            st.warning(f"⚠️ {alert['type']}: {alert['description']} on {alert['device']}")
        else:
            st.info(f"ℹ️ {alert['type']}: {alert['description']} on {alert['device']}")

elif workspace == "executive":
    st.header("📈 Executive Dashboard")
    
    # Executive metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Network Health", "94%", "+2%")
    with col2:
        st.metric("Uptime", "99.97%", "0.01%")
    with col3:
        st.metric("MTTR", "45min", "-5min")
    with col4:
        st.metric("Cost Savings", "$2.3M", "+$150K")
    
    st.subheader("Key Insights")
    insights = [
        "Network reliability improved by 3% this quarter",
        "Automated incident resolution reduced MTTR by 15 minutes",
        "AI-driven diagnostics prevented 12 potential outages",
        "Compliance automation saved 200 hours of manual work",
    ]
    
    for insight in insights:
        st.success(f"✅ {insight}")
    
    st.subheader("Risk Analysis")
    risks = [
        {"level": "Low", "description": "Scheduled maintenance window approaching"},
        {"level": "Medium", "description": "Vendor security advisory for BGP protocol"},
        {"level": "High", "description": "Critical link utilization above 85%"},
    ]
    
    for risk in risks:
        if risk["level"] == "High":
            st.error(f"🔴 {risk['description']}")
        elif risk["level"] == "Medium":
            st.warning(f"🟠 {risk['description']}")
        else:
            st.info(f"🟢 {risk['description']}")

else:
    # Default operations view
    st.header("🚀 Operations Center")
    st.info("Select a workspace from the sidebar to get started")
