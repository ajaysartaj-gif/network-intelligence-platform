
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
    
    # Key metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Active Devices", "248", "12")
    with col2:
        st.metric("Critical Incidents", "3", "-1")
    with col3:
        st.metric("Automation Rate", "87%", "+2%")
    with col4:
        st.metric("MTTR", "45min", "-5min")

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
    
    # Incident metrics
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Open Incidents", "12", "2")
    with col2:
        st.metric("Critical", "3", "0")
    with col3:
        st.metric("Resolved Today", "8", "+3")
    
    # Active incidents
    st.subheader("Active Incidents")
    incidents = [
        {"id": "INC-001", "title": "BGP flap detected in Mumbai", "severity": "high", "status": "investigating"},
        {"id": "INC-002", "title": "Firewall CPU high in Bangalore", "severity": "critical", "status": "mitigating"},
        {"id": "INC-003", "title": "WAN latency spike in Delhi", "severity": "medium", "status": "new"},
    ]
    
    for inc in incidents:
        severity_color = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(inc["severity"], "⚪")
        st.error(f"{severity_color} **{inc['id']}**: {inc['title']} - {inc['status']}")

elif workspace == "topology":
    st.header("🗺 Network Topology")
    
    # Topology metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Nodes", "156")
    with col2:
        st.metric("Links", "234")
    with col3:
        st.metric("Sites", "12")
    with col4:
        st.metric("Regions", "3")
    
    st.subheader("Topology Visualization")
    st.info("Interactive topology map would be displayed here")
    
    # Sample topology data
    st.subheader("Network Links")
    links_data = [
        {"source": "DEL-CORE-01", "target": "MUM-EDGE-01", "type": "MPLS", "status": "up"},
        {"source": "MUM-EDGE-01", "target": "BLR-FW-01", "type": "Internet", "status": "up"},
        {"source": "BLR-FW-01", "target": "HYD-LEAF-02", "type": "LAN", "status": "warning"},
    ]
    st.dataframe(pd.DataFrame(links_data))

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
