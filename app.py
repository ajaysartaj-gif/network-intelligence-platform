
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
    # Operations Dashboard
    st.header("🚀 Operations Center")
    
    # Run simulation cycle button
    if st.button("🔄 Run Autonomous Cycle", type="primary"):
        with st.spinner("Running simulation cycle..."):
            cycle_result = orchestrator.run_cycle()
            if cycle_result["status"] == "success":
                st.success(f"Cycle {cycle_result['cycle']} completed in {cycle_result['duration_seconds']:.2f}s")
                st.info(f"Anomalies: {cycle_result['anomalies_detected']}, Incidents: {cycle_result['incidents_created']}")
            else:
                st.error(f"Cycle failed: {cycle_result.get('error', 'Unknown error')}")
        st.rerun()
    
    # Get live operational status
    status = orchestrator.get_operational_status()
    topology = orchestrator.simulator.get_topology_summary()
    
    # Key metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        active_devices = topology.get("total_devices", 0)
        st.metric("Active Devices", active_devices)
    with col2:
        critical_incidents = status["incidents"]["by_status"].get("new", 0) + status["incidents"]["by_status"].get("investigating", 0)
        st.metric("Critical Incidents", critical_incidents)
    with col3:
        automation_rate = "87%"  # Placeholder, could calculate from events
        st.metric("Automation Rate", automation_rate)
    with col4:
        mttr = "45min"  # Placeholder
        st.metric("MTTR", mttr)

    # AI Search
    st.subheader("🤖 AI Diagnostics")
    query = st.text_input(
        "Ask NetBrain AI",
        placeholder="Why is BGP flapping in Delhi DC?",
        key="ops_query"
    )

    # Input validation
    if query and len(query.strip()) < 5:
        st.warning("Please enter a more detailed question (at least 5 characters)")
        query = ""
    elif query and not any(keyword in query.lower() for keyword in ["why", "what", "how", "when", "where", "bgp", "cpu", "memory", "interface", "link", "packet", "latency"]):
        st.info("💡 Tip: Try asking about network issues like BGP, CPU, memory, interfaces, or links")
    
    if query:
        try:
            with st.spinner("Analyzing telemetry and topology..."):
                time.sleep(1)
                topology_data = orchestrator.get_sample_topology()
                device_states = get_devices() if DATABASE_AVAILABLE else orchestrator.get_sample_devices()
                incidents_data = get_incidents() if DATABASE_AVAILABLE else []
                
                ai_response = ask_ai(query)
                
                # Log AI query to database
                if DATABASE_AVAILABLE:
                    try:
                        from database.database import log_ai_query
                        log_ai_query(query, ai_response)
                    except Exception:
                        pass  # Non-critical, continue
                
                orchestrator_result = orchestrator.ai_troubleshoot(
                    query,
                    device_states,
                    topology_data["interfaces"],
                    topology_data["bgp_peers"],
                    incidents_data,
                    topology_data["links"],
                )

            col1, col2 = st.columns([2, 1])
            with col1:
                st.markdown("### 🔍 Root Cause Analysis")
                root_cause = orchestrator_result.get("root_cause", "Analysis incomplete")
                if "No obvious root cause" in root_cause:
                    st.warning(root_cause)
                else:
                    st.info(root_cause)
                
                st.markdown("### 📋 Key Entities")
                entities = orchestrator_result.get("entities", {})
                if entities.get("devices"):
                    st.write("**Devices:**", ", ".join(entities["devices"]))
                if entities.get("protocols"):
                    st.write("**Protocols:**", ", ".join(entities["protocols"]))
                if entities.get("vendors"):
                    st.write("**Vendors:**", ", ".join(entities["vendors"]))
                if not any(entities.values()):
                    st.write("*No specific entities detected*")
                    
            with col2:
                st.markdown("### 📊 Executive Summary")
                exec_summary = orchestrator_result.get("executive_summary", "Summary unavailable")
                st.success(exec_summary)
                
                st.markdown("### 🤖 AI Response")
                if ai_response and not ai_response.startswith("ERROR"):
                    st.write(ai_response)
                else:
                    st.error("AI response unavailable. Check API configuration.")
                    
        except Exception as e:
            st.error(f"Analysis failed: {str(e)}")
            st.info("Try rephrasing your question or check system status.")

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
